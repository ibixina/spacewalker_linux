"""Lifecycle of an authenticated, private X11 desktop, independent of host Wayland."""
from contextlib import contextmanager
from collections import deque
import json
import mmap
import os
from pathlib import Path
import secrets
import select
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time

from .frames import FrameExchange


def stop_process(process):
    if process is None:
        return
    # Each child has a new process group; only touch groups created by this app.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


class Desktop:
    native = False
    def __init__(self, layout, fps=60):
        self.layout, self.fps = layout, fps
        self.server = self.worker = self.home = None
        self.apps = []
        self.temp = None
        self.buffer = self.framefile = self.log = None
        self.display = None
        self.last_sequence = 0
        self.last_frame_started = self.last_frame_captured = 0.
        self.frame_generations = ()
        self.capture_ms = 0.
        self.capture_progress = deque(maxlen=600)

    def start(self):
        if not shutil.which('Xvfb') or not shutil.which('xauth'):
            raise RuntimeError('Install Xvfb and xauth. Fedora: sudo dnf install xorg-x11-server-Xvfb xorg-x11-xauth')
        self.temp = tempfile.TemporaryDirectory(prefix='spacewalker-')
        folder = Path(self.temp.name)
        auth = folder/'Xauthority'
        auth.touch(mode=0o600)
        # Xorg accepts the cookie regardless of this initial display label.
        cookie = secrets.token_hex(16)
        subprocess.run(['xauth', '-f', str(auth), 'add', ':0', '.', cookie], check=True, capture_output=True)
        readfd, writefd = os.pipe()
        self.log = open(folder/'desktop.log', 'w+b')
        w, h = self.layout.width*self.layout.count, self.layout.height
        try:
            self.server = subprocess.Popen(['Xvfb', '-displayfd', str(writefd), '-screen', '0',
                f'{w}x{h}x24', '-nolisten', 'tcp', '-auth', str(auth), '-noreset', '+extension', 'RANDR'],
                pass_fds=(writefd,), stdout=self.log, stderr=self.log, start_new_session=True)
            os.close(writefd)
            writefd = None
            if not select.select([readfd], [], [], 8)[0]:
                raise RuntimeError('Xvfb did not start within 8 seconds.')
            number = os.read(readfd, 32).decode().strip()
            if not number.isdigit():
                raise RuntimeError('Xvfb could not allocate a display. '+self.log_text())
            self.display = ':'+number
            subprocess.run(['xauth', '-f', str(auth), 'add', self.display, '.', cookie], check=True, capture_output=True)
            self.env = os.environ.copy()
            self.env.update(DISPLAY=self.display, XAUTHORITY=str(auth), QT_QPA_PLATFORM='xcb',
                            GDK_BACKEND='x11', MOZ_ENABLE_WAYLAND='0', XDG_SESSION_TYPE='x11')
            self.env.pop('WAYLAND_DISPLAY', None)
            # Resolve this package for subprocesses even when launched outside the repo.
            root = str(Path(__file__).resolve().parent.parent)
            self.env['PYTHONPATH'] = root+os.pathsep+self.env.get('PYTHONPATH', '')
            path = folder/'frame'
            self.framefile = open(path, 'w+b')
            self.framefile.truncate(FrameExchange.size(w*h*4))
            self.buffer = mmap.mmap(self.framefile.fileno(), 0)
            self.exchange = FrameExchange(self.framefile,self.buffer,w*h*4)
            self.worker = subprocess.Popen([sys.executable, '-m', 'spacewalker.xworker',
                str(path), str(self.layout.count), str(self.layout.width), str(h), str(self.fps)],
                env=self.env, stdin=subprocess.PIPE, stdout=self.log, stderr=self.log,
                start_new_session=True, bufsize=0)
            os.set_blocking(self.worker.stdin.fileno(), False)
            self.pending = bytearray()
            deadline = time.monotonic()+8
            while struct.unpack_from('Q', self.buffer)[0] == 0:
                if self.worker.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Desktop capture failed. '+self.log_text())
                time.sleep(.02)
        except Exception:
            self.close()
            raise
        finally:
            os.close(readfd)
            if writefd is not None:
                os.close(writefd)

    def log_text(self):
        if self.log is None:
            return ''
        self.log.flush()
        return os.pread(self.log.fileno(), 8000, max(0, os.fstat(self.log.fileno()).st_size-8000)).decode(errors='replace')

    def frame(self):
        # Copying compatibility API for consumers that keep pixels after returning.
        with self.frame_view() as pixels:
            return pixels.tobytes() if pixels is not None else None

    @contextmanager
    def frame_view(self):
        # Borrow pixels only for the upload; no full-frame copy on the render thread.
        if self.worker.poll() is not None:
            raise RuntimeError('Desktop stopped. '+self.log_text())
        self.flush_input()
        with self.exchange.read(self.last_sequence) as frame:
            if frame is not None:
                self.last_sequence = frame.sequence
                self.last_frame_started = frame.started
                self.last_frame_captured = frame.captured
                self.frame_generations = frame.generations
                self.capture_ms = (frame.captured-frame.started)*1000
                self.capture_progress.append((frame.captured,frame.sequence))
            yield frame.pixels if frame is not None else None

    @property
    def capture_fps(self):
        if len(self.capture_progress)<2:
            return None
        t0,s0 = self.capture_progress[0]
        t1,s1 = self.capture_progress[-1]
        return (s1-s0)/(t1-t0) if t1>t0 else None

    def command(self, **message):
        self.pending.extend(json.dumps(message).encode()+b'\n')
        self.flush_input()

    def flush_input(self):
        if self.pending:
            try:
                n = os.write(self.worker.stdin.fileno(), self.pending)
                del self.pending[:n]
            except BlockingIOError:
                pass
            except BrokenPipeError:
                self.pending.clear()

    def launch(self, command):
        args = shlex.split(command) if isinstance(command, str) else command
        if not args:
            raise ValueError('Enter an application command.')
        proc = subprocess.Popen(args, env=self.env, stdout=self.log, stderr=self.log, start_new_session=True)
        self.apps.append(proc)
        return proc

    def close(self):
        for p in reversed(self.apps):
            stop_process(p)
        self.apps.clear()
        stop_process(self.worker)
        stop_process(self.server)
        self.worker = self.server = None
        if self.buffer is not None:
            self.buffer.close()
            self.buffer = None
        if self.framefile:
            self.framefile.close()
            self.framefile = None
        if self.log:
            self.log.close()
            self.log = None
        if self.temp:
            self.temp.cleanup()
            self.temp = None
