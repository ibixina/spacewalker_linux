from pathlib import Path
from collections import deque
import math
import time
import numpy as np
from OpenGL import GL
from OpenGL.GL.shaders import compileShader, compileProgram
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from .geometry import IDENTITY, axis_angle, matrix, multiply, view_ray
from .video import upload_image


SPECIAL_KEYS = {Qt.Key.Key_Escape: 0xff1b, Qt.Key.Key_Tab: 0xff09, Qt.Key.Key_Backtab: 0xff09,
    Qt.Key.Key_Backspace: 0xff08, Qt.Key.Key_Return: 0xff0d, Qt.Key.Key_Enter: 0xff8d,
    Qt.Key.Key_Insert: 0xff63, Qt.Key.Key_Delete: 0xffff, Qt.Key.Key_Home: 0xff50,
    Qt.Key.Key_End: 0xff57, Qt.Key.Key_Left: 0xff51, Qt.Key.Key_Up: 0xff52,
    Qt.Key.Key_Right: 0xff53, Qt.Key.Key_Down: 0xff54, Qt.Key.Key_PageUp: 0xff55,
    Qt.Key.Key_PageDown: 0xff56, Qt.Key.Key_Shift: 0xffe1, Qt.Key.Key_Control: 0xffe3,
    Qt.Key.Key_Alt: 0xffe9, Qt.Key.Key_Meta: 0xffeb, Qt.Key.Key_CapsLock: 0xffe5}
for i in range(12):
    SPECIAL_KEYS[int(Qt.Key.Key_F1)+i] = 0xffbe+i


def keysym(event):
    if event.nativeVirtualKey():
        return event.nativeVirtualKey()
    key = event.key()
    if key in SPECIAL_KEYS:
        return SPECIAL_KEYS[key]
    if 32 <= key <= 126:
        return ord(chr(key).lower())
    text = event.text()
    return (ord(text) if ord(text) < 256 else 0x01000000+ord(text)) if len(text) == 1 else 0


