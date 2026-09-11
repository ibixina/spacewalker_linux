"""Own native outputs independently of the GUI; parent-pipe EOF always detaches them."""
import fcntl
import json
import os
from pathlib import Path
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time

from .hyprland import PREFIX, hypr


def monitor_geometry(monitor):
    return tuple(monitor.get(k, 0) for k in ('x','y','width','height','scale','transform'))


def layout_problem(monitors, original):
    """Validate logical rectangles, including scale/rotation, without moving host outputs."""
    current = {m['name']:m for m in monitors if not m.get('disabled')}
    for before in original:
        after = current.get(before['name'])
        if after is None or monitor_geometry(after) != monitor_geometry(before):
            return f'Hyprland changed the existing display {before["name"]} while attaching XR monitors.'
    rectangles = []
    for m in current.values():
        if m.get('mirrorOf', 'none') not in ('none', '', None):
            continue
        scale = m.get('scale', 1)
        if scale <= 0:
            return f'Invalid scale on {m["name"]}.'
        w, h = m['width'], m['height']
        if m.get('transform', 0) % 2:
            w, h = h, w
        x, y = m['x'], m['y']
        right, bottom = x+w/scale, y+h/scale
        for name, left, top, r, b in rectangles:
            if min(right,r)-max(x,left)>0.01 and min(bottom,b)-max(y,top)>0.01:
                return f'Hyprland placed {m["name"]} over {name}.'
        rectangles.append((m['name'], x, y, right, bottom))
    return None


