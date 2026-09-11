import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import sys
import time


def parser():
    from . import __version__
    p = argparse.ArgumentParser(description='Linux spatial workspace and head-tracked VR video viewer')
    p.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    p.add_argument('--demo', action='store_true', help='Mouse preview; do not open tracking hardware')
    p.add_argument('--sdk', help='Path to current VITURE libglasses.so')
    p.add_argument('--pid', type=lambda s: int(s,0), help='USB product ID, e.g. 0x1301')
    p.add_argument('--screens', type=int, choices=range(1,6), help='Number of separate monitors (default 3)')
    p.add_argument('--mode', choices=['single','multiple'], help='Start in single-screen or multi-monitor mode')
    p.add_argument('--source', help='Mirror this existing Hyprland display in single-screen mode, e.g. eDP-1')
    p.add_argument('--resolution', default='1920x1080', help='Resolution per virtual screen (default 1920x1080, matching the glasses)')
    p.add_argument('--capture-fps', type=int, choices=range(1,121), default=60,
                   help='Desktop capture target, independent of head tracking (default 60)')
    p.add_argument('--desktop-backend', choices=['auto','hyprland','private'], default='auto',
                   help='Real Hyprland monitors by default; private selects the separate X11 workspace')
    p.add_argument('--no-desktop', action='store_true', help='Do not attach monitors automatically')
    p.add_argument('--video', help='Local video file to open')
    p.add_argument('--web-video',metavar='URL',help='Open YouTube 360 or a direct panoramic video link in your browser')
    p.add_argument('--projection', choices=['flat','180','360'], default='360')
    p.add_argument('--packing', choices=['mono','sbs','tb'], default='mono')
    p.add_argument('--doctor', action='store_true', help='Print diagnostics without opening the UI or device')
    p.add_argument('--probe-tracking', type=float, metavar='SECONDS', help='Read real head tracking for a bounded interval')
    p.add_argument('--profile-seconds',type=float,metavar='SECONDS',
                   help='Run for 3–60 seconds and report software render/capture/pose timing')
    p.add_argument('--profile-output',help='Also save the timing report to this JSON file')
    p.add_argument('--smoke-seconds', type=float, help=argparse.SUPPRESS)
    p.add_argument('--screenshot', help=argparse.SUPPRESS)
    return p


def doctor(args):
    from .tracking import devices, library_path
    report = {'session': os.environ.get('XDG_SESSION_TYPE', 'unknown'),
              'viture_usb_products': [f'0x{p:04x}' for p in devices()],
              'desktop': os.environ.get('XDG_CURRENT_DESKTOP', 'unknown'),
              'programs': {p: shutil.which(p) for p in ['hyprctl','cc','wayland-scanner','Xvfb','xauth','xrandr','xterm','gnome-terminal']}}
    try:
        path = library_path(args.sdk)
        lib = ctypes.CDLL(path)
        report['sdk'] = path
        report['sdk_current_abi'] = hasattr(lib, 'xr_device_provider_is_product_support_imu_frequency')
    except (RuntimeError, OSError) as e:
        report['sdk_error'] = str(e)
    report['hidraw'] = []
    for p in Path('/sys/class/hidraw').glob('*'):
        try:
            info = (p/'device/uevent').read_text()
            if '35CA' in info.upper():
                node = Path('/dev')/p.name
                report['hidraw'].append({'node':str(node),'read_write':os.access(node,os.R_OK|os.W_OK)})
        except OSError:
            pass
    print(json.dumps(report, indent=2))


