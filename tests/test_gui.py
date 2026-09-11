"""Run with SPACEWALKER_GUI_TESTS=1 under xvfb-run (uses real OpenGL and X11)."""
import math
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time
import pytest

pytestmark=pytest.mark.skipif(os.environ.get('SPACEWALKER_GUI_TESTS')!='1',
                             reason='Explicit opt-in: requires a temporary X server')


def test_text_reconstruction_preserves_edge_contrast(app):
    import numpy as np
    from spacewalker.geometry import Layout
    from spacewalker.renderer import Viewer
    pixels = np.full((360,640,4),255,dtype=np.uint8)
    pixels[:,:,0:3] = np.where(np.arange(640)%12<6,0,255)[None,:,None]
    class TextDesktop:
        last_sequence = 0
        def frame(self):
            return pixels.tobytes()
    viewer = Viewer(Layout(1,640,360))
    viewer.desktop = TextDesktop()
    viewer.fov = 26
    viewer.resize(960,540)
    viewer.show()
    try:
        until(app,lambda:viewer.has_source)
        contrasts = []
        for sharp in (False,True):
            viewer.sharp_text = sharp
            shot = viewer.grabFramebuffer()
            row = np.array([shot.pixelColor(x,shot.height()//2).red()
                            for x in range(50,shot.width()-50)],dtype=float)
            contrasts.append(np.mean(abs(row-127.5)))
        assert contrasts[1] > contrasts[0]+1
        assert not viewer.gl_error and not viewer.render_error
    finally:
        viewer.close()


def test_partial_monitor_upload_preserves_other_screens_and_channel_order(app):
    from contextlib import contextmanager
    import numpy as np
    from OpenGL import GL
    from PySide6.QtGui import QImage
    from spacewalker.geometry import Layout
    from spacewalker.renderer import Viewer
    pixels = np.zeros((360,1920,4),dtype=np.uint8)
    pixels[:,:,3] = 255
    for i in range(3):
        pixels[:,i*640:(i+1)*640,i] = 180
        pixels[:,i*640:(i+1)*640,1] = (np.arange(360)%240)[:,None]
    class Desktop:
        last_sequence = 0
        frame_generations = (1,1,1,0,0)
        @contextmanager
        def frame_view(self): yield pixels.reshape(-1)
        def command(self,**kwargs): pass
    viewer = Viewer(Layout(3,640,360))
    source = Desktop()
    viewer.desktop = source
    viewer.resize(800,500)
    viewer.show()
    def texture_matches():
        viewer.grabFramebuffer()
        viewer.makeCurrent()
        GL.glBindTexture(GL.GL_TEXTURE_2D,viewer.texture)
        actual = GL.glGetTexImage(GL.GL_TEXTURE_2D,0,GL.GL_RGBA,GL.GL_UNSIGNED_BYTE)
        np.testing.assert_array_equal(np.frombuffer(actual,dtype=np.uint8).reshape(pixels.shape),pixels)
        assert GL.glGetIntegerv(GL.GL_UNPACK_ROW_LENGTH) == 0
        viewer.doneCurrent()
    try:
        until(app,lambda:viewer.has_source)
        texture_matches()
        # Skip several producer frames: generations identify all changed screens,
        # including changes since the last image this consumer actually uploaded.
        pixels[:,:640,2] = 230
        pixels[:,1280:,0] = 47
        source.frame_generations = (5,1,3,0,0)
        texture_matches()
        pixels[:,640:1280,2] = (np.arange(360)%230)[:,None]
        source.frame_generations = (5,4,3,0,0)
        texture_matches()
        # Switching to an RGBA video and back must restore both full contents
        # and the BGRA swizzle, even when the texture dimensions match.
        viewer.switch_scene(1)
        rgba = QImage(1920,360,QImage.Format.Format_RGBA8888)
        rgba.fill('#d12e75')
        viewer.set_video_image(rgba)
        assert viewer.grabFramebuffer().pixelColor(400,250).name() == '#d12e75'
        viewer.switch_scene(0)
        texture_matches()
        assert not viewer.gl_error and not viewer.render_error
    finally:
        viewer.desktop = None
        viewer.close()


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QSurfaceFormat
    fmt=QSurfaceFormat()
    fmt.setVersion(3,3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)
    a=QApplication.instance() or QApplication([])
    yield a


def until(app,condition,timeout=8):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(.01)
    raise AssertionError('Condition did not become true within timeout')


@pytest.mark.parametrize('stereo',[False,True])
def test_stalled_tracking_levels_preview_and_reconnects_after_cleanup(app,monkeypatch,stereo):
    import numpy as np
    import threading
    from types import SimpleNamespace
    from spacewalker.__main__ import parser
    from spacewalker.app import MainWindow
    from spacewalker.geometry import Layout,viture_euler_to_gl
    from spacewalker.tracking import PoseState
    now = [100.]
    monkeypatch.setattr('spacewalker.app.time',SimpleNamespace(monotonic=lambda:now[0]))
    trackers = []
    closing = threading.Event()
    release = threading.Event()
    class Tracker:
        def __init__(self,*args):
            assert not trackers or trackers[-1].closed
            self.pose = PoseState()
            self.closed = False
            self.original_display_mode = None
            trackers.append(self)
        def start(self): self.pose.push(viture_euler_to_gl(25,32,47))
        def set_stereo(self,enabled):
            self.original_display_mode = 0x34 if enabled else None
        def close(self):
            if self is trackers[0]:
                closing.set()
                assert release.wait(5)
            self.closed = True
    monkeypatch.setattr('spacewalker.app.VitureTracker',Tracker)
    w = MainWindow(parser().parse_args(['--demo','--no-desktop']),Layout(2))
    w.status_timer.stop()
    w.show()
    try:
        w.connect_tracking()
        until(app,lambda:w.tracker and not w.jobs)
        first = w.tracker
        if stereo:
            w.set_hardware_stereo(True)
            until(app,lambda:not w.jobs)
            assert w.sbs.isChecked()
        first.pose.push(viture_euler_to_gl(55,40,50))
        w.viewer.read_orientation()
        assert not np.allclose(w.viewer.rotation,np.eye(3))
        # Simulate the reported stream stall after a rolled head pose.
        first.pose.received = time.monotonic()-2
        now[0] += 2
        w.update_status()
        until(app,closing.is_set)
        assert w.tracker is None and w.viewer.tracker is None
        w.viewer.read_orientation()
        np.testing.assert_allclose(w.viewer.rotation,np.eye(3))
        w.recenter()
        assert 'reconnecting' in w.message.text()
        assert w.reconnect_button.isVisible()
        now[0] += 10
        w.update_status()
        assert len(trackers) == 1  # No new SDK handle while cleanup is running.
        release.set()
        until(app,lambda:not w.jobs)
        w.update_status()
        assert len(trackers) == 1  # Backoff starts after cleanup finishes.
        now[0] += 1
        w.update_status()
        until(app,lambda:w.tracker and not w.jobs)
        assert w.tracker is trackers[1]
        assert w.sbs.isChecked() == stereo
        assert (w.tracker.original_display_mode is not None) == stereo
        w.update_status()
        assert w.tracking_status.text() == 'Tracking · Preview'
        assert not w.reconnect_button.isVisible()
        w.viewer.read_orientation()
        np.testing.assert_allclose(w.viewer.rotation,np.eye(3),atol=1e-6)
        assert w.layout.world_up == (0.,1.,0.)
        if stereo:
            # Restoring 2D after recovery must also change future reconnects.
            w.set_hardware_stereo(False)
            until(app,lambda:not w.jobs)
            w.reconnect_tracking()
            until(app,lambda:not w.jobs)
            now[0] += 1
            w.update_status()
            until(app,lambda:w.tracker and not w.jobs)
            assert w.tracker.original_display_mode is None
            assert not w.sbs.isChecked()
        w.disconnect_tracking()
        until(app,lambda:not w.jobs)
        now[0] += 60
        w.update_status()
        assert len(trackers) == (3 if stereo else 2) and not w.tracking_wanted
        assert not w.reconnect_stereo and not w.sbs.isChecked()
    finally:
        release.set()
        w.close()
        until(app,lambda:not w.jobs)


def test_tracking_retry_backoff_is_bounded_and_manual_disconnect_cancels(app,monkeypatch):
    from types import SimpleNamespace
    from spacewalker.__main__ import parser
    from spacewalker.app import MainWindow
    from spacewalker.geometry import Layout
    now,attempts = [100.],[]
    monkeypatch.setattr('spacewalker.app.time',SimpleNamespace(monotonic=lambda:now[0]))
    def unavailable(*args):
        attempts.append(now[0])
        raise RuntimeError('Test device unavailable')
    monkeypatch.setattr('spacewalker.app.VitureTracker',unavailable)
    w = MainWindow(parser().parse_args(['--demo','--no-desktop']),Layout())
    w.status_timer.stop()
    try:
        w.connect_tracking()
        until(app,lambda:not w.jobs)
        for delay in (1,2,4,8,16,30,30):
            previous = len(attempts)
            now[0] += delay-.01
            w.update_status()
            assert len(attempts) == previous
            now[0] += .01
            w.update_status()
            until(app,lambda:not w.jobs)
            assert len(attempts) == previous+1
        w.disconnect_tracking()
        previous = len(attempts)
        now[0] += 60
        w.update_status()
        assert not w.tracking_wanted and len(attempts) == previous
    finally:
        w.close()


@pytest.mark.parametrize('fails',[False,True])
def test_disconnect_during_tracking_startup_cancels_retries(app,monkeypatch,fails):
    import threading
    from spacewalker.__main__ import parser
    from spacewalker.app import MainWindow
    from spacewalker.geometry import Layout,IDENTITY
    from spacewalker.tracking import PoseState
    started,release,closed = threading.Event(),threading.Event(),threading.Event()
    class Tracker:
        def __init__(self,*args): self.pose = PoseState()
        def start(self):
            started.set()
            assert release.wait(5)
            if fails: raise RuntimeError('Test startup failed')
            self.pose.push(IDENTITY)
        def close(self): closed.set()
    monkeypatch.setattr('spacewalker.app.VitureTracker',Tracker)
    w = MainWindow(parser().parse_args(['--demo','--no-desktop']),Layout())
    w.status_timer.stop()
    try:
        w.connect_tracking()
        until(app,started.is_set)
        w.disconnect_tracking()
        release.set()
        until(app,lambda:not w.jobs)
        w.update_status()
        assert closed.is_set() and w.tracker is None
        assert not w.tracking_wanted and not w.tracking_busy
        assert w.tracking_status.text() == 'Mouse preview'
        assert w.reconnect_button.isHidden()
    finally:
        release.set()
        w.close()
        until(app,lambda:not w.jobs)


def test_control_icons_load_from_a_package_path_with_spaces(app,tmp_path,monkeypatch):
    from PySide6.QtCore import qInstallMessageHandler
    from spacewalker.__main__ import parser
    from spacewalker import app as app_module
    from spacewalker.geometry import Layout
    package = tmp_path/'Space walker'/'spacewalker'
    package.mkdir(parents=True)
    shutil.copytree(Path(app_module.__file__).with_name('icons'),package/'icons')
    monkeypatch.setattr(app_module,'__file__',str(package/'app.py'))
    messages = []
    previous = qInstallMessageHandler(lambda kind,context,message:messages.append(message))
    w = None
    try:
        w = app_module.MainWindow(parser().parse_args(['--demo','--no-desktop']),Layout())
        w.show()
        w.toggle_controls()
        app.processEvents()
        w.grab()
        assert not [m for m in messages if 'Cannot open file' in m or 'Could not parse' in m]
    finally:
        if w: w.close()
        qInstallMessageHandler(previous)


def test_browser_tracking_recenter_and_return_to_native(app,monkeypatch):
    import http.client
    import json
    from types import SimpleNamespace
    from spacewalker.__main__ import parser
    from spacewalker.app import MainWindow
    from spacewalker.geometry import Layout,viture_euler_to_gl
    from spacewalker.tracking import PoseState
    launched=[]
    monkeypatch.setattr('spacewalker.browser_launch.launch',lambda url:launched.append(url) or True)
    w=MainWindow(parser().parse_args(['--demo','--no-desktop']),Layout(1,640,360))
    pose=PoseState();pose.push(viture_euler_to_gl(0,0,0))
    w.tracker=w.viewer.tracker=SimpleNamespace(pose=pose,close=lambda:None)
    w.show();connection=None
    try:
        w.open_browser_video('https://www.youtube.com/watch?v=FAtdv94yzp4')
        until(app,lambda:launched and not w.jobs)
        bridge=w.browser_video
        assert launched==[bridge.url('https://www.youtube.com/watch?v=FAtdv94yzp4')]
        assert w.desktop is None and w.browser_timer.isActive()
        connection=http.client.HTTPConnection('127.0.0.1',bridge.http.server_port,timeout=2)
        connection.request('GET','/events?token='+bridge.token)
        response=connection.getresponse()
        assert response.status==200
        until(app,lambda:not w.viewer.timer.isActive())
        pose.push(viture_euler_to_gl(0,-20,45));w.update_browser_video()
        packet=json.loads(bridge.packet.removeprefix(b'data: '))
        assert packet['tracking'] and not packet['simulated']
        assert packet['yaw']==pytest.approx(45) and packet['pitch']==pytest.approx(20)
        bridge.commands.put('recenter');w.update_browser_video()
        packet=json.loads(bridge.packet.removeprefix(b'data: '))
        assert packet['yaw']==pytest.approx(0,abs=1e-5)
        assert packet['pitch']==pytest.approx(0,abs=1e-5)
        w.video_mode()
        assert w.browser_video is None and bridge.closed
        assert not w.browser_timer.isActive() and w.viewer.timer.isActive()
    finally:
        if connection:connection.close()
        w.close()
        until(app,lambda:not w.jobs)


def test_real_desktop_pointer_keyboard_and_cleanup(app,tmp_path):
    from PySide6.QtCore import QPoint,Qt
    from PySide6.QtTest import QTest
    from spacewalker.desktop import Desktop
    from spacewalker.geometry import Layout
    from spacewalker.renderer import Viewer
    layout=Layout(3,640,360)
    desktop=Desktop(layout,20)
    viewer=Viewer(layout)
    try:
        desktop.start()
        viewer.desktop=desktop
        viewer.resize(1000,600)
        viewer.show()
        until(app,lambda: viewer.has_source)
        assert viewer.gl_error is None
        # An empty desktop contains no demo windows; the first real app opens in the center.
        query='from Xlib import display; d=display.Display(); print(len(d.screen().root.get_full_property(d.intern_atom("_NET_CLIENT_LIST"),0).value))'
        until(app,lambda: int(subprocess.check_output([sys.executable,'-c',query],env=desktop.env))==0)
        log=tmp_path/'input.log'
        desktop.launch([sys.executable,str(Path(__file__).with_name('x11_client.py')),str(log)])
        until(app,lambda: log.exists())
        until(app,lambda: int(subprocess.check_output([sys.executable,'-c',query],env=desktop.env))==1)
        previous=viewer.frames
        until(app,lambda: viewer.frames!=previous)
        QTest.mouseClick(viewer,Qt.MouseButton.LeftButton,pos=QPoint(viewer.width()//2,viewer.height()//2))
        QTest.keyClick(viewer,Qt.Key.Key_K)
        until(app,lambda: 'key 107' in log.read_text())
        assert 'button 1' in log.read_text()
        frame=viewer.grabFramebuffer()
        pixel=frame.pixelColor(frame.width()//2,frame.height()//2+25)
        assert pixel.green()>pixel.red()*1.5  # Actual green X11 app is rendered.
        # Move the actual app to a specifically chosen display and back.
        import numpy as np
        def green_at(index):
            data = desktop.frame()
            if data is None:
                return False
            pixel = np.frombuffer(data,dtype=np.uint8).reshape(360,1920,4)[180,index*640+320,:3]
            return pixel[1]>int(pixel[2])*1.5 and pixel[1]>70
        desktop.command(type='move_to',screen=2)
        until(app,lambda: green_at(2))
        desktop.command(type='move_to',screen=1)
        until(app,lambda: green_at(1))
        if shutil.which('gnome-terminal') and shutil.which('dbus-run-session'):
            desktop.launch(['dbus-run-session', '--', 'gnome-terminal', '--wait'])
            try:
                until(app,lambda: int(subprocess.check_output([sys.executable,'-c',query],env=desktop.env))>=2)
                # GTK waits for ConfigureNotify after a denied resize request. A mapped
                # window alone is insufficient: verify it actually painted its content.
                import numpy as np
                def terminal_painted():
                    data = desktop.frame()
                    if data is None:
                        return False
                    pixels = np.frombuffer(data,dtype=np.uint8).reshape(360,1920,4)[:,:640,:3]
                    return len(np.unique(pixels.reshape(-1,3),axis=0)) > 8
                until(app,terminal_painted)
            except AssertionError as e:
                raise AssertionError('GNOME Terminal did not map and paint: '+desktop.log_text()) from e
        server,worker,folder=desktop.server,desktop.worker,desktop.temp.name
    finally:
        viewer.desktop=None
        viewer.close()
        desktop.close()
    assert server.poll() is not None and worker.poll() is not None
    assert not Path(folder).exists()


@pytest.mark.parametrize('stereo',[False,True])
def test_custom_monitor_gpu_and_pointer_agree(app,stereo):
    import numpy as np
    from PySide6.QtCore import QPointF
    from spacewalker.geometry import Layout
    from spacewalker.renderer import Viewer
    layout = Layout(3,640,360)
    layout.update_panel(0,azimuth=-30,elevation=10,distance=3,scale=.9,roll=-8)
    layout.update_panel(1,azimuth=8,elevation=8,distance=2.2,turn=18,tilt=-14,roll=12)
    layout.update_panel(2,azimuth=45,elevation=-15,distance=3.4,scale=.8)
    pixels = np.zeros((360,1920,4),dtype=np.uint8)
    for i in range(3):
        pixels[:,i*640:(i+1)*640,2] = 60+i*60
        pixels[:,i*640:(i+1)*640,1] = (np.arange(360)[:,None]*255/359).astype(np.uint8)
        pixels[:,i*640:(i+1)*640,0] = (np.arange(640)[None,:]*255/639).astype(np.uint8)
    pixels[:,:,3] = 255
    class GradientDesktop:
        last_sequence = 0
        def frame(self): return pixels.tobytes()
        def command(self,**args): pass
    viewer = Viewer(layout)
    viewer.desktop = GradientDesktop()
    viewer.stereo = stereo
    viewer.fov = 70
    viewer.resize(1500 if stereo else 1000,600)
    viewer.show()
    try:
        until(app,lambda: viewer.has_source)
        shot = viewer.grabFramebuffer()
        seen = set()
        gaps = 0
        for y in range(12,600,25):
            for x in range(12,shot.width(),25):
                ray,origin = viewer.pointer_ray(QPointF(x+.5,y+.5))
                hit = layout.hit(ray,origin)
                actual = shot.pixelColor(x,y).getRgb()
                if hit is None:
                    assert actual == (0,0,0,255)
                    gaps += 1
                else:
                    px,py = hit
                    index = px//640
                    seen.add(index)
                    expected = [60+index*60,py*255/359,(px%640)*255/639,255]
                    np.testing.assert_allclose(actual,expected,atol=2)
        assert seen == {0,1,2}
        assert gaps > 50
        assert viewer.gl_error is None and viewer.render_error is None
    finally:
        viewer.desktop = None
        viewer.close()


def test_arranging_drag_cancel_done_and_saved_layout(app,tmp_path):
    from PySide6.QtCore import QPoint,QPointF,QSettings,Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from spacewalker.__main__ import parser
    from spacewalker.app import MainWindow
    from spacewalker.geometry import Layout
    args = parser().parse_args(['--demo','--no-desktop'])
    w = MainWindow(args,Layout(3,640,360))
    settings = QSettings(str(tmp_path/'layout.ini'),QSettings.Format.IniFormat)
    w.settings = settings
    args.demo = False  # Exercise saving, with an isolated settings file and no tracking startup.
    commands = []
    class TestDesktop:
        last_sequence = 0
        def frame(self): return b'\x12\x12\x12\xff'*(3*640*360)
        def command(self,**args): commands.append(args)
        def close(self): pass
    w.desktop = w.viewer.desktop = TestDesktop()
    w.show()
    try:
        until(app,lambda: w.viewer.has_source)
        original = w.layout.to_dict()
        w.begin_arrange()
        app.processEvents()
        assert w.arrange_actions.isVisible() and not w.workspace_actions.isVisible()
        assert w.arrange_actions.geometry().bottom() < w.controls.height()
        commands.clear()
        center = QPoint(w.viewer.width()//2,w.viewer.height()//2)
        QTest.mousePress(w.viewer,Qt.MouseButton.LeftButton,pos=center)
        QTest.mouseMove(w.viewer,center+QPoint(70,-40))
        before_turn = w.layout.placement(1).azimuth
        # A grabbed display follows head rotation even without mouse motion.
        w.viewer.yaw = -.12
        w.viewer.grabFramebuffer()
        assert w.layout.placement(1).azimuth > before_turn+5
        QTest.mouseRelease(w.viewer,Qt.MouseButton.LeftButton,pos=center+QPoint(70,-40))
        assert w.layout.placement(1).azimuth > 0 and w.layout.placement(1).elevation > 0
        assert not any(c['type'] in ('motion','button','key') for c in commands)
        p = QPointF(center)
        wheel = QWheelEvent(p,p,QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        app.sendEvent(w.viewer,wheel)
        assert w.layout.placement(1).distance == pytest.approx(2.35)
        QTest.keyClick(w.viewer,Qt.Key.Key_Escape)
        assert w.layout.to_dict() == original
        assert not w.viewer.arranging and not w.controls.isVisible()
        w.begin_arrange()
        app.processEvents()
        map_view = w.layout_editor.map
        point = map_view.screen_point(0).toPoint()
        old = w.layout.placement(0).azimuth
        QTest.mousePress(map_view,Qt.MouseButton.LeftButton,pos=point)
        QTest.mouseMove(map_view,point+QPoint(-15,30))
        QTest.mouseRelease(map_view,Qt.MouseButton.LeftButton,pos=point+QPoint(-15,30))
        assert w.layout.placement(0).azimuth != old
        w.layout_editor.fields['elevation'].setValue(24)
        assert w.layout.placement(0).elevation == 24
        QTest.keyClick(w.viewer,Qt.Key.Key_Return)
        assert not w.viewer.arranging and not w.arrange_actions.isVisible()
        placed = w.layout.to_dict()
        assert settings.contains(w.layout_settings_key)
        w.layout.preset('arc')
        w.restore_monitor_layout()
        assert w.layout.to_dict() == placed
        w.enter_immersive()
        w.begin_arrange()
        app.processEvents()
        assert w.viewer.arranging and not w.controls.isVisible()
        QTest.keyClick(w.viewer,Qt.Key.Key_Return)
        assert w.isFullScreen() and not w.viewer.arranging and not w.toolbar.isVisible()
    finally:
        w.viewer.desktop = None
        w.close()


def test_single_screen_switch_preserves_layouts_and_changes_real_source(app,tmp_path,monkeypatch):
    from PySide6.QtCore import QSettings
    from spacewalker.__main__ import parser
    from spacewalker.app import MainWindow
    from spacewalker.geometry import Layout
    transitions = []
    class Desktop:
        native = True
        last_sequence = 0
        shortcuts = []
        def __init__(self,layout,source):
            self.layout,self.source = layout,source
        def start(self): transitions.append(('start',self.layout.count,self.source))
        def close(self): transitions.append(('close',self.layout.count,self.source))
        def poll_actions(self): return []
        def command(self,**kwargs): pass
        def frame(self): return b'\x22\x44\x66\xff'*(self.layout.width*self.layout.height*self.layout.count)
    monkeypatch.setattr('spacewalker.app.create_desktop',
                        lambda layout,fps,backend,source=None:Desktop(layout,source))
    args = parser().parse_args(['--demo','--no-desktop'])
    w = MainWindow(args,Layout(3,640,360))
    w.settings = QSettings(str(tmp_path/'modes.ini'),QSettings.Format.IniFormat)
    args.demo = False
    w.show()
    try:
        assert not hasattr(w,'mode_combo')
        assert [w.count_combo.itemData(i) for i in range(w.count_combo.count())]==[1,2,3,4,5]
        w.layout.update_panel(0,azimuth=-65,elevation=12)
        multiple = w.layout.to_dict()
        w.start_desktop()
        until(app,lambda:w.desktop is not None and not w.jobs)
        # A private X11 backend owns its app processes. Do not close it just
        # because the user selected another mode; native apps survive detaching.
        original_desktop = w.desktop
        original_desktop.native = False
        w.change_monitor_count(1)
        assert w.desktop is original_desktop and w.layout.count==3
        assert transitions==[('start',3,None)]
        original_desktop.native = True
        w.anchor.setChecked(False)
        w.count_combo.setCurrentIndex(w.count_combo.findData(1))
        w.count_combo.activated.emit(w.count_combo.currentIndex())
        assert not w.count_combo.isEnabled()
        until(app,lambda:w.desktop is not None and not w.jobs)
        assert w.layout.count == 1 and w.viewer.layout is w.layout
        assert w.layout_editor.selector.count()==1 and w.viewer.selected_screen==0
        assert w.viewer.anchored and w.anchor.isChecked()
        w.layout.update_panel(0,azimuth=27,elevation=9,distance=3.2,scale=.8)
        single = w.layout.to_dict()
        w.change_workspace('multiple')
        until(app,lambda:w.desktop is not None and not w.jobs)
        assert w.layout.to_dict()==multiple
        assert w.layout_editor.selector.count()==3
        for count in (2,4,5,3,5):
            w.count_combo.setCurrentIndex(w.count_combo.findData(count))
            w.count_combo.activated.emit(w.count_combo.currentIndex())
            assert not w.count_combo.isEnabled()
            until(app,lambda:w.desktop is not None and not w.jobs)
            assert w.layout.count==count and w.desktop.layout is w.viewer.layout is w.layout
            assert w.layout_editor.selector.count()==count and w.count_combo.currentData()==count
            assert not w.source_combo.isVisible()
            if count==3:
                assert w.layout.to_dict()==multiple
        w.layout.update_panel(4,azimuth=92,elevation=7)
        five = w.layout.to_dict()
        source = w.windowHandle().screen().name()
        w.change_workspace('single',source=source)
        until(app,lambda:w.desktop is not None and not w.jobs)
        assert w.layout.to_dict()==single
        assert w.desktop.source==source
        assert w.viewer.suppress_desktop
        shot = w.viewer.grabFramebuffer()
        assert shot.pixelColor(shot.width()//2,shot.height()//2).name()=='#000000'
        # A capture must never be presented full-screen on that same output.
        w.enter_immersive()
        assert not w.isFullScreen()
        assert 'different from the mirrored desktop' in w.message.text()
        assert transitions[:5]==[('start',3,None),('close',3,None),('start',1,None),
                                 ('close',1,None),('start',3,None)]
        assert w.count_combo.isEnabled() and w.source_combo.isEnabled()
    finally:
        w.close()
    assert w.settings.value('screen_mode')=='single'
    assert w.settings.value('single_source')==source
    assert w.settings.value('multiple_count',type=int)==5
    assert w.settings.contains('layouts/3-640x360') and w.settings.contains('layouts/1-640x360')

    settings = w.settings
    monkeypatch.setattr('spacewalker.app.QSettings',lambda *args:settings)
    def unavailable_sdk(_): raise RuntimeError('No tracking hardware during this test')
    monkeypatch.setattr('spacewalker.app.library_path',unavailable_sdk)
    restored = MainWindow(parser().parse_args(['--no-desktop']),Layout(3,640,360))
    try:
        assert restored.screen_mode=='single' and restored.layout.to_dict()==single
        assert restored.single_source==source
        restored.change_monitor_count(5)
        until(app,lambda:restored.desktop is not None and not restored.jobs)
        assert restored.count_combo.currentData()==5 and restored.layout.to_dict()==five
    finally:
        restored.close()
    # Explicit --screens 1 chooses the separate monitor even if a mirror was
    # remembered; fresh single-screen demo mode has the same separate default.
    for flags in (['--no-desktop','--screens','1'],['--demo','--no-desktop','--mode','single']):
        separate = MainWindow(parser().parse_args(flags),Layout(1,640,360) if '--screens' in flags else Layout(3,640,360))
        try:
            assert separate.screen_mode=='single' and separate.layout.count==1
            assert separate.single_source==''
        finally:
            separate.close()


def test_native_startup_error_shows_reason_and_keeps_retry_available(app,monkeypatch):
    from spacewalker.__main__ import parser
    from spacewalker.app import MainWindow
    from spacewalker.geometry import Layout
    error='Native monitors could not start. Traceback (most recent call last):\n  worker code\nRuntimeError: Hyprland did not activate the workspace on Spacewalker-1.'
    def fail(*args,**kwargs):raise RuntimeError(error)
    monkeypatch.setattr('spacewalker.app.create_desktop',fail)
    w=MainWindow(parser().parse_args(['--demo','--no-desktop']),Layout(1,640,360))
    try:
        w.change_monitor_count(3)
        until(app,lambda:not w.jobs)
        assert w.desktop is None and not w.desktop_busy
        assert w.count_combo.isEnabled() and w.start_button.isEnabled()
        assert w.count_combo.currentData()==3
        assert 'did not activate the workspace' in w.message.text()
        assert 'Traceback' not in w.message.text() and w.message.toolTip()==error
    finally:w.close()


def test_single_screen_remains_anchored_and_recenter_repositions_it(app):
    from types import SimpleNamespace
    from spacewalker.geometry import Layout,axis_angle
    from spacewalker.renderer import Viewer
    from spacewalker.tracking import PoseState
    class Desktop:
        last_sequence = 0
        def frame(self): return b'\x22\x44\x66\xff'*(640*360)
    viewer = Viewer(Layout(1,640,360))
    viewer.desktop = Desktop()
    pose = PoseState()
    pose.push(axis_angle([0,1,0],.4))
    viewer.tracker = SimpleNamespace(pose=pose)
    viewer.mouse_look = False
    viewer.resize(800,450)
    viewer.fov = 26
    viewer.show()
    try:
        until(app,lambda:viewer.has_source)
        assert viewer.grabFramebuffer().pixelColor(400,225).name()=='#664422'
        pose.push(axis_angle([0,1,0],1.4))
        assert viewer.grabFramebuffer().pixelColor(400,225).name()=='#000000'
        viewer.recenter()
        assert viewer.grabFramebuffer().pixelColor(400,225).name()=='#664422'
    finally:
        viewer.desktop = None
        viewer.close()


@pytest.mark.parametrize('image_format',['Format_RGBA8888','Format_RGB32'])
def test_gpu_stereo_eye_mapping_180_and_anchor_switch(app,image_format):
    from PySide6.QtGui import QColor,QImage,QPainter
    from spacewalker.geometry import Layout,axis_angle
    from spacewalker.renderer import Viewer
    from spacewalker.tracking import PoseState
    from types import SimpleNamespace
    viewer=Viewer(Layout())
    viewer.resize(800,400)
    viewer.stereo=True
    viewer.scene=3
    viewer.packing=1
    im=QImage(400,200,getattr(QImage.Format,image_format))
    p=QPainter(im)
    p.fillRect(0,0,200,200,QColor('red'))
    p.fillRect(200,0,200,200,QColor('blue'))
    p.end()
    viewer.set_video_image(im)
    viewer.show()
    try:
        until(app,lambda: viewer.has_source)
        shot=viewer.grabFramebuffer()
        assert shot.pixelColor(200,200).red()>240
        assert shot.pixelColor(600,200).blue()>240
        viewer.swap_eyes=True
        shot=viewer.grabFramebuffer()
        assert shot.pixelColor(200,200).blue()>240
        viewer.swap_eyes=False
        viewer.packing=2
        p=QPainter(im)
        p.fillRect(0,0,400,100,QColor('red'))
        p.fillRect(0,100,400,100,QColor('blue'))
        p.end()
        viewer.set_video_image(im)
        shot=viewer.grabFramebuffer()
        assert shot.pixelColor(200,200).red()>240
        assert shot.pixelColor(600,200).blue()>240
        viewer.scene=2
        viewer.yaw=math.pi
        shot=viewer.grabFramebuffer()
        assert shot.pixelColor(200,200).red()==0
        viewer.anchored=False
        shot=viewer.grabFramebuffer()
        assert shot.pixelColor(200,200).red()>240  # Head-follow mode resets view orientation.
        viewer.anchored=True
        viewer.recenter()
        assert viewer.grabFramebuffer().pixelColor(200,200).red()>240
        pose=PoseState()
        pose.push([1,0,0,0])
        viewer.tracker=SimpleNamespace(pose=pose)
        pose.push(axis_angle([0,1,0],math.pi))
        assert viewer.grabFramebuffer().pixelColor(200,200).red()==0
    finally:
        viewer.close()


def test_video_decode_seek_pause_and_projection(app,tmp_path):
    from spacewalker.__main__ import parser
    from spacewalker.geometry import Layout
    from spacewalker.app import MainWindow
    from PySide6.QtMultimedia import QMediaPlayer
    path=tmp_path/'video.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc2=size=640x320:rate=24',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','5','-c:v','mpeg4','-c:a','aac',str(path)],check=True)
    args=parser().parse_args(['--demo','--no-desktop'])
    w=MainWindow(args,Layout())
    w.show()
    try:
        app.processEvents()
        assert not w.controls.isVisible()
        w.toggle_controls()
        assert w.controls.isVisible()
        w.enter_immersive()
        app.processEvents()
        assert not w.toolbar.isVisible() and not w.controls.isVisible() and not w.footer.isVisible()
        w.leave_immersive()
        app.processEvents()
        assert w.toolbar.isVisible() and w.controls.isVisible()
        w.open_video(str(path))
        until(app,lambda:w.viewer.has_source and w.player.position()>300)
        assert w.viewer.texture_size==(640,320)
        assert w.player.hasAudio()
        w.toggle_play()
        assert w.player.playbackState()==QMediaPlayer.PlaybackState.PausedState
        w.player.setPosition(3000)
        until(app,lambda:w.player.position()>=2900)
        w.projection.setCurrentIndex(1)
        assert w.viewer.scene==2
        w.packing.setCurrentIndex(1)
        assert w.viewer.packing==1
        assert w.player.error()==QMediaPlayer.Error.NoError
    finally:
        w.close()


@pytest.mark.parametrize('stereo', [False, True])
def test_optical_passthrough_between_displays_is_pure_black(app, stereo):
    from spacewalker.geometry import Layout
    from spacewalker.renderer import Viewer

    class WhiteDesktop:
        last_sequence = 0

        def frame(self):
            return b'\xff'*(3*640*360*4)

    viewer = Viewer(Layout(3,640,360))
    viewer.desktop = WhiteDesktop()
    viewer.stereo = stereo
    viewer.resize(1200,500)
    viewer.show()
    try:
        until(app, lambda: viewer.has_source)
        shot = viewer.grabFramebuffer()
        eye_width = shot.width()/(2 if stereo else 1)
        for eye in range(2 if stereo else 1):
            cx = int((eye+.5)*eye_width)
            cy = shot.height()//2
            assert shot.pixelColor(cx,cy).red() == 255
            # Halfway between the center screen's 22° edge and the adjacent screen's 25° edge.
            gap_x = int(cx + math.tan(math.radians(23.5))/math.tan(math.radians(viewer.fov/2))*shot.height()/2)
            for x,y in [(gap_x,cy), (cx,2), (cx,shot.height()-3)]:
                assert shot.pixelColor(x,y).getRgb() == (0,0,0,255)
        viewer.desktop = None
        viewer.has_source = False
        assert viewer.grabFramebuffer().pixelColor(100,100).getRgb() == (0,0,0,255)
    finally:
        viewer.desktop = None
        viewer.close()


def test_head_pose_is_read_after_static_work_even_when_capture_stops(app):
    from spacewalker.geometry import Layout,axis_angle,IDENTITY
    from spacewalker.renderer import Viewer
    from spacewalker.tracking import PoseState
    from types import SimpleNamespace
    class OneFrameDesktop:
        last_sequence = 0
        def frame(self):
            if self.last_sequence:
                return None
            self.last_sequence = 1
            return b'\xff'*(640*360*4)
        def command(self,**args): pass
    viewer = Viewer(Layout(1,640,360))
    viewer.desktop = OneFrameDesktop()
    pose = PoseState()
    pose.push(IDENTITY)
    viewer.tracker = SimpleNamespace(pose=pose)
    viewer.resize(800,500)
    viewer.show()
    try:
        until(app,lambda: viewer.has_source)
        assert viewer.grabFramebuffer().pixelColor(400,250).red() == 255
        uploads = len(viewer.upload_times_ms)
        original = viewer.uniform
        def during_static_work(name,*args):
            original(name,*args)
            if name == 'hasSource':
                pose.push(axis_angle([0,1,0],math.pi/2))
        viewer.uniform = during_static_work
        shot = viewer.grabFramebuffer()
        assert shot.pixelColor(400,250).getRgb() == (0,0,0,255)
        assert len(viewer.upload_times_ms) == uploads
    finally:
        viewer.desktop = None
        viewer.close()


def test_viture_turns_reveal_the_correct_monitor_and_recenter(app):
    import ctypes as C
    from spacewalker.geometry import Layout
    from spacewalker.renderer import Viewer
    from spacewalker.tracking import VitureTracker,PoseState
    class ColoredDesktop:
        last_sequence = 0
        def frame(self):
            row = b'\0\0\xff\xff'*640+b'\0\xff\0\xff'*640+b'\xff\0\0\xff'*640
            return row*360
        def command(self,**args): pass
    tracker = VitureTracker.__new__(VitureTracker)
    tracker.pose = PoseState()
    def look(yaw):
        tracker._on_pose((C.c_float*7)(0,0,yaw,1,0,0,0),0)
    look(0)
    viewer = Viewer(Layout(3,640,360))
    viewer.desktop = ColoredDesktop()
    viewer.tracker = tracker
    viewer.fov = 26
    viewer.resize(960,540)
    viewer.show()
    try:
        until(app,lambda: viewer.has_source)
        for yaw,color in [(0,'#00ff00'),(47,'#ff0000'),(-47,'#0000ff')]:
            look(yaw)
            assert viewer.grabFramebuffer().pixelColor(480,270).name() == color
        viewer.recenter()
        assert viewer.grabFramebuffer().pixelColor(480,270).name() == '#00ff00'
    finally:
        viewer.desktop = None
        viewer.close()


def test_rendered_side_monitors_are_level_after_pitched_recenter(app):
    import numpy as np
    from types import SimpleNamespace
    from PySide6.QtCore import QPointF
    from spacewalker.geometry import Layout,multiply,viture_euler_to_gl
    from spacewalker.renderer import Viewer
    from spacewalker.tracking import PoseState
    pixels = np.zeros((360,640*3,4),dtype=np.uint8)
    pixels[:,:,1] = 110
    pixels[:,:,3] = 255
    pixels[176:184,:,:3] = 255  # A level stripe through every monitor's center.
    class StripedDesktop:
        last_sequence = 0
        def frame(self): return pixels.tobytes()
        def command(self,**args): pass
    viewer = Viewer(Layout(3,640,360))
    viewer.desktop = StripedDesktop()
    pose = PoseState()
    pose.push(viture_euler_to_gl(0,0,0))
    viewer.tracker = SimpleNamespace(pose=pose)
    viewer.mouse_look = False
    viewer.fov = 55
    viewer.resize(800,500)
    viewer.show()
    try:
        until(app,lambda: viewer.has_source)
        for angles in [(0,20,35),(0,-30,-140),(12,25,179)]:
            reference = viture_euler_to_gl(*angles)
            pose.push(reference)
            saved = viewer.layout.to_dict()
            viewer.recenter()
            assert viewer.layout.to_dict() == saved
            for i in range(3):
                center = viewer.layout.placement(i).center
                forward = center/np.linalg.norm(center)
                yaw = -math.degrees(math.atan2(forward[0],-forward[2]))
                pitch = -math.degrees(math.asin(np.clip(forward[1],-1,1)))
                pose.push(multiply(reference,viture_euler_to_gl(0,pitch,yaw)))
                shot = viewer.grabFramebuffer()
                stripe_rows = []
                for x in (300,500):
                    rows = [y for y in range(175,325) if shot.pixelColor(x,y).red()>200]
                    assert rows
                    stripe_rows.append(float(np.mean(rows)))
                    ray,origin = viewer.pointer_ray(QPointF(x+.5,np.mean(rows)+.5))
                    hit = viewer.layout.hit(ray,origin)
                    assert hit[0]//640 == i and abs(hit[1]-180) <= 1
                assert abs(stripe_rows[0]-stripe_rows[1]) <= 1
        assert not viewer.gl_error and not viewer.render_error
    finally:
        viewer.desktop = None
        viewer.close()


@pytest.mark.parametrize('stereo',[False,True])
def test_rendered_monitors_have_parallel_vertical_sides_between_screens(app,stereo):
    import numpy as np
    from types import SimpleNamespace
    from PySide6.QtCore import QPointF
    from spacewalker.geometry import Layout,multiply,viture_euler_to_gl
    from spacewalker.renderer import Viewer
    from spacewalker.tracking import PoseState
    pixels = np.full((360,640*3,4),50,dtype=np.uint8)
    pixels[:,:,3] = 255
    for i in range(3):
        # Off-center vertical lines expose keystone skew. A center line on a
        # panel aimed at the eye can project vertically despite tilted sides.
        stripe = pixels[:,i*640+476:i*640+484,:3]
        stripe[:,:,:] = 0
        stripe[:,:,2-i] = 255  # BGRA -> one distinct RGB primary per monitor.
    class StripedDesktop:
        last_sequence = 0
        def frame(self): return pixels.tobytes()
        def command(self,**args): pass
    layout = Layout(3,640,360)
    for i,(azimuth,elevation) in enumerate([(-11.15,-15.31),(-11.37,11.69),(34.56,-.72)]):
        layout.update_panel(i,azimuth=azimuth,elevation=elevation)
    saved = layout.to_dict()
    viewer = Viewer(layout)
    viewer.desktop = StripedDesktop()
    pose = PoseState()
    reference = viture_euler_to_gl(0,20,35)
    pose.push(reference)
    viewer.tracker = SimpleNamespace(pose=pose)
    viewer.mouse_look = False
    viewer.stereo = stereo
    viewer.fov = 70
    eye_width,height = 600,450
    viewer.resize(eye_width*(2 if stereo else 1),height)
    viewer.show()
    try:
        until(app,lambda: viewer.has_source)
        # Level head looking between two monitors, not directly at either one.
        pose.push(multiply(reference,viture_euler_to_gl(0,0,-10)))
        shot = viewer.grabFramebuffer()
        image = shot.convertToFormat(shot.Format.Format_RGBA8888)
        rgb = np.frombuffer(image.constBits(),dtype=np.uint8).reshape(height,-1,4)[:,:,:3]
        for eye in range(2 if stereo else 1):
            visible = []
            for i in range(3):
                area = rgb[:,eye*eye_width:(eye+1)*eye_width,:]
                ys,xs = np.nonzero((area[:,:,i]>200)&(np.max(np.delete(area,i,axis=2),axis=2)<25))
                if not len(ys) or np.ptp(ys)<70:
                    continue
                visible.append(i)
                # Exclude the stripe's ends where the monitor border clips it.
                stripe_x = [float(np.mean(xs[ys==y])) for y in np.unique(ys)[5:-5]]
                assert np.ptp(stripe_x)<=1, (i,min(stripe_x),max(stripe_x))
                # The shader's vertical strip and CPU picking must still agree.
                y = int(np.median(ys))
                x = float(np.mean(xs[ys==y]))+eye*eye_width
                ray,origin = viewer.pointer_ray(QPointF(x+.5,y+.5))
                hit = layout.hit(ray,origin)
                assert hit is not None and hit[0]//640 == i
                assert abs(hit[0]%640-480)<=2
            assert {1,2}.issubset(visible)
        assert layout.to_dict() == saved
        assert not viewer.gl_error and not viewer.render_error
    finally:
        viewer.desktop = None
        viewer.close()


def test_glasses_calibration_is_editable_and_independent_of_preview(app,tmp_path):
    from PySide6.QtCore import QSettings
    from spacewalker.app import MainWindow
    from spacewalker.__main__ import parser
    from spacewalker.geometry import Layout
    args = parser().parse_args(['--demo','--no-desktop'])
    w = MainWindow(args,Layout())
    w.settings = QSettings(str(tmp_path/'calibration.ini'),QSettings.Format.IniFormat)
    args.demo = False
    w.show()
    try:
        app.processEvents()
        w.glasses_fov_control.setValue(28)
        assert w.viewer.fov == 55
        w.enter_immersive()
        assert w.viewer.fov == 28 and w.fov.value() == 55
        w.fov.setValue(70)
        assert w.viewer.fov == 28
        w.glasses_fov_control.setValue(27)
        assert w.viewer.fov == 27
        w.leave_immersive()
        assert w.viewer.fov == 70
        w.enter_immersive()
        assert w.viewer.fov == 27
    finally:
        w.close()
    assert w.settings.value('glasses_fov',type=float) == 27
    assert w.settings.value('preview_fov',type=float) == 70


@pytest.mark.parametrize('fail', [False, True])
def test_display_mode_switch_keeps_ui_responsive_and_serializes_disconnect(app, fail):
    import threading
    from types import SimpleNamespace
    from PySide6.QtCore import QTimer
    from spacewalker.__main__ import parser
    from spacewalker.app import MainWindow
    from spacewalker.geometry import Layout
    from spacewalker.tracking import PoseState
    started, release = threading.Event(), threading.Event()
    calls, ticks = [], []
    def switch(enabled):
        calls.append(('switch', enabled))
        started.set()
        assert release.wait(3)
        if fail:
            raise RuntimeError('Simulated firmware failure')
    def close():
        calls.append(('close', None))
        return []
    window = MainWindow(parser().parse_args(['--demo', '--no-desktop']), Layout(1,640,360))
    tracker = SimpleNamespace(pose=PoseState(), set_stereo=switch, close=close)
    window.tracker = window.viewer.tracker = tracker
    window.show()
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda:ticks.append(True))
    heartbeat.start(5)
    try:
        window.set_hardware_stereo(True)
        until(app, lambda:started.is_set() and len(ticks)>2)
        window.set_hardware_stereo(False)  # Cannot race a second SDK operation.
        window.disconnect_tracking()      # Queued until the switch finishes.
        assert calls == [('switch', True)]
        window.close()                    # Also waits for SDK cleanup.
        assert window.closing and window.isVisible()
        release.set()
        until(app, lambda:not window.jobs and not window.isVisible())
        assert calls == [('switch', True), ('close', None)]
        assert window.sbs.isChecked() is (not fail)
    finally:
        release.set()
        heartbeat.stop()
        window.close()
        until(app, lambda:not window.jobs)


def test_capture_failure_releases_resources_and_allows_restart(app):
    from spacewalker.__main__ import parser
    from spacewalker.app import MainWindow
    from spacewalker.geometry import Layout
    window = MainWindow(parser().parse_args(['--demo', '--no-desktop', '--desktop-backend', 'private']),
                        Layout(1,640,360))
    window.show()
    try:
        window.start_desktop()
        until(app, lambda:window.desktop is not None and window.viewer.has_source and not window.jobs)
        old = window.desktop
        old.worker.terminate()
        old.worker.wait(timeout=3)
        until(app, lambda:window.desktop is None and not window.jobs)
        assert old.buffer is None and old.server is None
        assert window.start_button.isEnabled()
        assert window.start_button.text() == 'Restart workspace'
        window.start_button.click()
        until(app, lambda:window.desktop is not None and window.viewer.has_source and not window.jobs)
        assert window.desktop is not old
        assert not window.viewer.render_error
        assert window.viewer.timer.isActive()
    finally:
        window.close()
        until(app, lambda:not window.jobs)
