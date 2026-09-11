# Release evaluation — 0.1.0rc1

Evaluation date: 2026-09-10 (America/New_York). Target: Fedora 44 x86_64, Python 3.14.7, PySide6 6.11.2, Hyprland 0.56.2, VITURE Pro 2.

The app passes the local release-candidate gate. Physical comfort, sustained drift, and additional platform qualification remain required before a general availability release. The source repository is [ibixina/spacewalker_linux](https://github.com/ibixina/spacewalker_linux); built release archives remain local.

## Findings and changes

| Area | Finding | Result |
| --- | --- | --- |
| Visual design | Toolbar actions and settings had little hierarchy. | Charcoal surfaces, compact workspace/video navigation, quieter actions, clearer typography, accessible focus states, explicit dropdown indicators, and a matching browser player; fullscreen remains free of controls. |
| Pointer performance | Every pointer event rebuilt all panel transforms, even when geometry was unchanged. | Drawing and hit testing share cached geometry at original precision; placement, gravity reference, and geometry edits invalidate it. |
| UI responsiveness | A display switch could poll the SDK for four seconds on the UI thread; disconnect could also block. | SDK operations run in background jobs; pending switches, disconnects, and exit serialize. |
| Capture recovery | A failed producer stopped rendering and left Start disabled with the failed backend attached. | Deferred cleanup releases borrowed frame resources, exposes Restart workspace, and resumes rendering on recovery. |
| Video recovery | A conversion failure stopped the render watchdog; selecting another file did not restart it. | Opening a new source clears the render error and resumes updates. |
| Linux launcher | Exec paths were inserted through sed without quoting; paths with spaces or replacement characters broke. | Desktop-entry escaping, separate TryExec handling, and validation before installation. |
| SDK selection | Multiple SDK architectures made automatic discovery ambiguous; run.sh preferred x86_64 even on ARM. | Library discovery checks ELF class/machine; the launcher selects the host architecture. ARM execution still needs physical testing. |
| Browser boundary | Command names without the required prefix were accepted; error responses could leave unread bodies on persistent connections. | Exact action routes and connection closure for rejected requests. Existing loopback binding, random token, Host/Origin validation, and latest-pose streaming retained. |
| Distribution | Minimal metadata, duplicate version strings, and no documented asset/build gate. | Single version source, --version, metadata, source manifest, wheel/source checks, checksums, and a provider-neutral release script. |
| Installation documentation | The introduction assumed a machine with a preinstalled environment and SDK. | Portable quick start, explicit requirements, release procedure, and supported-scope statement. |

## Performance evidence

The controlled five-monitor pointer benchmark decreased median time per event from **621.884 µs to 37.002 µs**, approximately **16.81× faster**. Each result is the median of five runs of 1,000 events against unchanged monitor geometry. Both implementations ran in the same process/environment. Exact cached/cold pointer results and rendered-coordinate agreement are covered by tests. See [raw results](pointer-benchmark.json).

This measures pointer projection only. It does not establish an improvement in total frame rate or physical motion-to-photon latency. Existing latest-frame capture, per-monitor partial uploads, late pose sampling, and off-thread video conversion remain in place.

## Verification

| Check | Result |
| --- | --- |
| Unit suite | 86 passed; 27 opt-in graphics/native cases skipped in this invocation and exercised separately. |
| OpenGL/X11/video integration | 24 passed, using a temporary X server and software OpenGL. Includes playback/audio-stream presence/seek/pause, input mapping, fullscreen, geometry, new SDK responsiveness/serialization, and deliberate capture-failure recovery. |
| Native Hyprland integration | 13 passed (10 unit checks plus 3 real monitor scenarios): multiple, single, and mirror. Window survival, captured colors, pointer capture, original display geometry, and shortcut cleanup verified. |
| Browser camera unit tests | 3 passed, with Node.js 22.22.2. |
| Browser visual/interaction check | Local generated MP4 decoded at 640×320 in the in-app browser. Play/pause, view presets, independent FOV, tracking pause, 180° projection, and SBS source selection exercised; no browser warnings/errors during inspection. External YouTube service playback was not requalified in this pass. |
| Native tracking | Live Pro 2 probe received 605 samples in 3 seconds; final reported sample age 0.63 ms. |
| Native idle performance | Two 1920×1080 outputs, tracking connected: 59.89 Qt swaps/s; CPU render p95 1.095 ms; SDK callback-to-draw age p95 5.416 ms; no GL/render errors. No changed content after warmup, so capture/upload rates were unavailable. This is an idle preview, not an animated-content benchmark or physical latency measurement. |
| Dependency advisory audit | No known vulnerabilities in the 14 exact runtime/test Python package versions in requirements-tested.txt at the time of the audit. |
| Static checks | Focused Ruff runtime-error rules, shell syntax, and strict package metadata checks passed. |
| Source and wheel | Built the wheel from the source archive, verified shaders/browser/icons/C/protocol assets, confirmed SDK and local-artifact exclusion, generated SHA256SUMS. |
| Clean installation | Installed dependencies and the wheel into a new virtual environment; pip check, --version, --doctor, and an actual private-workspace/OpenGL smoke run from /tmp passed. SDK absence is reported as expected until configured separately. |
| UI visual QA | Inspected workspace, Displays settings, View settings, and the browser player. No clipping in the 1380×850 native preview; controls stay hidden in glasses view. |
| User session | Relaunched the normal viewer with two saved Full HD monitors; original physical display coordinates and modes confirmed. |

Detailed local logs, screenshots, audit output, and profiling data are in `artifacts/release/` (excluded from distribution). The portable pointer benchmark is retained alongside this report. The first native-test attempt was refused while the pre-existing viewer still owned the outputs; the final native suite passed after confirmed graceful shutdown.

## Remaining acceptance work

- Optical comfort, long-session drift/thermals, and physical motion-to-photon measurement require hands-on use through the glasses.
- Additional Linux distributions, supported Python versions other than 3.14, ARM64 execution, and other GPUs need qualification.
- The proprietary SDK and Qt/FFmpeg's bundled native components are outside the Python advisory scan's complete coverage.
- Native GNOME/KDE monitors, positional tracking, automatic device reconnection, DRM, and fisheye projection remain unsupported as documented.
- A release tag and an explicitly requested release upload are still required to publish the built archives; pushing source does not publish a binary release.

Packaging follows the [setuptools package configuration](https://setuptools.pypa.io/en/stable/userguide/pyproject_config.html) and [source inclusion documentation](https://setuptools.pypa.io/en/latest/userguide/miscellaneous.html). Launcher escaping follows the [freedesktop desktop-entry specification](https://specifications.freedesktop.org/desktop-entry/latest-single/).
