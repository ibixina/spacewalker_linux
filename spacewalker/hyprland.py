"""Real outputs in the existing Hyprland session, with a separate capture guardian."""
import json
import mmap
import os
from pathlib import Path
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import time

from .desktop import Desktop
from .frames import FrameExchange
from .geometry import Layout
from .native_build import capture_helper

PREFIX = 'Spacewalker-'


def hypr(*args, query=False):
    result = subprocess.run(['hyprctl', *(['-j'] if query else []), *args],
                            capture_output=True, text=True, timeout=4)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Hyprland IPC failed.')
    if query:
        return json.loads(result.stdout)
    if result.stdout.strip() not in ('ok', ''):
        raise RuntimeError(result.stdout.strip())


def available():
    return bool(os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') and os.environ.get('WAYLAND_DISPLAY'))


class HyprlandDesktop(Desktop):
    native = True

    def __init__(self, layout, fps=60, source=None):
        super().__init__(layout, fps)
        self.source = source
        self.control = None
        self.monitors = []
        self.shortcuts = []
        self.native_log_offset = 0

    def start(self):
        if self.source:
            monitor = next((m for m in hypr('monitors',query=True) if m['name']==self.source),None)
            if not monitor or self.source.startswith(PREFIX):
                raise RuntimeError('The display selected for mirroring is no longer available.')
            if monitor.get('transform',0) != 0:
                raise RuntimeError('Mirroring currently requires a display without rotation or reflection.')
            # Capture physical pixels, independent of desktop UI scaling. Do not
            # mutate the GUI's layout from this startup thread.
            self.layout = Layout(1,monitor['width'],monitor['height'],self.layout.distance,
                                 self.layout.screen_degrees,self.layout.gap_degrees,dict(self.layout.placements))
        helper = capture_helper()
        self.temp = tempfile.TemporaryDirectory(prefix='spacewalker-monitors-')
        folder = Path(self.temp.name)
        self.log = open(folder/'desktop.log', 'w+b')
        self.control = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.control.bind(str(folder/'control.sock'))
        self.control.setblocking(False)
        os.chmod(folder/'control.sock', 0o600)
        path = folder/'frame'
        self.framefile = open(path, 'w+b')
        self.framefile.truncate(FrameExchange.size(self.layout.count*self.layout.width*self.layout.height*4))
        self.buffer = mmap.mmap(self.framefile.fileno(), 0)
        self.exchange = FrameExchange(self.framefile, self.buffer, self.layout.count*self.layout.width*self.layout.height*4)
        self.pending = bytearray()
        self.env = os.environ.copy()
        root = str(Path(__file__).resolve().parent.parent)
        self.env['PYTHONPATH'] = root+os.pathsep+self.env.get('PYTHONPATH', '')
        try:
            self.worker = subprocess.Popen([sys.executable, '-m', 'spacewalker.hyprworker', str(folder),
                helper, str(self.layout.count), str(self.layout.width), str(self.layout.height), str(self.fps), str(os.getpid()),
                self.source or ''],
                stdin=subprocess.PIPE, stdout=self.log, stderr=self.log, env=self.env, start_new_session=True, bufsize=0)
            os.set_blocking(self.worker.stdin.fileno(), False)
            deadline = time.monotonic()+15
            while not struct.unpack_from('Q', self.buffer)[0] or not (folder/'ready.json').exists():
                if self.worker.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('Native monitors could not start. '+self.log_text())
                time.sleep(.02)
            status = json.loads((folder/'ready.json').read_text())
            self.monitors, self.shortcuts = status['monitors'], status['shortcuts']
            self.lua = status['lua']
        except Exception:
            self.close()
            raise

    def poll_actions(self):
        actions = []
        if self.control:
            while True:
                try:
                    actions.append(self.control.recv(1024).decode())
                except BlockingIOError:
                    break
        return actions

    def command(self, **message):
        if message.get('type') not in ('motion','key','button','release'):
            super().command(**message)

    def windows(self):
        return [w for w in hypr('clients', query=True)
                if w.get('mapped') and w.get('pid') != os.getpid() and w.get('title')]

    def launch(self, command):
        args = shlex.split(command) if isinstance(command, str) else list(command)
        if not args:
            raise ValueError('Enter an application command.')
        # Host applications keep their Wayland session, clipboard and normal lifetime.
        # Hyprland's exec rule places newly mapped windows without changing focus first.
        target = self.monitors[len(self.monitors)//2]['activeWorkspace']['name']
        target = target if target.isdigit() else 'name:'+target
        if self.lua:
            hypr('eval','hl.dispatch(hl.dsp.exec_cmd('+json.dumps(shlex.join(args))+
                 ', {workspace='+json.dumps(target+' silent')+'}))')
        else:
            hypr('dispatch', 'exec', f'[workspace {target} silent] '+shlex.join(args))

    def close(self):
        # EOF tells the guardian to remove only its own monitors, even if the GUI crashes.
        if self.worker and self.worker.stdin:
            self.worker.stdin.close()
            try:
                self.worker.wait(timeout=8)
            except subprocess.TimeoutExpired:
                pass
        if self.control:
            self.control.close()
            self.control = None
        super().close()


def create_desktop(layout, fps=60, backend='auto', source=None):
    if source and (layout.count != 1 or backend == 'private'):
        raise RuntimeError('Mirroring a display requires single-screen mode on Hyprland.')
    if backend == 'hyprland' or (backend == 'auto' and available()):
        if not available():
            raise RuntimeError('Native Hyprland monitors require an active Hyprland Wayland session.')
        return HyprlandDesktop(layout, fps, source)
    if backend == 'auto':
        raise RuntimeError('Native monitors currently require Hyprland. Use --desktop-backend private for the separate X11 workspace.')
    return Desktop(layout, fps)
