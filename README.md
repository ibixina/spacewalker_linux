# Spacewalker Linux

An independent native Linux spatial desktop and VR video viewer for VITURE glasses. **0.1.0rc1 is a release candidate**, not VITURE's proprietary SpaceWalker app or a product affiliated with VITURE. See [release evaluation](docs/RELEASE_EVALUATION.md), [changes](CHANGELOG.md), and [release verification](RELEASE.md).

## Quick start

Requires Linux, Python 3.11+, and OpenGL 3.3. Native monitors require Hyprland; tracking requires a separately downloaded VITURE SDK. First follow [installation](#install-on-another-linux-machine), then run from the extracted source directory:

```bash
./run.sh
```

To add **Spacewalker Linux** to your desktop application menu, run:

```bash
./scripts/install-app.sh
```

The launcher includes right-click actions for a single anchored screen and multiple spatial screens. It starts this project through `run.sh`, so it uses the same SDK and environment as the command-line launch.

On a Hyprland desktop, the app initially attaches three real **1920×1080** virtual monitors to your existing session and connects to the glasses when their SDK is available. Later launches restore the saved monitor count. Choose **Open → Existing window…**, then select a window and its monitor. Alternatively, focus any application and press **Ctrl+Alt+1**, **2**, or **3** to move it to that monitor.

In **Settings → View**, leave **Anchor screens in space** enabled. Select the glasses under **Output display**, then click **Glasses view**. Look straight ahead and press **Ctrl+Alt+R** to place the screens in front of you. Turn your head to look at the other monitors. **Ctrl+Alt+0** returns to the viewer controls even while a different application has focus; **Esc** also works when the viewer has focus.

The normal window has a compact toolbar; **Settings** opens a drawer. Glasses view hides every control. There is no virtual room, grid, glow, or colored frame. Pixels between monitors are pure black, so the display adds no image there and you can see the real world through the lenses. This is optical see-through, not camera passthrough or desktop-window alpha transparency. Lens tint, ambient light, and the glasses' optics still affect visibility. Use **Arrange** to leave as much space between displays as you like.

Use your desktop's display settings to extend onto the glasses. Mirroring the laptop display limits placement and stereo output. The glasses must be connected through a cable/adapter that carries both video and USB data.

**Pro 2 supports rotation tracking (3DoF).** The screens stay anchored as you rotate your head, including pitch and roll. Translating your head through the room is not tracked. There is no camera-based room mapping or persistent physical room anchor. Recenter corrects the facing direction and accumulated drift.

## One anchored screen

Choose **Settings → Displays → Number of monitors → 1**. The same selector offers **1 through 5**, with no separate single-screen mode. One monitor defaults to **Separate monitor**, giving the glasses a dedicated desktop. Move an existing app onto it with **Ctrl+Alt+1** or **Open → Existing window…**. You can optionally select **Mirror eDP-1** under **Source** to show your laptop desktop at its native resolution with its applications left in place.

Select the VITURE display under **Output display**, enter **Glasses view**, look where you want your forward reference, and press **Ctrl+Alt+R**. With **Anchor screens in space** enabled, the screen stays there as you turn your head. Use **Arrange** to change its position, distance, or size. Turn anchoring off in **Settings → View** for a screen that follows your head.

Each monitor count has its own saved arrangement. Select **2**, **3**, **4**, or **5** to add more monitors; returning to a previous count restores its positions. Switching counts keeps applications open; Hyprland relocates workspaces when separate monitors are detached. Normal launches remember the selected count and source.

The mirrored source and glasses output must be different extended displays. The preview is black while the viewer itself is on the captured source, to prevent a recursive image; **Glasses view** moves it onto the glasses. Mirroring currently supports unrotated Hyprland outputs up to 3840×2160. It does not require creating a virtual monitor.

```bash
# One separate monitor for the glasses
./run.sh --screens 1

# One anchored copy of your laptop desktop instead
./run.sh --screens 1 --source eDP-1

# Return to the multi-monitor workspace
./run.sh --screens 3
```

## Place your monitors

Click **Arrange** in the toolbar. Each display has its own position and orientation, independent of the others.

- **Drag a display in the view** to move it left, right, up, or down. Hold it and turn your head to carry it around you. Scroll to bring the selected display closer or farther away; **Shift+scroll** changes its size.
- **Drag a numbered display on the overhead map** to place it around, beside, or behind you. Select its number to reach displays outside your current view.
- Adjust **Left / right**, **Up / down**, **Distance**, and **Size** for precise placement. Expand **Screen angle** to turn, tilt, or rotate the monitor. At zero tilt and rotation, every monitor stands vertical, with its sides parallel to gravity. It turns left/right toward your seated position but does not automatically lean when raised or lowered, including after recentering while looking up or down. Use **Tilt** explicitly to lean a screen toward you. Your manual screen angles are applied on top of that upright orientation.
- Each position, size, and angle control has a slider that updates the display continuously while you drag. The numeric value stays in sync and supports precise entry. **Done** saves the changes; **Cancel** restores the previous arrangement.
- **Place where I’m looking** brings the selected display into your current gaze without changing its distance or size.
- **Choose a layout…** starts an arc around you, a straight row, or a vertical stack. **Move active app to this display** puts the focused application on the selected monitor.

Click **Done** to keep and save the arrangement, or **Cancel** to restore it. In the viewer, **Enter** finishes and **Esc** cancels. Thin selection outlines appear only while arranging; after Done the view contains just the monitor surfaces and black gaps. Normal app clicks and typing resume when arranging ends.

**Ctrl+Alt+A** opens arrangement controls from any application in native monitor mode. Positions are saved separately for each screen count and resolution. They are restored relative to your recentered forward direction on the next normal launch. Distance controls virtual geometry; it does not add positional tracking to the glasses. Spatial placement changes the view through the glasses; the operating system’s monitor layout remains a horizontal row for ordinary pointer movement.

## Use applications on the screens

The default backend creates **Spacewalker-1**, **Spacewalker-2**, and **Spacewalker-3** as actual Hyprland outputs. Existing Wayland and XWayland windows, your clipboard, application state, tiling rules, and ordinary keyboard/mouse input remain in the same desktop session. Each output is captured directly through Wayland and shown on its corresponding spatial surface. The physical glasses output is excluded from the source monitors and remains the destination for the XR renderer.

Each XR output starts with a fresh named workspace. This avoids inheriting a numbered workspace's stale fade/render state after it moves from a physical output. Temporary workspace rules are disabled when the session ends; applications on those workspaces remain open.

- **Open → Existing window…** moves any chosen desktop window to a chosen monitor. You can also find this in **Settings → Displays**.
- **Ctrl+Alt+1…5** moves the currently focused application to that numbered monitor, up to the configured count. These shortcuts work while the application has focus.
- Click a monitor in the preview to transfer your real pointer there; subsequent clicks and typing go through Hyprland normally. You can also move the pointer across desktop display edges as usual. The virtual outputs start immediately to the right of your existing displays.
- **Open → Terminal / Application…** launches in your ordinary desktop session, requesting the middle XR monitor. Programs that reuse an existing window may ignore launch placement; use the existing-window picker to move that window.
- **Ctrl+Alt+R** recenters from any application. **Ctrl+Alt+F** toggles glasses view. **Ctrl+Alt+0** focuses the viewer controls.
- Closing the viewer removes its outputs and temporary shortcuts. Hyprland relocates the workspaces to remaining displays; applications keep running. A separate guardian also removes the outputs if the viewer process dies.

The integration supports both Lua and legacy Hyprland configuration; it is verified on **Hyprland 0.56.2**. It does not edit your configuration files or physical display modes. Temporary shortcuts are installed only when those chords are unused. If you already bind one, use the equivalent toolbar action. A Hyprland configuration reload can clear the temporary bindings; restart the viewer to reinstall them. Lua monitor mode rules for the named outputs remain in memory until a configuration reload, after the outputs themselves are removed. Only one native monitor session can run at a time.

Startup replaces those saved runtime rules before creating any output, uses automatic right-side placement, and verifies the resolution, refresh rate, scale, and non-overlapping layout. If Hyprland reattaches an output with an old active workspace, Spacewalker explicitly activates its new workspace and restores keyboard focus and pointer position before capture starts. Existing display geometry must remain unchanged. A rejected setup removes the newly created outputs instead of starting capture with an invalid layout. This prevents an old fixed-position rule from briefly overlapping another display during startup.

Native GNOME/KDE monitor backends are not implemented. The earlier separate X11 workspace remains available explicitly with **`--desktop-backend private`** on Wayland or X11. It runs applications in its own authenticated Xvfb server; existing host windows cannot move into it, and closing that private workspace ends its applications. The default reports an unsupported compositor rather than silently presenting this separate desktop as native monitors.

```bash
# Three 1080p screens (the default)
./run.sh --screens 3 --resolution 1920x1080

# Five 720p screens (lower bandwidth, softer text in the glasses)
./run.sh --screens 5 --resolution 1280x720

# Try it without opening the tracking device; right-drag to look around
./run.sh --demo
```

## VR and stereo video

Choose **Open → Video…** in the toolbar. The **Video** button opens the playback controls. Choose its actual projection and eye layout:

| Content | Projection | Video eye layout |
| --- | --- | --- |
| Ordinary movie | Flat screen | Mono |
| Stereo movie | Flat screen | Side by side or top/bottom |
| Panoramic video | 360° equirectangular | Mono, SBS, or top/bottom |
| VR180 | VR180 equirectangular | Usually SBS; select what the file contains |

Turn your head to look around panoramic video. The back hemisphere of VR180 is black. Dual-fisheye, cubemap, proprietary spatial formats, DRM streams, and automatic projection-metadata detection are not supported. Convert those files to equirectangular first. Decoder/codec support comes from Qt Multimedia's FFmpeg backend. The player supports audio, volume, pause, and seeking.

For **stereoscopic** playback:

1. Connect tracking, then choose **Settings → View → Switch glasses to 3D**, or use the glasses' physical 3D switch.
2. Select the glasses' **3840 × 1080** output in your Linux display settings, with mirroring disabled. Desktop scaling affects the reported logical dimensions; the rendered output must fill the physical display.
3. Enable **Render SBS output (two eyes)** and enter glasses view on that display. The video eye layout describes the source file; this output setting controls the images sent to the glasses. They are separate settings.
4. Use **Swap left and right eyes** if the file's eye order is reversed.

The SDK display switch checks the reported mode before claiming success. If firmware acknowledges a switch without reporting the new mode, the app reports the failure and offers the physical-switch fallback. A mode changed through the app is restored on normal disconnect/exit; if the process is forcibly killed, restore it manually on the glasses.

```bash
./run.sh --video /path/to/panorama.mp4 --projection 360 --packing mono
./run.sh --video /path/to/vr180.mp4 --projection 180 --packing sbs
```

## Browser 360° video in Helium

Choose **Open → Browser 360…** in Spacewalker. It opens a dedicated player window in your default Chromium-family browser, including the Helium AppImage installed on this machine. Paste a YouTube 360° link, click **Open**, and press the video's **Play** button.

Choose the VITURE output under Spacewalker's **Settings → View → Output display**. In the browser player, click **Move to glasses**, then its **Fullscreen** button and **Recenter** while looking forward. Keep Spacewalker running: it supplies the glasses' head orientation. The browser renders directly on the physical glasses display; avoid placing this player on an anchored virtual monitor, which would apply head movement twice. Use normal **2D glasses mode** for YouTube.

The controls appear when you move the pointer over their area. **Head tracking** pauses or resumes view control. Browser video starts in **View → Wide** at **90°**, the slider's maximum, to avoid an overly zoomed-in panorama. **View → Glasses scale** optionally uses Spacewalker's narrower optical calibration. The **Field of view** slider fine-tunes the video immediately, including while tracking is paused or disconnected. Tracking updates and recentering preserve your chosen video view. These video-view choices do not alter the desktop/glasses calibration. **Recenter** sets the current direction as forward, and **App controls** returns to Spacewalker. Press **Esc** to leave browser fullscreen. If Helium retains its window title bar, also use your compositor's fullscreen command so the video fills the physical output. On Hyprland, Move to glasses moves only the player window; elsewhere use your desktop's window controls.

This supports public YouTube 360° videos that allow embedded playback. It uses [YouTube's official spherical-video API](https://developers.google.com/youtube/iframe_api_reference#Spherical_Video_Controls), including the conversion from vertical optical field of view to YouTube's longer-edge field of view. It does not control an already-open youtube.com tab or add head tracking to arbitrary websites. Ordinary videos and ads have no panoramic camera. If Helium blocks the embed, allow YouTube for the local player page. For clarity, choose the highest practical quality in YouTube's playback settings: the full 360° image supplies only a small part of its pixels to each view.

Even the highest-quality stream can look soft with a narrow view: a 26° vertical view greatly enlarges part of the sphere. For example, a 3840×1920 equirectangular panorama contributes roughly 470×280 source pixels to a centered 45°×26° view; other projections distribute pixels differently. The default **Wide** view reduces this magnification but cannot restore missing source detail. For videos offering 8K, select **Playback Settings → Quality → 4320p** inside the embedded YouTube player; Auto may choose a lower resolution. The footer shows YouTube's reported quality level when available, or actual decoded dimensions for direct videos. YouTube may report 8K simply as “High resolution,” so that label does not confirm exact dimensions. YouTube's public API does not support forcing a higher quality level; change it through the embedded player's own settings.

You can also paste a direct **MP4/WebM equirectangular video URL**. Its server must allow cross-origin video playback. Select **360°** or **180°** and the source's **Video eyes** layout; playback, seeking, volume, and projection controls remain available in fullscreen. For stereo sources, configure the glasses' 3840×1080 mode and **Render SBS output** in Spacewalker first. A normal website page URL, DRM stream, or a server that denies cross-origin access cannot be used as a direct video source; use the local file player for files you have downloaded legitimately.

```bash
./run.sh --web-video 'https://www.youtube.com/watch?v=FAtdv94yzp4'
```

This starts the browser and tracking without creating virtual monitors. The connection stays on `127.0.0.1`, uses a random per-session token, and sends only the latest pose. There is no screen capture or video re-encoding in the browser path. Browser decoding, YouTube's player, and display refresh still add latency; zero latency is not possible.

## Anchoring and calibration

Desktop clarity now defaults to Full HD per monitor. The earlier 1280×720 default enlarged a lower-resolution desktop onto the glasses’ 1920×1080 output, softening text. **Settings → View → Sharper text** is enabled by default and uses Catmull-Rom reconstruction for desktop text near native scale or when enlarged; video sampling is unchanged. This improves pixel reconstruction without changing head-tracking gain or adding temporal smoothing. Screens made very small or tilted far away still have fewer physical display pixels available for their contents. Existing 720p screen placements are retained when first switching to the Full HD default.

**Anchor screens in space** is on by default. Turning it off makes the view follow your head. **Recenter here** sets the current orientation as forward. For Gen1/Gen2 glasses, including Pro 2, the app follows the supplied VITURE demo's roll/pitch/yaw convention: positive yaw looks left, pitch looks down, and roll tilts right. It builds a quaternion from those angles and uses quaternion composition for recentering and rendering.

The Pro 2 packets measured on this machine do not give the same NWU rotation in their quaternion fields as in their Euler fields. Applying the documented NWU basis change directly to those quaternion fields produced the wrong movement axes. The app now follows the actual Gen1/Gen2 implementation in the SDK's `glasses-demo/main.cpp`, rather than that assumption. Regression tests include a recorded packet, the reference demo's camera basis, single-axis and combined movement, yaw wraparound, and rendered left/center/right monitor selection.

Use **Glasses view** on the VITURE output for calibrated movement through the lenses. The ordinary desktop preview intentionally shows a wider field and is not an optically matched view.

**Settings → View → Glasses field of view** now exposes the separate optical calibration. It starts at **26° vertically**, an adjustable starting point rather than a measurement of your unit. Adjust it if movement has the correct axes but the wrong scale. **Preview field of view** changes only the desktop preview; it cannot overwrite the glasses calibration. Both values are saved independently. Recenter changes the forward direction, not this scale. VITURE lists a 50° FOV for Pro 2; treating that as diagonal at 16:9 gives a roughly 26° vertical starting point. [VITURE Pro 2 specifications](https://www.viture.com/product/viture-pro-2-xr-glasses).

**Screen angular width** changes how much space each monitor occupies. Smoothing defaults to zero; increasing it reduces small movements but adds latency. Calibration values and the SDK path are saved under `~/.config/SpacewalkerLinux/Spacewalker.conf` for normal runs. Demo, smoke-test, and timed profiling runs do not save preferences.

| Shortcut | Action |
| --- | --- |
| Ctrl+Alt+R | Recenter |
| Ctrl+Alt+A | Arrange displays / finish arranging |
| Ctrl+Alt+F | Enter/leave glasses view |
| Ctrl+Alt+0, native monitors | Focus viewer controls |
| Ctrl+Alt+1…5, native monitors | Move the focused desktop window to that monitor |
| Esc, with viewer focused | Return to controls and release input |
| Ctrl+Alt+Tab | Cycle application windows |
| Ctrl+Alt+Left / Right | Move active app between screens |
| Space, in video view | Play/pause |
| Right-drag, with Mouse preview enabled | Simulate head rotation |

## Install on another Linux machine

Requires Python 3.11+, OpenGL 3.3, and a working Qt platform backend. Native monitors additionally need an active Hyprland session, `hyprctl`, a C compiler, and Wayland development headers/scanner. The small capture helper builds automatically on first use. On this machine its Fedora development files were unpacked locally in `artifacts/wayland-dev`; no system package installation was needed. Xvfb and xauth are only needed for the optional private workspace and X11 integration tests. The current official VITURE Linux SDK supports x86_64 and aarch64. This project has been exercised on Fedora 44 x86_64; other distributions and architectures still need testing.

```bash
# Fedora
sudo dnf install python3 python3-pip gcc wayland-devel xorg-x11-server-Xvfb xorg-x11-xauth xrandr xterm libxcb-cursor

# Debian / Ubuntu
sudo apt install python3-venv build-essential libwayland-dev libwayland-bin xvfb xauth x11-xserver-utils xterm libxcb-cursor0 libegl1 libgl1

./scripts/setup.sh
```

Get the **current Linux Glasses SDK** from [VITURE's developer portal](https://www.viture.com/developer), then import your downloaded archive:

```bash
python3 scripts/import-sdk.py /path/to/VITURE_XR_Glasses_SDK_for_Linux_x86_64.zip
./run.sh --doctor
./run.sh --probe-tracking 3
./run.sh
```

The SDK is extracted under `vendor/viture`, excluded from Git, and remains subject to VITURE's license. It is not bundled with this application's source. You can alternatively select `libglasses.so` in the UI, use `--sdk /path/to/libglasses.so`, or set `VITURE_SDK_LIBRARY`. The old `libviture` 1.0.7 SDK is not compatible with this binding. The supplied SDK's C headers are the ABI authority.

If diagnostics show that your user cannot access the VITURE HID interface, install the supplied rule and reconnect the glasses:

```bash
sudo install -m 0644 packaging/70-viture.rules /etc/udev/rules.d/70-viture.rules
sudo udevadm control --reload-rules
# Physically reconnect the glasses after reloading.
```

The rule grants access to the active local user, not every user. Run the app as your normal user. Close other XR drivers that hold the device. A failed or stale tracking signal is shown in the UI; disconnect and reconnect tracking to retry. This release does not reconnect automatically after unplugging.

## Verification and architecture

```bash
.venv/bin/python -m pytest -q
SPACEWALKER_GUI_TESTS=1 QT_QPA_PLATFORM=xcb LIBGL_ALWAYS_SOFTWARE=1 \
  xvfb-run -a -s '-screen 0 1440x900x24' .venv/bin/python -m pytest tests/test_gui.py -q
```

The unit tests cover coordinate conversion, world anchoring/recenter, independently positioned and tilted monitors, nearest-surface input mapping, layout serialization and presets, stereo texture coordinates, SDK frequency selection, lifecycle cleanup, and display-mode restoration. Opt-in integration tests exercise real X11 capture and injected mouse/keyboard events, moving an app to a chosen display, agreement between rendered pixels and pointer coordinates for custom monitor poses in mono and stereo, arrangement dragging/cancel/save, rendered left/right eye colors and VR180 masking, pure-black gaps, hidden controls in glasses view, and actual video decoding, audio-stream presence, seeking, and pausing.

The native integration test attaches temporary outputs to the real desktop, moves an ordinary Wayland test window between monitors, verifies its captured pixels and channel order, and simulates viewer death by closing the guardian pipe. It checks that the application survives, the original displays retain their positions/modes, and the original shortcuts are restored. Run it separately from Xvfb tests:

```bash
SPACEWALKER_NATIVE_TESTS=1 .venv/bin/python -m pytest tests/test_hyprland.py -q
```

Development checks also cover live Pro 2 orientation callbacks, a verified hardware stereo-mode switch and restoration, and approximately 60 render fps. The suite verifies that a slow reader cannot block capture or receive torn pixels, stale frames are skipped, source changes discard in-flight video conversion, native RGBA/BGRA uploads preserve stereo colors, and the newest head pose affects rendering even when desktop capture stops. Optical calibration and long-session drift still need hands-on use.

The renderer is PySide6/OpenGL 3.3, with full-screen ray/plane and equirectangular shaders. The native backend uses a persistent C Wayland screencopy client, includes the compositor cursor, and publishes a BGRA monitor atlas into three shared mmap slots. There is no video encoding or process launch per frame. Native application input stays with Hyprland. The optional private backend instead captures Xvfb and handles XTest input. Both render only the newest completed frame. Nonblocking metadata and slot locks prevent read/write collisions, and pixels upload directly from mmap without an intermediate Python byte copy.

Native capture requests updates on damage, compares completed pixels to suppress duplicate frames, and tracks each monitor's content generation. Each monitor has separate front/back capture buffers, so an idle or slow monitor cannot hold up another screen's update. Changed screens are copied directly into a free shared slot and uploaded only to their part of the texture. Texture channel swizzles avoid converting BGRA bytes on the CPU during GPU upload. Resolution and the sharp-text filter are unchanged.

Hyprland references: [virtual outputs](https://wiki.hypr.land/0.54.0/Configuring/Using-hyprctl/), [current monitor configuration](https://wiki.hypr.land/configuring/core/monitors/), and the [capture protocol shipped with the tested version](https://github.com/hyprwm/Hyprland/blob/v0.56.2/protocols/wlr-screencopy-unstable-v1.xml). The protocol’s upstream license is retained with its XML definition.

The SDK callback retains only the latest pose. Rendering reads it immediately before drawing, after texture uploads and static scene setup. Monitor geometry and unchanged shader parameters are cached. Rendering schedules the next update from Qt's presentation callback, with a watchdog for window/context transitions; it does not wait for a new desktop or video frame. The output's compositor and refresh rate still control presentation. See [Qt's QOpenGLWidget presentation documentation](https://doc.qt.io/qt-6/qopenglwidget.html#frameSwapped).

Video uses Qt Multimedia with a separate conversion worker. A lightweight GUI callback passes a frame reference to a mailbox; newer frames replace pending conversion work. The renderer takes the newest converted image. This avoids converting every 4K frame on the head-tracking/UI thread. CPU-to-GPU texture uploads remain; zero-copy PipeWire/DMABUF and GPU video interop are future performance work.

## Latency and measuring performance

Zero physical latency cannot be guaranteed. SDK processing, USB delivery, GPU work, compositor scheduling, display scanout, and the optics are outside these software timing measurements. A stable frame rate alone does not establish motion-to-photon latency. At 60 Hz, a display refresh period is about 16.7 ms; higher refresh modes reduce that period when supported by the glasses and host. The app does not automatically change your desktop refresh rate.

Keep **Tracking smoothing** at **0 ms** for the fastest response. Desktop capture now defaults to **60 fps**, with **1–120 fps** selectable through `--capture-fps`. Capture deadlines account for capture time instead of adding an extra sleep after each frame. Missed deadlines are skipped without accumulating a backlog. Large resolutions, software-rendered applications, slow codecs, and CPU/GPU contention can still cause drops. Head rotation continues to reproject the last available image independently of its content update rate.

To collect a bounded report (this closes that viewer instance; native desktop applications remain open):

```bash
./run.sh --profile-seconds 10 --profile-output artifacts/timing.json

# Profile without accessing the glasses, or measure a particular video
./run.sh --demo --profile-seconds 10
./run.sh --video /path/to/vr180.mp4 --projection 180 --packing sbs \
  --profile-seconds 10 --profile-output artifacts/video-timing.json
```

The report excludes the first two seconds of startup. It includes median, 95th percentile, and maximum CPU render/upload duration, Qt swap intervals, content update rate, and the age of the **specific SDK sample used** for drawing. Sample age starts at the application's SDK callback, so it excludes sensor/firmware and USB latency. Native desktop age starts at the compositor timestamp of the oldest changed monitor in the published snapshot and ends at CPU draw submission; the private backend uses capture start time. An unchanged desktop produces no new frames, so its content update rate can fall and its image age can grow without indicating lag. Qt swap callbacks are not a measurement of when pixels reach your eyes. Validate perceived stability through the lenses; a high-speed camera or external latency rig is needed for a physical motion-to-photon measurement.

The real Hyprland monitor backend measured **59.9 capture fps and 59.9 render swaps/sec** for three 1280×720 outputs, with a 17.04 ms 95th-percentile swap interval and 5.76 ms 95th-percentile CPU render time. This was an eight-second preview run without tracking; report: `artifacts/native-monitor-timing.json`.

A second run with live VITURE tracking measured **59.99 capture fps and 59.76 render swaps/sec**, a 4.74 ms 95th-percentile CPU render time, and a 5.14 ms 95th-percentile SDK callback-to-draw sample age. Report: `artifacts/native-monitor-tracking-timing.json`. These software measurements do not measure physical motion-to-photon latency.

The initial three **1920×1080** implementation improved clarity but introduced a desktop-latency regression: tracked fullscreen capture ran at **33.54 fps** (`artifacts/fullhd-timing.json`). After removing redundant copies and uploading only changed screens, a controlled Full HD scrolling test on this machine improved from **29.82 to 57.36 content updates/sec** and from **54.68 to 59.89 render swaps/sec**. Median GPU-upload call duration fell from **12.39 to 1.50 ms**. A timestamp painted by the test application measured median content age after upload falling from **54 to 32 ms** (95th percentile **72.6 to 38 ms**). These are short runs without tracking, with one scrolling monitor and two mostly static monitors, on the Radeon Renoir GPU. Reports: `artifacts/native-latency-baseline-scrolling.json` and `artifacts/native-latency-final.json`. The timestamp measurement excludes display scanout and is not physical input-to-photon latency. Workloads animating every monitor may remain slower; Full HD content is not guaranteed to sustain 60 fps.

Earlier measurements below used the private X11 desktop backend, rendered in native Wayland previews on a 60 Hz output, excluding startup:

| Measurement | Before this latency pass | After |
| --- | --- | --- |
| Three 1280×720 desktops: actual capture rate | 25.2 fps (30 target) | 59.9 fps (60 target) |
| Desktop CPU render duration, 95th percentile | 7.0 ms | 5.0 ms, with live tracking |
| 3840×1920 / 30 fps test video: Qt swap interval, 95th percentile | 133.3 ms | 25.1 ms |
| Test-video longest observed swap interval | 329.4 ms | 29.2 ms |

The final video run averaged 59.4 Qt swaps/sec. The tracked desktop run averaged 59.9 swaps/sec and used SDK samples with a median callback-to-draw age of 2.6 ms (95th percentile 5.3 ms). These short runs demonstrate reduced software stalls, **not zero lag** or a guarantee for every workload. The 4K test used a generated MPEG-4 file and software decoding; no DRM or network streaming was involved. Local raw reports are under `artifacts/latency-*.json` (excluded from Git).

Official reference: [VITURE Glasses SDK documentation](https://www.viture.com/en-SG/developer/glasses-sdk/glasses).
