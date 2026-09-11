"""Private X server capture, input, and a small per-screen tiling window manager.

Runs in a subprocess with its own Xauthority so host GUI authentication is untouched.
"""
import json
import mmap
import os
import select
import subprocess
import sys
import time
import mss
from Xlib import X, XK, Xatom, display, error
from Xlib.ext import xtest
from Xlib.protocol import event
from .frames import FrameExchange, next_capture_deadline


class WindowManager:
    def __init__(self, d, count, width, height):
        self.d, self.root = d, d.screen().root
        self.count, self.width, self.height = count, width, height
        self.windows, self.slots = [], {}
        self.active = None
        self.pressed_keys, self.pressed_buttons = set(), set()
        d.set_error_handler(lambda *args: None)  # Windows may close between queued events.
        self.root.change_attributes(event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
                                    background_pixel=0x121212)
        self.root.clear_area(0, 0, count*width, height)
        self.atoms = {n: d.intern_atom(n) for n in ['_NET_SUPPORTED', '_NET_CLIENT_LIST',
            '_NET_ACTIVE_WINDOW', '_NET_WM_STATE', '_NET_WM_STATE_FULLSCREEN', '_NET_WM_NAME',
            '_NET_SUPPORTING_WM_CHECK', 'UTF8_STRING', 'WM_PROTOCOLS', 'WM_DELETE_WINDOW']}
        self.check = self.root.create_window(0, 0, 1, 1, 0, d.screen().root_depth)
        for win in (self.root, self.check):
            win.change_property(self.atoms['_NET_SUPPORTING_WM_CHECK'], Xatom.WINDOW, 32, [self.check.id])
        self.check.change_property(self.atoms['_NET_WM_NAME'], self.atoms['UTF8_STRING'], 8, b'Spacewalker tiler')
        self.root.change_property(self.atoms['_NET_SUPPORTED'], Xatom.ATOM, 32,
            [self.atoms[n] for n in ['_NET_CLIENT_LIST', '_NET_ACTIVE_WINDOW', '_NET_WM_STATE', '_NET_WM_STATE_FULLSCREEN']])
        self.publish()
        d.sync()

    def publish(self):
        self.root.change_property(self.atoms['_NET_CLIENT_LIST'], Xatom.WINDOW, 32, [w.id for w in self.windows])

    def tile(self, w):
        slot = self.slots[w.id]
        w.configure(x=slot*self.width, y=0, width=self.width, height=self.height, border_width=0)
        # A client may request a different size while the tiled geometry stays unchanged.
        # X then emits no real ConfigureNotify; GTK waits for the WM acknowledgement to draw.
        w.send_event(event.ConfigureNotify(event=w, window=w, above_sibling=X.NONE,
            x=slot*self.width, y=0, width=self.width, height=self.height,
            border_width=0, override=False), event_mask=X.StructureNotifyMask)

    def focus(self, w):
        if w is None or w.id not in self.slots:
            return
        self.active = w
        w.configure(stack_mode=X.Above)
        w.set_input_focus(X.RevertToPointerRoot, X.CurrentTime)
        self.root.change_property(self.atoms['_NET_ACTIVE_WINDOW'], Xatom.WINDOW, 32, [w.id])

    def events(self):
        while self.d.pending_events():
            e = self.d.next_event()
            if e.type == X.MapRequest:
                w = e.window
                if w.id not in self.slots:
                    parent = w.get_wm_transient_for()
                    order = sorted(range(self.count), key=lambda slot: abs(slot-(self.count-1)/2))
                    fallback = self.slots.get(self.active.id, order[0]) if self.active else order[0]
                    target = next((slot for slot in order if slot not in self.slots.values()), fallback)
                    self.slots[w.id] = self.slots.get(parent.id, target) if parent else target
                    self.windows.append(w)
                    w.change_attributes(event_mask=X.EnterWindowMask)
                self.tile(w)
                w.map()
                self.focus(w)
                self.publish()
            elif e.type == X.ConfigureRequest:
                if e.window.id in self.slots:
                    self.tile(e.window)
                else:
                    values = {name: getattr(e, name) for bit, name in [(X.CWX, 'x'), (X.CWY, 'y'),
                        (X.CWWidth, 'width'), (X.CWHeight, 'height'), (X.CWBorderWidth, 'border_width'),
                        (X.CWStackMode, 'stack_mode')] if e.value_mask & bit}
                    e.window.configure(**values)
            elif e.type in (X.DestroyNotify, X.UnmapNotify):
                if e.window.id in self.slots:
                    self.windows = [w for w in self.windows if w.id != e.window.id]
                    del self.slots[e.window.id]
                    if self.active and self.active.id == e.window.id:
                        self.active = None
                        if self.windows:
                            self.focus(self.windows[-1])
                    self.publish()
            elif e.type == X.EnterNotify:
                self.focus(e.window)
            elif e.type == X.ClientMessage:
                if e.client_type == self.atoms['_NET_ACTIVE_WINDOW']:
                    self.focus(e.window)
                elif e.client_type == self.atoms['_NET_WM_STATE'] and e.window.id in self.slots:
                    self.tile(e.window)
        self.d.flush()

    def command(self, msg):
        kind = msg['type']
        if kind == 'motion':
            xtest.fake_input(self.d, X.MotionNotify, x=max(0, min(self.count*self.width-1, msg['x'])),
                             y=max(0, min(self.height-1, msg['y'])))
        elif kind == 'button':
            code, down = int(msg['code']), bool(msg['down'])
            xtest.fake_input(self.d, X.ButtonPress if down else X.ButtonRelease, code)
            (self.pressed_buttons.add if down else self.pressed_buttons.discard)(code)
        elif kind == 'key':
            # Qt delivers a keysym from X11, or our viewer maps Wayland keys to X keysyms.
            keysym, down = int(msg['keysym']), bool(msg['down'])
            code = self.d.keysym_to_keycode(keysym)
            if code:
                xtest.fake_input(self.d, X.KeyPress if down else X.KeyRelease, code)
                (self.pressed_keys.add if down else self.pressed_keys.discard)(code)
        elif kind == 'release':
            for code in self.pressed_keys:
                xtest.fake_input(self.d, X.KeyRelease, code)
            for code in self.pressed_buttons:
                xtest.fake_input(self.d, X.ButtonRelease, code)
            self.pressed_keys.clear()
            self.pressed_buttons.clear()
        elif kind == 'cycle' and self.windows:
            index = self.windows.index(self.active) if self.active in self.windows else -1
            self.focus(self.windows[(index+1)%len(self.windows)])
        elif kind == 'move' and self.active:
            self.slots[self.active.id] = (self.slots[self.active.id]+msg['delta'])%self.count
            self.tile(self.active)
        elif kind == 'move_to' and self.active and 0 <= msg['screen'] < self.count:
            self.slots[self.active.id] = msg['screen']
            self.tile(self.active)
        elif kind == 'close' and self.active:
            self.active.send_event(event.ClientMessage(window=self.active, client_type=self.atoms['WM_PROTOCOLS'],
                data=(32, [self.atoms['WM_DELETE_WINDOW'], X.CurrentTime, 0, 0, 0])))
        self.d.flush()


