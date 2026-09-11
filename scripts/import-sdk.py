#!/usr/bin/env python3
"""Install a user-provided VITURE SDK archive locally, never into system paths."""
from pathlib import Path
import shutil
import stat
import sys
from zipfile import ZipFile


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 scripts/import-sdk.py /path/to/VITURE_SDK.zip')
    target = Path(__file__).resolve().parent.parent/'vendor'/'viture'
    target.mkdir(parents=True, exist_ok=True)
    with ZipFile(Path(sys.argv[1]).expanduser()) as archive:
        links = []
        for info in archive.infolist():
            dest = target/info.filename
            if not dest.resolve().is_relative_to(target.resolve()):
                raise ValueError('Archive contains an unsafe path')
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if stat.S_ISLNK(info.external_attr >> 16):
                link = archive.read(info).decode()
                if not (dest.parent/link).resolve().is_relative_to(target.resolve()):
                    raise ValueError('Archive contains an unsafe symlink')
                links.append((dest, link))
            else:
                if dest.is_symlink():
                    dest.unlink()
                with archive.open(info) as source, dest.open('wb') as out:
                    shutil.copyfileobj(source, out)
        for dest, link in links:
            if dest.exists() or dest.is_symlink():
                dest.unlink()
            dest.symlink_to(link)
    print(f'SDK installed in {target}')
    print('Launch with ./run.sh; the SDK remains excluded from version control.')


if __name__ == '__main__':
    main()
