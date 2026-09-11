# Release procedure

The prepared version is **0.1.0rc1**, a Linux release candidate. The source repository is [ibixina/spacewalker_linux](https://github.com/ibixina/spacewalker_linux). Build artifacts remain local until a release upload is requested. Do not bundle the VITURE SDK.

## Build and validate

Use Python 3.11 or later. Install the system prerequisites in README.md, including Xvfb, xauth, FFmpeg, and Node.js 22+ for verification. Native capture also needs a C compiler, Wayland headers, and wayland-scanner.

```bash
./scripts/setup.sh
.venv/bin/python -m pip install '.[release]'
./scripts/check-release.sh
```

The release gate runs unit tests, browser camera tests, actual OpenGL/X11/video integration, focused lint checks, shell syntax validation, the source-to-wheel build, package metadata validation, required-asset checks, and SHA-256 generation. It does not upload anything or change your desktop. Use a dist directory containing only the current candidate's wheel and source archive. The script also accepts `SPACEWALKER_PYTHON` and `SPACEWALKER_BUILD_PYTHON` when runtime and build tools live in different environments.

The wheel includes Python code, shaders, browser assets, the C capture helper source, and its licensed Wayland protocol. The source archive additionally includes setup/launcher/SDK-import scripts, the desktop icon, udev rules, tests, and release documentation. Vendor SDK files, local profiling captures, and virtual environments are excluded.

## Clean installation

Test outside the checkout so source files cannot hide missing package contents:

```bash
python3 -m venv /tmp/spacewalker-install
/tmp/spacewalker-install/bin/python -m pip install dist/spacewalker_linux-0.1.0rc1-py3-none-any.whl
cd /tmp
/tmp/spacewalker-install/bin/spacewalker --version
/tmp/spacewalker-install/bin/spacewalker --doctor
/tmp/spacewalker-install/bin/spacewalker --demo --desktop-backend private --smoke-seconds 5
```

For the desktop menu launcher, extract the source archive to its permanent location and follow README.md. The wheel CLI uses `--sdk /path/to/libglasses.so` or `VITURE_SDK_LIBRARY` to locate the separately supplied SDK. Keep SDK dependency libraries alongside it according to VITURE's instructions.

## Native and physical acceptance

Close the viewer before running tests that create native outputs:

```bash
SPACEWALKER_NATIVE_TESTS=1 .venv/bin/python -m pytest tests/test_hyprland.py -q
./run.sh --probe-tracking 3
./run.sh --profile-seconds 10 --profile-output artifacts/release/native-timing.json
```

Native tests temporarily attach monitors, move a disposable test window, compare pixels, simulate viewer death, and verify that applications survive and output geometry/shortcuts are restored. Run them in an unlocked Hyprland session. Reopen the viewer afterward.

Before promoting to 0.1.0:

- Check optical comfort, motion scale, head axes, anchoring, and recentering through the glasses; run a 30-minute drift/thermal session.
- Verify real 2D → SBS → original display-mode restoration and audio/video playback through the intended glasses/cable/adapter.
- Exercise unplug/replug, session lock/unlock, fullscreen transitions, mirror exclusion, and restart after capture loss.
- Verify each additional advertised distribution, Python version, GPU, and architecture. Current automated evidence is Fedora 44, Python 3.14, x86_64; dependency declarations are not a compatibility matrix.
- Audit the resolved dependencies: `pip-audit --no-deps --disable-pip -r requirements-tested.txt`. This checks published Python-package advisories, not the proprietary SDK or all embedded native libraries.
- Review `docs/RELEASE_EVALUATION.md`, update the single version in `spacewalker/__init__.py`, rebuild, and repeat the gate.
- Commit the reviewed source to the user-selected repository, tag that commit, and publish only to an explicitly selected destination. Keep the checksum manifest with the archives.

## Supported scope and limitations

Native monitor integration targets Hyprland. Other compositors can use the explicit private X11 workspace; existing host windows cannot move into that workspace. Tracking supports the current VITURE Gen1/Gen2 SDK, including Pro 2, and is rotational 3DoF. Tracking reconnection is manual. DRM, fisheye, positional tracking, and automatic projection detection are outside this release. Performance reports measure software timing, not physical motion-to-photon latency.
