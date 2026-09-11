"""Launch the configured Chromium-family browser without modifying its profile."""
import configparser
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess


def chromium_command():
    try:
        name=subprocess.run(['xdg-settings','get','default-web-browser'],capture_output=True,
                            text=True,timeout=3,check=True).stdout.strip()
        if '/' in name or not name.endswith('.desktop'):
            return None
        roots=[Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))]
        roots += [Path(p) for p in os.environ.get('XDG_DATA_DIRS','/usr/local/share:/usr/share').split(':')]
        for root in roots:
            file=root/'applications'/name
            if not file.is_file():
                continue
            config=configparser.ConfigParser(interpolation=None,strict=False)
            config.read(file)
            command=shlex.split(config['Desktop Entry']['Exec'])
            if not command or not any(word in (name+' '+command[0]).lower()
                                      for word in ('helium','chromium','chrome','brave','vivaldi','edge')):
                return None
            return [part for part in command if not part.startswith('%')]
    except (OSError,KeyError,ValueError,configparser.Error,subprocess.SubprocessError):
        pass
    return None


def launch(url):
    command=chromium_command()
    if command and (Path(command[0]).is_file() or shutil.which(command[0])):
        # App mode creates a dedicated window, rather than moving a window that
        # contains the user's unrelated tabs when they choose Move to glasses.
        subprocess.Popen([*command,'--new-window','--app='+url],stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,start_new_session=True)
        return True
    return False


def move_to_output(title,output):
    from .hyprland import hypr,available,PREFIX
    if not available():
        raise RuntimeError('Move the browser window to the glasses using your desktop’s window controls, then click Fullscreen.')
    monitors=hypr('monitors',query=True)
    target=next((m for m in monitors if m['name']==output and not m['name'].startswith(PREFIX)),None)
    if not target:
        raise RuntimeError('Select the connected glasses under Output display in Spacewalker Settings.')
    windows=hypr('clients',query=True)
    window=next((w for w in windows if w.get('mapped') and w.get('title','').startswith(title)),None)
    if not window:
        raise RuntimeError('The browser player window is not ready. Click Move to glasses again after the page opens.')
    selector='address:'+window['address']
    try:
        hypr('eval','local spacewalker_browser = true')
        lua=True
    except RuntimeError:
        lua=False
    if lua:
        hypr('eval','hl.dispatch(hl.dsp.window.move({monitor='+json.dumps(output)+
             ',window='+json.dumps(selector)+',follow=true}))')
        hypr('eval','hl.dispatch(hl.dsp.focus({window='+json.dumps(selector)+'}))')
    else:
        workspace=target['activeWorkspace']['name']
        workspace=workspace if workspace.isdigit() else 'name:'+workspace
        hypr('dispatch','movetoworkspacesilent',workspace+','+selector)
        hypr('dispatch','focuswindow',selector)
