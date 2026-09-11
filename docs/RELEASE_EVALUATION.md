# Release evaluation — 0.1.0rc2

Evaluation date: 2026-09-10 (America/New_York). Target: Fedora 44 x86_64, Python 3.14.7, PySide6 6.11.2, Hyprland 0.56.2, VITURE Pro 2.

The rc1 automated gate missed a live failure: screens remained tilted after recentering and tracking stopped without recovery. Those results did not establish working motion through the glasses. The rc2 corrections and their verification are described below. Physical motion acceptance, comfort, sustained drift, and additional platform qualification remain required before a general availability release. The source repository is [ibixina/spacewalker_linux](https://github.com/ibixina/spacewalker_linux); built release archives remain local.

## Corrective verification after the reported failure

The running session had zero manual tilt/roll on both saved screens, but its hidden up vector was approximately `(0.350, 0.794, 0.498)` and the latest pose was minutes old. Recenter reset the camera while preserving pitch/roll in monitor geometry. Calibration now defines one complete frame with a level horizon; saved placements and manual angles remain intact. Tests now exercise the calibrated frame explicitly, including rendered stripes and pointer agreement.

A stopped stream now levels the preview and triggers serialized cleanup/reconnect with 1–30 second backoff. A native Pro 2 test deliberately closed the IMU stream: a new connection had received 104 samples after **3.77 seconds**, with **0.99 ms** sample age and the old SDK handle destroyed. After another three seconds it had 707 samples and 3.76 ms sample age. This tests an interrupted stream, not physical unplug/replug or long-term drift. The test ran in an isolated X server with the real USB device.

The rc1 icon URL used a `file:` URI that Qt stylesheets interpreted as a relative filename. Quoted filesystem paths now load correctly, including paths containing spaces. This is covered by a real Qt resource-loading check.

## Findings and changes

| Area | Finding | Result |
| --- | --- | --- |
| Visual design | Toolbar actions and settings had little hierarchy. | Charcoal surfaces, compact workspace/video navigation, quieter actions, clearer typography, accessible focus states, explicit dropdown indicators, and a matching browser player; fullscreen remains free of controls. |
| Pointer performance | Every pointer event rebuilt all panel transforms, even when geometry was unchanged. | Drawing and hit testing share cached geometry at original precision; placement, reference-frame, and geometry edits invalidate it. |
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
| Unit suite | 87 passed; 33 opt-in graphics/native cases skipped in this invocation and exercised separately. |
| OpenGL/X11/video integration | 30 passed, using a temporary X server and software OpenGL. Includes playback/audio-stream presence/seek/pause, input mapping, fullscreen, geometry, SDK responsiveness/serialization, deliberate capture-failure recovery, stale tracking recovery, stereo restoration, retry cancellation/backoff, and icon loading. |
| Native Hyprland integration | 13 passed (10 unit checks plus 3 real monitor scenarios): multiple, single, and mirror. Window survival, captured colors, pointer capture, original display geometry, and shortcut cleanup verified. |
| Browser camera unit tests | 3 passed, with Node.js 22.22.2. |
| Browser visual/interaction check | Retained rc1 check: local generated MP4 decoded at 640×320 in the in-app browser. Play/pause, view presets, independent FOV, tracking pause, 180° projection, and SBS source selection exercised; no browser warnings/errors during inspection. External YouTube service playback was not requalified in this pass. |
| Native tracking | Live Pro 2 interrupted-stream recovery passed; 104 samples on the replacement connection within 3.77 seconds, then 707 samples after another three seconds. |
| Native idle performance | Retained rc1 measurement, two 1920×1080 outputs, tracking connected: 59.89 Qt swaps/s; CPU render p95 1.095 ms; SDK callback-to-draw age p95 5.416 ms; no GL/render errors. No changed content after warmup, so capture/upload rates were unavailable. This is an idle preview, not an animated-content benchmark or physical latency measurement. |
| Dependency advisory audit | No known vulnerabilities in the 14 exact runtime/test Python package versions in requirements-tested.txt at the time of the audit. |
| Static checks | Focused Ruff runtime-error rules, shell syntax, and strict package metadata checks passed. |
| Source and wheel | Built the wheel from the source archive, verified shaders/browser/icons/C/protocol assets, confirmed SDK and local-artifact exclusion, generated SHA256SUMS. |
| Clean installation | Installed rc2 into the isolated wheel-test environment; pip check, --version, --doctor, and an actual private-workspace/OpenGL smoke run from /tmp passed. SDK absence is reported as expected until configured separately. |
| UI visual QA | Rechecked arrangement at 1380×850 in an isolated display: icons load, the settings scroll, and Cancel/Done remain visible. Prior workspace/View/browser inspections are retained; fullscreen controls are covered by integration tests. |
| User session | Relaunched using current saved settings; fresh tracking and a level calibration frame confirmed with no GL/render errors. Hands-on motion acceptance remains pending. |

Detailed local logs, screenshots, audit output, and profiling data are in `artifacts/release/` and `artifacts/recovery/` (excluded from distribution). The portable pointer benchmark is retained alongside this report. The first native-test attempt was refused while the pre-existing viewer still owned the outputs; the final native suite passed after confirmed graceful shutdown.

## Remaining acceptance work

- Optical comfort, long-session drift/thermals, and physical motion-to-photon measurement require hands-on use through the glasses.
- Additional Linux distributions, supported Python versions other than 3.14, ARM64 execution, and other GPUs need qualification.
- The proprietary SDK and Qt/FFmpeg's bundled native components are outside the Python advisory scan's complete coverage.
- Native GNOME/KDE monitors, positional tracking, DRM, and fisheye projection remain unsupported as documented. Automatic stream recovery is tested; physical unplug/replug remains an acceptance item.
- A release tag and an explicitly requested release upload are still required to publish the built archives; pushing source does not publish a binary release.

Packaging follows the [setuptools package configuration](https://setuptools.pypa.io/en/stable/userguide/pyproject_config.html) and [source inclusion documentation](https://setuptools.pypa.io/en/latest/userguide/miscellaneous.html). Launcher escaping follows the [freedesktop desktop-entry specification](https://specifications.freedesktop.org/desktop-entry/latest-single/).
