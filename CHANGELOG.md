# Changelog

## 0.1.0rc1

Initial independent Linux release candidate for VITURE spatial monitors and panoramic video.

- Refined charcoal UI with compact workspace/video navigation, quieter toolbar actions, clearer settings hierarchy, visible keyboard focus, and matching browser-player controls. Glasses view retains pure-black gaps and hides all controls.

- Native Hyprland outputs, one to five independently arranged screens, optional physical-display mirroring, and an explicit private X11 backend.
- Gen1/Gen2 rotational tracking, recentering, optical calibration, SBS output, local flat/180°/360° video, and authenticated browser video tracking.
- Cached monitor geometry now serves both rendering and pointer projection; repeated pointer events no longer rebuild every panel's transform.
- Hardware display-mode changes and disconnects run outside the UI thread. Disconnect and application exit wait for pending SDK operations.
- Capture errors release the failed backend and enable Restart workspace; opening a new video restores the render loop after conversion errors.
- Desktop launchers correctly quote paths containing spaces and shell metacharacters, and validate before installation.
- SDK discovery selects the host ELF architecture when an archive contains multiple architectures.
- Local browser command routes are exact; rejected HTTP requests close connections before unread bodies can be interpreted as new requests.
- Added package metadata, a single version source and `--version`, a provider-neutral release gate, source/wheel asset validation, and checksums.
