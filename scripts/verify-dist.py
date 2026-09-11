"""Check release contents and write SHA-256 checksums; never upload artifacts."""
import hashlib
from pathlib import Path, PurePosixPath
import sys
import tarfile
import zipfile


ASSETS = {
    'spacewalker/shaders/scene.vert.glsl', 'spacewalker/shaders/scene.frag.glsl',
    'spacewalker/native/capture.c', 'spacewalker/native/protocols/wlr-screencopy-unstable-v1.xml',
    'spacewalker/web/index.html', 'spacewalker/web/player.js', 'spacewalker/web/player.css',
    'spacewalker/web/panorama.js', 'spacewalker/web/view.js',
    'spacewalker/icons/chevron-down.svg', 'spacewalker/icons/chevron-up.svg',
}
SOURCE = {'run.sh', 'scripts/setup.sh', 'scripts/install-app.sh', 'scripts/render-desktop.py',
          'scripts/import-sdk.py', 'scripts/check-release.sh', 'scripts/verify-dist.py',
          'packaging/70-viture.rules', 'packaging/spacewalker-linux.svg',
          'packaging/spacewalker-linux.desktop.in', 'tests/browser_view.mjs',
          'README.md', 'LICENSE', 'CHANGELOG.md', 'RELEASE.md'}


def verify(folder):
    packages = sorted([*folder.glob('*.whl'), *folder.glob('*.tar.gz')])
    if len(packages)!=2 or not any(p.suffix=='.whl' for p in packages):
        raise ValueError('Expected exactly one wheel and one source archive. Use a fresh dist directory.')
    checksums = []
    for package in packages:
        if package.suffix == '.whl':
            with zipfile.ZipFile(package) as archive:
                names = set(archive.namelist())
            required = ASSETS
        else:
            with tarfile.open(package) as archive:
                entries = archive.getmembers()
                if any(e.issym() or e.islnk() for e in entries):
                    raise ValueError('Unexpected link in source archive')
                names = {str(PurePosixPath(e.name).relative_to(PurePosixPath(e.name).parts[0])) for e in entries}
            required = ASSETS | SOURCE
        missing = required-names
        forbidden = {n for n in names if set(PurePosixPath(n).parts) &
                     {'vendor', 'artifacts', '.venv', '.git', '__pycache__'} or n.endswith(('.pyc', '.so'))}
        if missing or forbidden:
            raise ValueError(f'{package.name}: missing={sorted(missing)}, forbidden={sorted(forbidden)}')
        checksums.append(f'{hashlib.sha256(package.read_bytes()).hexdigest()}  {package.name}')
        print(f'Verified {package.name}: {len(names)} entries')
    (folder/'SHA256SUMS').write_text('\n'.join(checksums)+'\n')


if __name__ == '__main__':
    verify(Path(sys.argv[1] if len(sys.argv)>1 else 'dist'))
