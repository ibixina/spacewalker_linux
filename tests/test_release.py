"""Release entry points and desktop integration, without touching user settings."""
import importlib.util
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_version_works_without_a_display():
    from spacewalker import __version__
    result = subprocess.run([sys.executable, '-m', 'spacewalker', '--version'],
                            capture_output=True, text=True)
    assert result.returncode == 0
    assert __version__ in result.stdout


@pytest.mark.parametrize('arguments', [
    ['--smoke-seconds', 'nan'], ['--smoke-seconds', '-1'],
    ['--screenshot', '/tmp/unused.png'], ['--profile-seconds', 'inf'],
    ['--profile-output', '/tmp/unused.json'], ['--resolution', 'bad'],
])
def test_invalid_cli_options_fail_before_starting_qt(arguments):
    result = subprocess.run([sys.executable, '-m', 'spacewalker', *arguments],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Traceback' not in result.stderr
    assert 'qt.qpa' not in result.stderr


def test_desktop_launcher_installs_in_a_path_with_spaces_and_metacharacters(tmp_path):
    import os
    project = tmp_path/'Space walker & tools $test `literal`'
    (project/'scripts').mkdir(parents=True)
    shutil.copytree(ROOT/'packaging', project/'packaging')
    for name in ('install-app.sh', 'render-desktop.py'):
        shutil.copy2(ROOT/'scripts'/name, project/'scripts'/name)
    runner = project/'run.sh'
    runner.write_text('#!/bin/sh\nexit 0\n')
    runner.chmod(0o755)
    data = tmp_path/'data'
    subprocess.run(['bash', str(project/'scripts/install-app.sh')],
                   env=dict(os.environ, XDG_DATA_HOME=str(data)), check=True, capture_output=True)
    desktop = (data/'applications/spacewalker-linux.desktop').read_text()
    execs = [line.removeprefix('Exec=') for line in desktop.splitlines() if line.startswith('Exec=')]
    # The desktop-entry layer removes one level of backslash escaping, then
    # Exec tokenization applies double-quote escaping (without a shell).
    commands = [[part.replace('\\$', '$').replace('\\`', '`')
                 for part in shlex.split(line.replace('\\\\', '\\'))] for line in execs]
    assert commands == [[str(runner)], [str(runner), '--mode', 'single'], [str(runner), '--mode', 'multiple']]
    assert 'TryExec='+str(runner) in desktop


def test_desktop_renderer_preserves_percent_and_backslash_paths():
    spec = importlib.util.spec_from_file_location('render_desktop', ROOT/'scripts/render-desktop.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.exec_value('/tmp/100%/run.sh') == '"/tmp/100%%/run.sh"'
    assert module.string_value('/tmp/a\\b') == '/tmp/a\\\\b'


@pytest.mark.parametrize('entry', ['../escaped.txt', '/tmp/spacewalker-unsafe-archive.txt'])
def test_sdk_import_rejects_archive_path_traversal(tmp_path, entry):
    import zipfile
    project = tmp_path/'project'
    (project/'scripts').mkdir(parents=True)
    script = project/'scripts/import-sdk.py'
    shutil.copy2(ROOT/'scripts/import-sdk.py', script)
    archive = tmp_path/'sdk.zip'
    with zipfile.ZipFile(archive,'w') as sdk:
        sdk.writestr(entry, b'unsafe')
    result = subprocess.run([sys.executable,str(script),str(archive)],text=True,capture_output=True)
    assert result.returncode != 0
    assert 'unsafe path' in result.stderr
    assert not (project/'vendor/escaped.txt').exists()


def test_sdk_discovery_selects_host_architecture(tmp_path, monkeypatch):
    from spacewalker import tracking
    root = tmp_path/'project'
    package = root/'spacewalker'
    package.mkdir(parents=True)
    monkeypatch.setattr(tracking,'__file__',str(package/'tracking.py'))
    monkeypatch.delenv('VITURE_SDK_LIBRARY', raising=False)
    for architecture, machine in [('x86_64',62), ('aarch64',183)]:
        directory = root/'vendor'/architecture
        directory.mkdir(parents=True)
        header = bytearray(20)
        header[:6] = b'\x7fELF\x02\x01'
        header[18:20] = machine.to_bytes(2,'little')
        (directory/'libglasses.so').write_bytes(header)
    for architecture in ('x86_64','aarch64'):
        monkeypatch.setattr(tracking.platform,'machine',lambda:architecture)
        assert tracking.library_path() == str(root/'vendor'/architecture/'libglasses.so')
