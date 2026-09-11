"""Build the small native capture helper once, outside the render path."""
import hashlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


def capture_helper():
    root = Path(__file__).resolve().parent
    source = root/'native'
    protocol = source/'protocols/wlr-screencopy-unstable-v1.xml'
    digest = hashlib.sha256(b'O3-c11-v1'+(source/'capture.c').read_bytes()+protocol.read_bytes()).hexdigest()[:16]
    cache = Path(tempfile.gettempdir())/f'spacewalker-native-{os.getuid()}'
    cache.mkdir(mode=0o700, exist_ok=True)
    if cache.stat().st_uid != os.getuid() or cache.stat().st_mode & 0o077 or cache.is_symlink():
        raise RuntimeError('Unsafe native helper cache directory.')
    binary = cache/f'capture-{digest}'
    if binary.is_file():
        return str(binary)
    local = root.parent/'artifacts/wayland-dev/usr'
    scanner = shutil.which('wayland-scanner')
    include = []
    if not scanner and (local/'bin/wayland-scanner').is_file():
        scanner = str(local/'bin/wayland-scanner')
        include = ['-I'+str(local/'include')]
    if not scanner or not shutil.which('cc'):
        raise RuntimeError('Native monitors need a C compiler and Wayland headers. Fedora: sudo dnf install gcc wayland-devel')
    try:
        flags = shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client'],stderr=subprocess.DEVNULL,text=True))
    except (FileNotFoundError, subprocess.CalledProcessError):
        flags = ['-l:libwayland-client.so.0']
    with tempfile.TemporaryDirectory(dir=cache) as folder:
        folder = Path(folder)
        for kind, name in [('client-header','screencopy.h'),('private-code','screencopy.c')]:
            subprocess.run([scanner,kind,str(protocol),str(folder/name)],check=True,capture_output=True)
        build = subprocess.run(['cc','-O3','-std=c11','-Wall','-Wextra','-Wno-unused-parameter',
            '-I'+str(folder),*include,str(source/'capture.c'),str(folder/'screencopy.c'),
            '-o',str(folder/'capture'),*flags],capture_output=True,text=True)
        if build.returncode:
            raise RuntimeError('Cannot build Wayland capture helper: '+build.stderr)
        (folder/'capture').replace(binary)
    return str(binary)