class Outputs:
    def __init__(self, folder, count, width, height, fps, gui_pid, source=None):
        self.folder, self.count, self.width, self.height, self.fps = folder, count, width, height, fps
        self.gui_pid = gui_pid
        self.created, self.shortcuts = [], []
        self.lua = None
        self.token = 'spacewalker_'+folder.name.rsplit('-', 1)[-1].replace('-', '_')
        self.monitors = []
        self.workspaces = {}
        self.lock = None
        self.source = source

    @property
    def capture_names(self):
        return [self.source] if self.source else self.created

    def start(self):
        cache = Path(tempfile.gettempdir())/f'spacewalker-native-{os.getuid()}'
        self.lock = open(cache/'monitors.lock', 'a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Native monitors are already running in another Spacewalker instance.')
        existing = hypr('monitors', 'all', query=True)
        if any(m['name'].startswith(PREFIX) for m in existing):
            raise RuntimeError('Spacewalker outputs already exist. Close the instance that owns them before reconnecting.')
        physical = [m for m in existing if not m.get('disabled')]
        if not physical:
            raise RuntimeError('Connect a physical display before starting XR monitors.')
        if self.source:
            source = next((m for m in physical if m['name']==self.source),None)
            if not source or self.count!=1 or source.get('transform',0)!=0 or (
                    source['width'],source['height'])!=(self.width,self.height):
                raise RuntimeError('The source display changed. Select it again to restart mirroring.')
            self.monitors = [source]
            try:
                hypr('eval','local spacewalker_mirror = true')
                self.lua = True
            except RuntimeError:
                self.lua = False
            self.install_shortcuts()
            return  # Borrow this output; never configure, create, or remove it.
        original_errors = set(hypr('configerrors', query=True))
        names = [f'{PREFIX}{i+1}' for i in range(self.count)]
        # Prepare every rule before activating any output. Lua rules can survive a
        # previous session, with a different mode or an overlapping fixed offset.
        for name in names:
            self.configure_monitor(name)
        self.configure_workspaces(names)
        for name in names:
            hypr('output', 'create', 'headless', name)
            self.created.append(name)
            self.wait_for_monitors(physical)
        new_errors = [e for e in hypr('configerrors', query=True) if e.strip() and e not in original_errors]
        if new_errors:
            raise RuntimeError('Hyprland rejected the monitor setup: '+'; '.join(new_errors))
        self.install_shortcuts()

    def configure_workspaces(self,names):
        # Fresh workspaces avoid adopting a host workspace whose fade/render
        # state belongs to a different output. Only our temporary rules change.
        if self.lua:
            hypr('eval',self.token+'_workspaces = {}')
        for index,name in enumerate(names):
            workspace=f'{self.token}-{index+1}'
            self.workspaces[name]=workspace
            if self.lua:
                hypr('eval','table.insert('+self.token+'_workspaces, hl.workspace_rule({workspace='+
                     json.dumps('name:'+workspace)+', monitor='+json.dumps(name)+', default=true, persistent=false}))')
            else:
                hypr('keyword','workspace',f'name:{workspace},monitor:{name},default:true,persistent:false')

    def configure_monitor(self, name):
        # Fixed offsets push existing "auto" laptop outputs around. Appending
        # auto-right outputs preserves the original monitor placement order.
        rule = f'{name},{self.width}x{self.height}@{self.fps},auto-right,1,transform,0'
        if self.lua is not True:
            try:
                hypr('keyword', 'monitor', rule)
                self.lua = False
                return
            except RuntimeError as e:
                if self.lua is False or 'non-legacy' not in str(e):
                    raise
                self.lua = True
        hypr('eval', 'hl.monitor({output='+json.dumps(name)+
             f', mode="{self.width}x{self.height}@{self.fps}", position="auto-right", scale=1, transform=0, disabled=false, mirror=""}})')

    def wait_for_monitors(self, original):
        deadline = time.monotonic()+6
        stable = 0
        problem = None
        activated = set()
        while True:
            monitors = hypr('monitors', query=True)
            current = {m['name']:m for m in monitors}
            self.monitors = [current[n] for n in self.created if n in current]
            problem = layout_problem(monitors, original)
            valid_modes = len(self.monitors)==len(self.created) and all(
                m['width']==self.width and m['height']==self.height and m['scale']==1
                and m.get('transform',0)==0 and abs(m['refreshRate']-self.fps)<1
                for m in self.monitors)
            wrong_workspaces = [m['name'] for m in self.monitors
                                if m.get('activeWorkspace',{}).get('name')!=self.workspaces.get(m['name'])]
            if valid_modes and not problem:
                # Hyprland can restore the previous active workspace when an
                # output name is reused, despite its new default-workspace rule.
                # Explicitly select our fresh workspace before starting capture.
                for name in wrong_workspaces:
                    if name not in activated:
                        self.activate_workspace(name)
                        activated.add(name)
            stable = stable+1 if valid_modes and not problem and not wrong_workspaces else 0
            if stable >= 2:
                return
            if time.monotonic()>deadline:
                if not problem and valid_modes and wrong_workspaces:
                    problem = 'Hyprland did not activate the workspace on '+', '.join(wrong_workspaces)+'.'
                raise RuntimeError(problem or 'Hyprland did not apply the virtual monitor mode.')
            time.sleep(.05)

    def activate_workspace(self,name):
        workspace = 'name:'+self.workspaces[name]
        if self.lua:
            # Save and restore focus within a single compositor event, so setup
            # does not pull the pointer or keyboard away from the user's app.
            hypr('eval','local window = hl.get_active_window(); '
                 'local monitor = hl.get_active_monitor(); local cursor = hl.get_cursor_pos(); '
                 'hl.dispatch(hl.dsp.focus({workspace='+json.dumps(workspace)+'})); '
                 'if window then hl.dispatch(hl.dsp.focus({window=window})) '
                 'elseif monitor then hl.dispatch(hl.dsp.focus({monitor=monitor})) end; '
                 'if cursor then hl.dispatch(hl.dsp.cursor.move(cursor)) end')
        else:
            window = hypr('activewindow',query=True)
            monitor = next((m['name'] for m in hypr('monitors',query=True) if m.get('focused')),None)
            cursor = hypr('cursorpos',query=True)
            try:
                hypr('dispatch','workspace',workspace)
            finally:
                if window.get('address'):
                    hypr('dispatch','focuswindow','address:'+window['address'])
                elif monitor:
                    hypr('dispatch','focusmonitor',monitor)
                hypr('dispatch','movecursor',f'{cursor["x"]} {cursor["y"]}')

    def install_shortcuts(self):
        existing = hypr('binds', query=True)
        requests = [('R','recenter'), ('F','fullscreen'), ('A','arrange')]
        requests += [(str(i+1),f'move:{i}') for i in range(self.count)]
        requests += [('0','controls')]
        if self.lua:
            hypr('eval', self.token+' = {}')
        script = Path(__file__).with_name('control.py')
        for key, action in requests:
            # Do not override any existing binding on the same chord, including submaps.
            if any(b['modmask']==12 and (b['key'].upper()==key or b.get('keycode',0)) for b in existing):
                continue
            command = shlex.join([sys.executable, str(script), str(self.folder/'control.sock'), action])
            if self.lua:
                hypr('eval', f'table.insert({self.token}, hl.bind("CTRL + ALT + {key}", '
                     'hl.dsp.exec_cmd('+json.dumps(command)+'), {description='+json.dumps(self.token)+'}))')
            else:
                hypr('keyword', 'bindd', f'CTRL ALT, {key}, {self.token}, exec, {command}')
            self.shortcuts.append({'key':key,'action':action})

    def command(self, msg):
        kind = msg.get('type')
        if kind in ('motion','button','key','release'):
            return  # Input is delivered normally by the host compositor.
        if kind == 'focus_at':
            x, y = int(msg['x']), int(msg['y'])
            index = max(0,min(self.count-1,x//self.width))
            monitor = self.current_monitor(index)
            scale = monitor.get('scale',1)
            px = round(monitor['x']+(x%self.width)/scale)
            py = round(monitor['y']+max(0,min(self.height-1,y))/scale)
            if self.lua:
                hypr('eval',f'hl.dispatch(hl.dsp.cursor.move({{x={px},y={py}}}))')
            else:
                hypr('dispatch','movecursor',f'{px} {py}')
        elif kind in ('move_to','move'):
            active = hypr('activewindow', query=True)
            address = msg.get('address', active.get('address'))
            windows = hypr('clients', query=True)
            target = next((w for w in windows if w['address']==address), None)
            if target and target.get('pid')==self.gui_pid and 'address' not in msg:
                candidates = [w for w in windows if w.get('mapped') and w.get('pid')!=self.gui_pid
                              and w.get('focusHistoryID',-1)>=0]
                target = min(candidates, key=lambda w:w['focusHistoryID'], default=None)
                address = target['address'] if target else None
            if not target or target.get('pid') == self.gui_pid:
                return  # Never move the XR renderer onto a captured monitor.
            index = int(msg.get('screen', self.count//2))
            if kind == 'move':
                current = next((i for i,m in enumerate(self.monitors) if m['id']==target['monitor']),self.count//2)
                index = (current+int(msg['delta']))%self.count
            monitor = self.current_monitor(index)
            ws = monitor['activeWorkspace']['name']
            spec = ws if ws.isdigit() else 'name:'+ws
            if self.lua:
                hypr('eval','hl.dispatch(hl.dsp.window.move({monitor='+json.dumps(monitor['name'])+
                     ',window='+json.dumps('address:'+address)+',follow=false}))')
            else:
                hypr('dispatch','movetoworkspacesilent',f'{spec},address:{address}')
        elif kind == 'cycle':
            if self.lua:
                hypr('eval','hl.dispatch(hl.dsp.window.cycle_next())')
            else:
                hypr('dispatch','cyclenext')
        elif kind == 'focus_viewer':
            viewer = next((w for w in hypr('clients', query=True) if w.get('pid')==self.gui_pid), None)
            if viewer:
                selector = 'address:'+viewer['address']
                if self.lua:
                    hypr('eval','hl.dispatch(hl.dsp.focus({window='+json.dumps(selector)+'}))')
                else:
                    hypr('dispatch','focuswindow',selector)

    def current_monitor(self,index):
        if not 0 <= index < self.count:
            raise ValueError('Invalid monitor number.')
        name = self.capture_names[index]
        return next(m for m in hypr('monitors', query=True) if m['name']==name)

    def close(self):
        # A config reload may already have removed our bindings. Only unbind chords
        # whose current description still identifies this guardian.
        try:
            binds = hypr('binds', query=True)
            for shortcut in self.shortcuts:
                key = shortcut['key']
                matches = [b for b in binds if b['modmask']==12 and b['key'].upper()==key]
                if matches and all(b.get('description')==self.token for b in matches):
                    if self.lua:
                        hypr('eval', f'hl.unbind("CTRL + ALT + {key}")')
                    else:
                        hypr('keyword', 'unbind', f'CTRL ALT, {key}')
            if self.lua:
                hypr('eval', self.token+' = nil')
        except Exception as e:
            print('Shortcut cleanup:', e, flush=True)
        try:
            if self.lua:
                hypr('eval','for _, rule in ipairs('+self.token+'_workspaces or {}) do rule:set_enabled(false) end; '+
                     self.token+'_workspaces = nil')
            else:
                for name,workspace in self.workspaces.items():
                    hypr('keyword','workspace',f'name:{workspace},monitor:{name},default:false,persistent:false')
        except Exception as e:
            print('Workspace rule cleanup:', e, flush=True)
        for name in reversed(self.created):
            try:
                # Hyprland migrates windows/workspaces; it does not close their apps.
                hypr('output', 'remove', name)
                if self.lua is False:
                    hypr('keyword', 'monitor', name+',remove')
            except Exception as e:
                print('Monitor cleanup:', name, e, flush=True)
        if self.lock:
            self.lock.close()


def main():
    folder, helper, count, width, height, fps, pid, *source = sys.argv[1:]
    owner = Outputs(Path(folder), int(count), int(width), int(height), int(fps), int(pid),
                    source[0] if source and source[0] else None)
    capture = None
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        owner.start()
        capture = subprocess.Popen([helper,str(owner.folder/'frame'),width,height,fps,*owner.capture_names],stdin=subprocess.PIPE)
        (owner.folder/'ready.json').write_text(json.dumps({'monitors':owner.monitors,'shortcuts':owner.shortcuts,'lua':owner.lua}))
        pending = bytearray()
        while running:
            if capture.poll() is not None:
                raise RuntimeError('Native monitor capture stopped.')
            if select.select([sys.stdin],[],[],.1)[0]:
                data = os.read(sys.stdin.fileno(),65536)
                if not data:
                    break
                pending.extend(data)
                while b'\n' in pending:
                    line, _, pending = pending.partition(b'\n')
                    try:
                        owner.command(json.loads(line))
                    except Exception as e:
                        print('Monitor action:', e, flush=True)
    finally:
        if capture:
            capture.stdin.close()
            try:
                capture.wait(timeout=2)
            except subprocess.TimeoutExpired:
                capture.terminate()
                capture.wait(timeout=2)
        owner.close()


if __name__ == '__main__':
    main()