class Viewer(QOpenGLWidget):
    problem = Signal(str)
    escape = Signal()
    recentered = Signal()
    fullscreen_requested = Signal()
    play_pause = Signal()
    layout_changed = Signal()
    screen_selected = Signal(int)
    edit_finished = Signal(bool)

    def __init__(self, layout, parent=None):
        super().__init__(parent)
        self.layout = layout
        self.desktop = self.tracker = None
        self.fov = 55.
        self.smoothing_ms = 0.
        self.stereo = self.swap_eyes = False
        self.sharp_text = True
        self.anchored = True
        self.arranging = False
        self.selected_screen = layout.count//2
        self.panel_drag = None
        self.panel_drag_position = None
        self.mouse_look = True
        self.yaw = self.pitch = 0.
        self.rotation = np.eye(3)
        self.scene, self.packing = 0, 0
        self.cursor = (-100., -100.)
        self.drag = None
        self.texture = self.vao = self.program = None
        self.locations = {}
        self.uniform_values = {}
        self.texture_size = (1, 1)
        self.texture_format = None
        self.uploaded_generations = ()
        self.pending_image = None
        self.video_image = None
        self.video_frames = None
        self.video_sequence = 0
        self.has_source = False
        self.suppress_desktop = False
        self.frames, self.fps, self.last_stat = 0, 0., time.monotonic()
        self.gl_error = None
        self.render_error = None
        self.cpu_ms = deque(maxlen=600)
        self.upload_times_ms = deque(maxlen=600)
        self.pose_age_ms = deque(maxlen=600)
        self.source_age_ms = deque(maxlen=600)
        self.present_intervals_ms = deque(maxlen=600)
        self.last_present = 0.
        self.last_pose_received = 0.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(420, 280)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.update)
        # Continue on presentation, with a watchdog for expose/context transitions.
        self.frameSwapped.connect(self.presented)
        self.timer.start(100)

    def presented(self):
        now = time.monotonic()
        if self.last_present:
            self.present_intervals_ms.append((now-self.last_present)*1000)
        self.last_present = now
        if self.timer.isActive() and self.isVisible():
            self.update()

    def read_orientation(self):
        q = self.tracker.pose.orientation(self.smoothing_ms) if self.tracker and self.anchored else IDENTITY
        self.last_pose_received = self.tracker.pose.sample_received if self.tracker and self.anchored else 0.
        if self.mouse_look and self.anchored:
            q = multiply(q, multiply(axis_angle([0,1,0], self.yaw), axis_angle([1,0,0], self.pitch)))
        self.rotation = matrix(q)

    def performance_report(self):
        def summary(values):
            return {'median':round(float(np.median(values)),3),
                    'p95':round(float(np.percentile(values,95)),3),
                    'max':round(max(values),3),'samples':len(values)} if values else None
        intervals = self.present_intervals_ms
        return {'cpu_render_ms':summary(self.cpu_ms),'cpu_upload_ms':summary(self.upload_times_ms),
                'sdk_sample_age_at_draw_ms':summary(self.pose_age_ms),
                'desktop_age_at_draw_ms':summary(self.source_age_ms),
                'qt_swap_interval_ms':summary(intervals),
                'qt_swap_fps':round(1000/float(np.mean(intervals)),2) if intervals else None,
                'capture_fps':getattr(self.desktop,'capture_fps',None),
                'video_conversion_ms':summary(tuple(self.video_frames.conversion_ms)) if self.video_frames else None,
                'output_refresh_hz':self.screen().refreshRate() if self.screen() else None,
                'note':'Software timings only; SDK sensor processing, compositor scanout, and optical latency are not measured.'}

    def recenter(self):
        self.yaw = self.pitch = 0.
        if self.tracker:
            self.tracker.pose.recenter()
        self.sync_world_up()
        self.update()
        self.recentered.emit()

    def sync_world_up(self):
        self.layout.world_up = self.tracker.pose.reference_up if self.tracker and self.anchored else (0.,1.,0.)

    def set_arranging(self, enabled):
        self.release_input()
        self.arranging = enabled
        self.panel_drag = None
        self.drag = None
        self.cursor = (-100., -100.)
        self.setCursor(Qt.CursorShape.OpenHandCursor if enabled else Qt.CursorShape.ArrowCursor)

    def place_selected_here(self):
        self.layout.place_on_ray(self.selected_screen,self.rotation @ np.array([0.,0.,-1.]))
        self.layout_changed.emit()

    def initializeGL(self):
        try:
            self.locations.clear()
            self.uniform_values.clear()
            self.texture_size = (1, 1)
            self.texture_format = None
            self.uploaded_generations = ()
            self.has_source = False
            self.pending_image = self.video_image
            if self.desktop:
                self.desktop.last_sequence = 0
            folder = Path(__file__).with_name('shaders')
            self.program = compileProgram(
                compileShader((folder/'scene.vert.glsl').read_text(), GL.GL_VERTEX_SHADER),
                compileShader((folder/'scene.frag.glsl').read_text(), GL.GL_FRAGMENT_SHADER))
            self.vao = GL.glGenVertexArrays(1)
            self.texture = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
            for name, value in [(GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                                (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)]:
                GL.glTexParameteri(GL.GL_TEXTURE_2D, name, value)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, 1, 1, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, bytes(4))
            self.context().aboutToBeDestroyed.connect(self.cleanup)
        except Exception as e:
            self.gl_error = str(e)
            QTimer.singleShot(0, lambda: self.problem.emit('OpenGL 3.3 initialization failed: '+self.gl_error))

    def cleanup(self):
        self.makeCurrent()
        if self.texture:
            GL.glDeleteTextures([self.texture])
            self.texture = None
        if self.vao:
            GL.glDeleteVertexArrays(1, [self.vao])
            self.vao = None
        if self.program:
            GL.glDeleteProgram(self.program)
            self.program = None
        self.doneCurrent()

    def uniform(self, name, function, *values):
        previous = self.uniform_values.get(name)
        if previous is not None and len(previous) == len(values) and all(
                old is new if isinstance(new,np.ndarray) else old == new for old,new in zip(previous,values)):
            return
        if name not in self.locations:
            self.locations[name] = GL.glGetUniformLocation(self.program, name)
        function(self.locations[name], *values)
        self.uniform_values[name] = values

    def upload(self, data, width, height, fmt, generations=()):
        started = time.monotonic()
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        # Upload native bytes without a CPU-side BGRA -> RGBA conversion in
        # the driver. Texture sampling supplies the channel order instead.
        if self.texture_format != fmt:
            bgra = fmt == GL.GL_BGRA
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_SWIZZLE_R, GL.GL_BLUE if bgra else GL.GL_RED)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_SWIZZLE_B, GL.GL_RED if bgra else GL.GL_BLUE)
            self.texture_format = fmt
        transfer_format = GL.GL_RGBA if fmt == GL.GL_BGRA else fmt
        if self.texture_size != (width, height):
            max_size = int(GL.glGetIntegerv(GL.GL_MAX_TEXTURE_SIZE))
            if max(width,height) > max_size:
                raise RuntimeError(f'Source {width}×{height} exceeds GPU texture limit {max_size}.')
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA8, width, height, 0, transfer_format, GL.GL_UNSIGNED_BYTE, data)
            self.texture_size = width, height
        else:
            if any(generations) and self.uploaded_generations:
                # A native atlas retains unchanged screens. Borrow each changed
                # monitor using its row stride; avoid uploading the entire atlas.
                GL.glPixelStorei(GL.GL_UNPACK_ROW_LENGTH,width)
                try:
                    for i in range(self.layout.count):
                        if generations[i] != self.uploaded_generations[i]:
                            start=i*self.layout.width
                            GL.glTexSubImage2D(GL.GL_TEXTURE_2D,0,start,0,self.layout.width,height,
                                              transfer_format,GL.GL_UNSIGNED_BYTE,data[start*4:])
                finally:
                    GL.glPixelStorei(GL.GL_UNPACK_ROW_LENGTH,0)
            else:
                GL.glTexSubImage2D(GL.GL_TEXTURE_2D, 0, 0, 0, width, height, transfer_format, GL.GL_UNSIGNED_BYTE, data)
        self.uploaded_generations = tuple(generations)
        self.has_source = True
        self.upload_times_ms.append((time.monotonic()-started)*1000)

    def set_video_image(self, image):
        if not image.isNull():
            self.pending_image = upload_image(image)
            self.video_image = self.pending_image

    def resume_rendering(self):
        self.render_error = None
        self.timer.start(100)
        self.update()

    def switch_scene(self, scene):
        if self.scene == scene:
            return
        self.scene = scene
        self.uploaded_generations = ()
        self.has_source = False
        if self.desktop:
            self.desktop.last_sequence = 0

    def paintGL(self):
        paint_started = time.monotonic()
        GL.glClearColor(0, 0, 0, 1)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        if self.program is None:
            return
        GL.glUseProgram(self.program)
        GL.glBindVertexArray(self.vao)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        try:
            if self.scene != 0 and self.video_frames:
                converted = self.video_frames.take(self.video_sequence)
                if converted is not None:
                    self.video_sequence,self.pending_image = converted
                    self.video_image = self.pending_image
            if self.scene == 0 and self.desktop:
                if hasattr(self.desktop,'frame_view'):
                    with self.desktop.frame_view() as frame:
                        if frame is not None:
                            self.upload(frame,self.layout.count*self.layout.width,self.layout.height,GL.GL_BGRA,
                                        getattr(self.desktop,'frame_generations',()))
                    del frame
                else:
                    frame = self.desktop.frame()
                    if frame is not None:
                        self.upload(frame,self.layout.count*self.layout.width,self.layout.height,GL.GL_BGRA)
            elif self.scene != 0 and self.pending_image is not None:
                im, self.pending_image = self.pending_image, None
                fmt = GL.GL_BGRA if im.format() in (QImage.Format.Format_RGB32,QImage.Format.Format_ARGB32) else GL.GL_RGBA
                self.upload(im.constBits(), im.width(), im.height(), fmt)
        except Exception as e:
            self.render_error = str(e)
            self.timer.stop()
            self.problem.emit(str(e))
        self.sync_world_up()
        if self.panel_drag is not None:
            self.read_orientation()
            self.move_panel_to_pointer(self.panel_drag_position)
        ratio = self.devicePixelRatioF()
        width, height = max(1, round(self.width()*ratio)), max(1, round(self.height()*ratio))
        GL.glViewport(0,0,width,height)
        self.uniform('source', GL.glUniform1i, 0)
        self.uniform('sharpText', GL.glUniform1i, int(self.sharp_text))
        self.uniform('resolution', GL.glUniform2f, width, height)
        self.uniform('textureSizePx', GL.glUniform2f, *self.texture_size)
        self.uniform('fovY', GL.glUniform1f, self.fov)
        self.uniform('stereo', GL.glUniform1i, self.stereo)
        self.uniform('ipd', GL.glUniform1f, .064)
        self.uniform('scene', GL.glUniform1i, self.scene)
        self.uniform('packing', GL.glUniform1i, self.packing)
        self.uniform('swapEyes', GL.glUniform1i, self.swap_eyes)
        self.uniform('screenCount', GL.glUniform1i, self.layout.count)
        arrays = self.layout.render_arrays()
        for column,name in enumerate(('panelCenters','panelRights','panelUps','panelNormals')):
            self.uniform(name+'[0]', GL.glUniform3fv, self.layout.count, arrays[column])
        self.uniform('panelSizes[0]', GL.glUniform2fv, self.layout.count, arrays[4])
        self.uniform('arranging', GL.glUniform1i, self.arranging and self.scene == 0)
        self.uniform('selectedPanel', GL.glUniform1i, self.selected_screen)
        half_size = self.layout.half_size.copy()
        if self.scene == 1 and self.has_source:
            w, h = self.texture_size
            aspect = (w/(2 if self.packing == 1 else 1))/(h/(2 if self.packing == 2 else 1))
            half_size[1] = half_size[0]/aspect
        self.uniform('panelHalfSize', GL.glUniform2f, *half_size)
        self.uniform('distanceM', GL.glUniform1f, self.layout.distance)
        self.uniform('cursor', GL.glUniform2f, *self.cursor)
        self.uniform('hasSource', GL.glUniform1i, self.has_source and not (self.scene == 0 and self.suppress_desktop))
        # Latch the newest pose after uploads and all static work, immediately before drawing.
        self.read_orientation()
        self.uniform('orientation', GL.glUniformMatrix3fv, 1, GL.GL_TRUE, self.rotation)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 3)
        GL.glBindVertexArray(0)
        GL.glUseProgram(0)
        self.frames += 1
        now = time.monotonic()
        self.cpu_ms.append((now-paint_started)*1000)
        if self.last_pose_received:
            self.pose_age_ms.append((now-self.last_pose_received)*1000)
        captured = getattr(self.desktop,'last_frame_started',0.) if self.scene == 0 else 0.
        if captured:
            self.source_age_ms.append((now-captured)*1000)
        if now-self.last_stat >= 1:
            self.fps = self.frames/(now-self.last_stat)
            self.frames, self.last_stat = 0, now

    def pointer_ray(self, position):
        width = self.width()/(2 if self.stereo else 1)
        eye = int(position.x() >= width) if self.stereo else 0
        ray = view_ray(position.x()-eye*width, position.y(), width, self.height(), self.fov, self.rotation)
        origin = self.rotation @ np.array([(eye-.5)*.064,0,0]) if self.stereo else None
        return ray,origin

    def pointer(self, position):
        if not self.desktop or self.scene != 0 or self.arranging:
            return False
        if getattr(self.desktop, 'native', False):
            return False
        ray,origin = self.pointer_ray(position)
        hit = self.layout.hit(ray, origin)
        if hit:
            self.cursor = hit
            self.desktop.command(type='motion', x=hit[0], y=hit[1])
            return True
        return False

    def mousePressEvent(self, e):
        self.setFocus()
        if self.arranging and self.scene == 0 and e.button() == Qt.MouseButton.LeftButton:
            ray,origin = self.pointer_ray(e.position())
            hit = self.layout.hit(ray,origin)
            if hit:
                self.selected_screen = hit[0]//self.layout.width
                panel = self.layout.placement(self.selected_screen)
                azimuth = math.degrees(math.atan2(ray[0],-ray[2]))
                elevation = math.degrees(math.asin(np.clip(ray[1],-1,1)))
                self.panel_drag = (panel.azimuth-azimuth,panel.elevation-elevation)
                self.panel_drag_position = e.position()
                self.screen_selected.emit(self.selected_screen)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self.mouse_look and e.button() == Qt.MouseButton.RightButton:
            self.drag = e.position()
        elif self.desktop and getattr(self.desktop, 'native', False) and self.scene == 0:
            # A deliberate click transfers the actual pointer to the chosen monitor.
            # Hover never warps it; all subsequent input belongs to the host apps.
            ray,origin = self.pointer_ray(e.position())
            hit = self.layout.hit(ray, origin)
            if hit:
                self.desktop.command(type='focus_at',x=hit[0],y=hit[1])
        elif self.pointer(e.position()):
            button = {Qt.MouseButton.LeftButton:1, Qt.MouseButton.MiddleButton:2, Qt.MouseButton.RightButton:3}.get(e.button())
            if button:
                self.desktop.command(type='button', code=button, down=True)

    def mouseMoveEvent(self, e):
        if self.panel_drag is not None:
            self.panel_drag_position = e.position()
            self.move_panel_to_pointer(e.position())
        elif self.drag is not None:
            delta, self.drag = e.position()-self.drag, e.position()
            self.yaw -= delta.x()*.004
            self.pitch = max(-math.pi/2, min(math.pi/2, self.pitch-delta.y()*.004))
        else:
            self.pointer(e.position())

    def move_panel_to_pointer(self, position):
        ray,_ = self.pointer_ray(position)
        azimuth = (math.degrees(math.atan2(ray[0],-ray[2]))+self.panel_drag[0]+180)%360-180
        elevation = float(np.clip(math.degrees(math.asin(np.clip(ray[1],-1,1)))+self.panel_drag[1],-80,80))
        panel = self.layout.placement(self.selected_screen)
        if abs(panel.azimuth-azimuth)>1e-7 or abs(panel.elevation-elevation)>1e-7:
            self.layout.update_panel(self.selected_screen,azimuth=azimuth,elevation=elevation)
            self.layout_changed.emit()

    def mouseReleaseEvent(self, e):
        if self.arranging:
            if e.button() == Qt.MouseButton.LeftButton:
                self.panel_drag = None
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            elif e.button() == Qt.MouseButton.RightButton:
                self.drag = None
            return
        if self.drag is not None and e.button() == Qt.MouseButton.RightButton:
            self.drag = None
        elif self.desktop and self.scene == 0:
            button = {Qt.MouseButton.LeftButton:1, Qt.MouseButton.MiddleButton:2, Qt.MouseButton.RightButton:3}.get(e.button())
            if button:
                self.desktop.command(type='button', code=button, down=False)

    def wheelEvent(self, e):
        if self.arranging and self.scene == 0:
            panel = self.layout.placement(self.selected_screen)
            steps = e.angleDelta().y()/120
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.layout.update_panel(self.selected_screen,scale=float(np.clip(panel.scale*math.exp(.08*steps),.25,3)))
            else:
                self.layout.update_panel(self.selected_screen,distance=float(np.clip(panel.distance-.15*steps,.5,10)))
            self.layout_changed.emit()
            return
        if self.pointer(e.position()):
            code = 4 if e.angleDelta().y() > 0 else 5
            for _ in range(max(1, abs(e.angleDelta().y())//120)):
                self.desktop.command(type='button', code=code, down=True)
                self.desktop.command(type='button', code=code, down=False)

    def release_input(self):
        if self.desktop:
            self.desktop.command(type='release')

    def focusOutEvent(self, e):
        self.release_input()
        self.drag = None
        self.panel_drag = None
        if self.arranging:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        if self.arranging and e.key() in (Qt.Key.Key_Escape,Qt.Key.Key_Return,Qt.Key.Key_Enter):
            self.edit_finished.emit(e.key() != Qt.Key.Key_Escape)
            return
        modifiers = e.modifiers()
        special = modifiers & Qt.KeyboardModifier.ControlModifier and modifiers & Qt.KeyboardModifier.AltModifier
        if special:
            self.release_input()
            if e.key() == Qt.Key.Key_R:
                self.recenter()
            elif e.key() == Qt.Key.Key_F:
                self.fullscreen_requested.emit()
            elif self.desktop and e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                self.desktop.command(type='move', delta=-1 if e.key()==Qt.Key.Key_Left else 1)
            elif self.desktop and e.key() == Qt.Key.Key_Tab:
                self.desktop.command(type='cycle')
            return
        if e.key() == Qt.Key.Key_Escape:
            self.release_input()
            self.escape.emit()
        elif self.scene != 0 and e.key() == Qt.Key.Key_Space:
            self.play_pause.emit()
        elif self.desktop and self.scene == 0 and not self.arranging:
            code = keysym(e)
            if code:
                self.desktop.command(type='key', keysym=code, down=True)

    def keyReleaseEvent(self, e):
        if self.desktop and self.scene == 0 and not self.arranging and not e.isAutoRepeat():
            code = keysym(e)
            if code:
                self.desktop.command(type='key', keysym=code, down=False)