def main():
    path, count, width, height, fps = sys.argv[1:]
    count, width, height, fps = map(int, (count, width, height, fps))
    d = display.Display()
    wm = WindowManager(d, count, width, height)
    # Logical RandR monitors help applications choose sensible maximize and dialog bounds.
    for index in range(count):
        try:
            subprocess.run(['xrandr', '--setmonitor', f'SW-{index+1}',
                f'{width}/340x{height}/190+{index*width}+0', 'none'], capture_output=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass
    os.set_blocking(sys.stdin.fileno(), False)
    pending, sequence = b'', 0
    with open(path, 'r+b') as f, mmap.mmap(f.fileno(), 0) as buf, mss.mss() as capture:
        exchange = FrameExchange(f,buf,count*width*height*4)
        deadline = time.monotonic()
        while True:
            wait = max(0., deadline-time.monotonic())
            ready, _, _ = select.select([sys.stdin, d.fileno()], [], [], wait)
            if sys.stdin in ready:
                chunk = os.read(sys.stdin.fileno(), 65536)
                if not chunk:
                    break
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    wm.command(json.loads(line))
            wm.events()
            if time.monotonic() >= deadline:
                started = time.monotonic()
                shot = capture.grab({'left': 0, 'top': 0, 'width': count*width, 'height': height})
                captured = time.monotonic()
                if exchange.publish(shot.raw,sequence+1,started,captured):
                    sequence += 1
                deadline = next_capture_deadline(deadline,time.monotonic(),1/fps)
    wm.command({'type': 'release'})
    d.close()


if __name__ == '__main__':
    main()