def main():
    args = parser().parse_args()
    if args.web_video and args.video:
        raise SystemExit('Choose either --web-video or --video.')
    if args.source and args.mode == 'multiple':
        raise SystemExit('--source requires single-screen mode; omit --mode or use --mode single.')
    if args.profile_seconds is not None and not 3 <= args.profile_seconds <= 60:
        raise SystemExit('Profile duration must be between 3 and 60 seconds.')
    if args.profile_output and not args.profile_seconds:
        raise SystemExit('--profile-output requires --profile-seconds.')
    if args.smoke_seconds is not None and not 0 < args.smoke_seconds <= 60:
        raise SystemExit('Smoke-test duration must be >0 and <=60 seconds.')
    if args.screenshot and not args.smoke_seconds:
        raise SystemExit('--screenshot requires --smoke-seconds.')
    if args.doctor:
        doctor(args)
        return 0
    if args.probe_tracking is not None:
        from .tracking import VitureTracker
        if not 0 < args.probe_tracking <= 60:
            raise SystemExit('Tracking probe duration must be >0 and <=60 seconds.')
        tracker = None
        try:
            tracker = VitureTracker(args.sdk, args.pid)
            tracker.start()
            deadline = time.monotonic()+args.probe_tracking
            while time.monotonic() < deadline:
                time.sleep(.25)
                print(json.dumps({'samples':tracker.pose.samples,'age_ms':round(tracker.pose.age*1000,2),
                                  'orientation_wxyz':tracker.pose.orientation().tolist()}), flush=True)
            return 0 if tracker.pose.samples else 1
        except (OSError, RuntimeError) as e:
            print(e, file=sys.stderr)
            return 1
        finally:
            if tracker:
                tracker.close()
    from .geometry import Layout
    try:
        width,height = map(int,args.resolution.lower().split('x'))
        layout = Layout(args.screens or 3,width,height)
    except ValueError as e:
        raise SystemExit(f'Invalid screen layout: {e}')
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    fmt = QSurfaceFormat()
    fmt.setVersion(3,3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)
    app.setApplicationName('Spacewalker Linux')
    app.setOrganizationName('SpacewalkerLinux')
    app.setDesktopFileName('spacewalker-linux')
    from . import __version__
    app.setApplicationVersion(__version__)
    app.setStyle('Fusion')
    from .app import MainWindow
    window = MainWindow(args,layout)
    window.show()
    result = [0]
    if args.profile_seconds:
        def clear_warmup():
            for samples in (window.viewer.cpu_ms,window.viewer.upload_times_ms,window.viewer.pose_age_ms,
                            window.viewer.source_age_ms,window.viewer.present_intervals_ms):
                samples.clear()
            if window.desktop:
                window.desktop.capture_progress.clear()
            window.video_frames.conversion_ms.clear()
        QTimer.singleShot(2000,clear_warmup)
        def profile_done():
            report = window.viewer.performance_report()
            report.update(capture_target_fps=args.capture_fps,screen_count=window.layout.count,
                          screen_resolution=[window.layout.width,window.layout.height],tracking_connected=bool(window.tracker),
                          desktop_running=bool(window.desktop),has_source=window.viewer.has_source,
                          gl_error=window.viewer.gl_error,render_error=window.viewer.render_error)
            serialized = json.dumps(report,indent=2)
            print(serialized,flush=True)
            if args.profile_output:
                try:
                    path = Path(args.profile_output).expanduser()
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_text(serialized+'\n')
                except OSError as e:
                    print(f'Cannot save timing report: {e}',file=sys.stderr)
                    result[0] = 1
            if window.viewer.gl_error or window.viewer.render_error or (
                    not args.no_desktop and not args.video and not args.web_video and not window.desktop) or (
                    args.video and not window.viewer.has_source):
                result[0] = 1
            window.close()
        QTimer.singleShot(int(args.profile_seconds*1000),profile_done)
    if args.smoke_seconds:
        def finish():
            if window.viewer.gl_error or window.viewer.render_error or (not args.no_desktop and not args.video and not args.web_video and not window.desktop):
                result[0] = 1
            if args.screenshot:
                Path(args.screenshot).parent.mkdir(parents=True,exist_ok=True)
                window.grab().save(args.screenshot)
            print(json.dumps({'render_fps':window.viewer.fps,'desktop':bool(window.desktop),
                              'texture':window.viewer.texture_size,'gl_error':window.viewer.gl_error}),flush=True)
            window.close()
        QTimer.singleShot(int(args.smoke_seconds*1000),finish)
    app.exec()
    return result[0]


if __name__ == '__main__':
    sys.exit(main())
