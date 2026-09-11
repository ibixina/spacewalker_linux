"""Real X11 app used by the GUI integration test; logs actual server input events."""
import sys
from Xlib import X, display

d=display.Display()
w=d.screen().root.create_window(0,0,300,200,0,d.screen().root_depth,
    background_pixel=0x307050, event_mask=X.KeyPressMask|X.ButtonPressMask|X.ExposureMask)
w.set_wm_name('Integration test application')
w.map()
d.flush()
with open(sys.argv[1],'w',buffering=1) as out:
    while True:
        e=d.next_event()
        if e.type==X.KeyPress:
            out.write(f'key {d.keycode_to_keysym(e.detail,0)}\n')
        elif e.type==X.ButtonPress:
            out.write(f'button {e.detail}\n')
