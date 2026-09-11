from pathlib import Path
import json
import shlex
import shutil
import sys
import queue
from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal, QSettings
from PySide6.QtGui import QShortcut, QKeySequence, QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QSlider, QDoubleSpinBox, QFileDialog,
    QLineEdit, QTabWidget, QFormLayout, QScrollArea, QMenu, QInputDialog)
from .hyprland import create_desktop, PREFIX
from .renderer import Viewer
from .tracking import VitureTracker, library_path
from .layout_editor import LayoutEditor
from .video import VideoFrames
from .geometry import Layout, IDENTITY, multiply, axis_angle


STYLE = '''
QWidget { color: #dedee3; background: #151517; font-family: "Inter", "Noto Sans", sans-serif; font-size: 13px; }
QMainWindow { background: #000; }
QWidget#toolbar { background: #151517; border-bottom: 1px solid #26262a; }
QWidget#drawer { background: #151517; border-left: 1px solid #2b2b30; }
QWidget#navigation { background: #222225; border: 1px solid #2c2c31; border-radius: 9px; }
QLabel { background: transparent; }
QLabel#brand { color: #fafafa; font-size: 16px; font-weight: 600; margin-right: 18px; }
QLabel#muted { color: #9b9ba5; font-size: 12px; }
QLabel#status { color: #a5a5ae; font-size: 11px; padding: 5px 9px; border: 1px solid #303036; border-radius: 11px; }
QLabel#sectionTitle { color: #f2f2f4; font-size: 19px; font-weight: 600; }
QLabel#eyebrow { color: #8c8c98; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel#divider { color: #35353c; padding: 0 8px; }
QPushButton { background: #252529; border: 1px solid #35353c; border-radius: 7px; padding: 8px 12px; }
QPushButton:hover { background: #303036; border-color: #494951; color: #fff; }
QPushButton:pressed { background: #3a3a42; }
QPushButton:focus { border-color: #b7b7c6; }
QPushButton:checked { background: #34343b; color: #fff; border-color: #474750; }
QPushButton:disabled { color: #85858e; border-color: #2c2c31; background: #202024; }
QPushButton#primary { background: #ededf1; border-color: #ededf1; color: #17171b; font-weight: 600; }
QPushButton#primary:hover { background: #fff; border-color: #fff; }
QPushButton#primary:pressed { background: #ceced8; }
QPushButton#quiet { border-color: transparent; background: transparent; color: #a9a9b3; }
QPushButton#quiet:hover { background: #29292e; color: #fff; }
QPushButton#quiet:checked { background: #3a3a42; color: #fafafa; }
QPushButton#quiet:focus { border-color: #858592; }
QWidget#navigation QPushButton { padding: 6px 14px; border-radius: 6px; font-size: 12px; }
QPushButton#closeDrawer { background: transparent; color: #9b9ba5; border: 0; border-radius: 6px; font-size: 20px; padding: 0; }
QPushButton#closeDrawer:hover { background: #303036; color: #fff; }
QMenu { background: #202024; padding: 6px; border: 1px solid #3b3b43; border-radius: 8px; }
QMenu::item { padding: 9px 24px; border-radius: 5px; }
QMenu::item:selected { background: #37373f; }
QMenu::separator { height: 1px; background: #34343b; margin: 5px 8px; }
QLineEdit, QComboBox, QDoubleSpinBox { padding: 8px 10px; background: #111114; border: 1px solid #36363e; border-radius: 6px; selection-background-color: #51515f; }
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus { border-color: #9292a2; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox::down-arrow { image: url(@ICONS@/chevron-down.svg); width: 12px; height: 12px; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 22px; border: 0; background: transparent; }
QDoubleSpinBox::up-arrow { image: url(@ICONS@/chevron-up.svg); width: 10px; height: 10px; }
QDoubleSpinBox::down-arrow { image: url(@ICONS@/chevron-down.svg); width: 10px; height: 10px; }
QComboBox QAbstractItemView { background: #232328; color: #e6e6ec; selection-background-color: #3c3c46; border: 1px solid #454550; padding: 4px; }
QTabWidget::pane { border: 0; }
QTabBar::tab { padding: 11px 16px; color: #94949f; border-bottom: 2px solid #303036; font-size: 12px; }
QTabBar::tab:selected { color: #f4f4f7; border-bottom-color: #d5d5df; }
QTabBar::tab:hover { color: #fff; }
QSlider::groove:horizontal { height: 3px; background: #3e3e48; border-radius: 1px; }
QSlider::sub-page:horizontal { background: #b5b5c4; border-radius: 1px; }
QSlider::handle:horizontal { background: #e8e8ef; border: 1px solid #151517; width: 12px; margin: -5px 0; border-radius: 7px; }
QSlider::handle:horizontal:hover { background: #fff; }
QCheckBox { spacing: 10px; padding: 5px 0; }
QCheckBox::indicator { width: 15px; height: 15px; }
QScrollArea { border: 0; }
QScrollBar:vertical { background: transparent; width: 5px; margin: 2px 0; }
QScrollBar::handle:vertical { background: #44444e; border-radius: 2px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { color: #ececf0; background: #2a2a31; border: 1px solid #484853; padding: 6px; }
'''



class Job(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.ready.emit(self.fn())
        except Exception as e:
            self.failed.emit(str(e))


def note(text):
    label = QLabel(text)
    label.setObjectName('muted')
    label.setWordWrap(True)
    return label


def button(text, fn, primary=False):
    b = QPushButton(text)
    b.clicked.connect(fn)
    if primary:
        b.setObjectName('primary')
    return b


class MainWindow(QMainWindow):
    def __init__(self, args, layout):
        super().__init__()
        self.args, self.layout = args, layout
        self.desktop = self.tracker = None
        self.browser_video = None
        self.browser_moving = False
        self.browser_had_client = False
        self.browser_timer = QTimer(self)
        self.browser_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.browser_timer.setInterval(8)
        self.browser_timer.timeout.connect(self.update_browser_video)
        self.jobs = []
        self.closing = False
        self.tracking_busy = self.desktop_busy = False
        self.disconnect_requested = False
        self.sdk = args.sdk
        self.settings = QSettings('SpacewalkerLinux', 'Spacewalker')
        self.multiple_count = layout.count if layout.count>1 else 3
        self.monitor_resolution = (layout.width,layout.height)
        remembered_mode = self.settings.value('screen_mode','multiple',type=str) if self.remember_settings else 'multiple'
        self.screen_mode = args.mode or ('single' if args.source or layout.count==1 else
                                        'multiple' if args.screens else remembered_mode)
        if self.screen_mode not in ('single','multiple'):
            self.screen_mode = 'multiple'
        if self.remember_settings and args.screens is None:
            self.multiple_count = max(2,min(5,self.settings.value('multiple_count',self.multiple_count,type=int)))
        self.single_source = args.source if args.source is not None else (
            '' if args.screens==1 else self.settings.value('single_source','',type=str)
            if self.remember_settings else '')
        self.layout_cache = {}
        if self.screen_mode == 'single' and layout.count != 1:
            self.layout = layout = Layout(1,layout.width,layout.height)
        elif self.screen_mode == 'multiple' and layout.count != self.multiple_count:
            self.layout = layout = Layout(self.multiple_count,layout.width,layout.height)
        self.glasses_fov = 26.
        self.preview_fov = 55.
        self.layout_snapshot = None
        self.setWindowTitle('Spacewalker')
        self.resize(1380, 850)
        self.setStyleSheet(STYLE.replace('@ICONS@',Path(__file__).with_name('icons').as_uri()))
        central = QWidget()
        self.setCentralWidget(central)
        column = QVBoxLayout(central)
        column.setContentsMargins(0,0,0,0)
        column.setSpacing(0)
        self.toolbar = QWidget()
        self.toolbar.setObjectName('toolbar')
        tools = QHBoxLayout(self.toolbar)
        tools.setContentsMargins(22,12,22,12)
        tools.setSpacing(8)
        brand = QLabel('Spacewalker')
        brand.setObjectName('brand')
        tools.addWidget(brand)
        navigation = QWidget()
        navigation.setObjectName('navigation')
        navigation_layout = QHBoxLayout(navigation)
        navigation_layout.setContentsMargins(3,3,3,3)
        navigation_layout.setSpacing(2)
        self.workspace_button = button('Workspace', self.show_desktop)
        self.workspace_button.setObjectName('quiet')
        self.workspace_button.setCheckable(True)
        self.workspace_button.setChecked(True)
        navigation_layout.addWidget(self.workspace_button)
        self.video_button = button('Video', self.show_video_controls)
        self.video_button.setObjectName('quiet')
        self.video_button.setCheckable(True)
        navigation_layout.addWidget(self.video_button)
        tools.addWidget(navigation)
        tools.addSpacing(8)
        open_button = QPushButton('Open')
        open_menu = QMenu(open_button)
        open_menu.addAction('Terminal', self.launch_terminal)
        open_menu.addAction('Application…', self.prompt_application)
        open_menu.addAction('Existing window…', self.choose_existing_window)
        open_menu.addAction('Note', self.launch_note)
        open_menu.addSeparator()
        open_menu.addAction('Video…', self.choose_video)
        open_menu.addAction('Browser 360…', self.open_browser_video)
        open_button.setMenu(open_menu)
        tools.addWidget(open_button)
        self.arrange_button = button('Arrange',self.toggle_arrange)
        self.arrange_button.setCheckable(True)
        self.arrange_button.setObjectName('quiet')
        tools.addWidget(self.arrange_button)
        tools.addStretch()
        self.tracking_status = QLabel('Mouse preview')
        self.tracking_status.setObjectName('status')
        self.tracking_status.setMinimumWidth(80)
        tools.addWidget(self.tracking_status)
        tools.addSpacing(8)
        recenter_button = button('Recenter', lambda: self.viewer.recenter())
        recenter_button.setObjectName('quiet')
        tools.addWidget(recenter_button)
        self.settings_button = button('Settings', self.toggle_controls)
        self.settings_button.setCheckable(True)
        self.settings_button.setObjectName('quiet')
        tools.addWidget(self.settings_button)
        tools.addWidget(button('Glasses view', self.enter_immersive, True))
        column.addWidget(self.toolbar)
        content = QWidget()
        row = QHBoxLayout(content)
        row.setContentsMargins(0,0,0,0)
        row.setSpacing(0)
        column.addWidget(content, 1)
        self.controls = QWidget()
        self.controls.setObjectName('drawer')
        self.controls.setFixedWidth(336)
        side = QVBoxLayout(self.controls)
        side.setContentsMargins(22,22,18,20)
        side.setSpacing(16)
        drawer_header = QHBoxLayout()
        drawer_title = QLabel('Settings')
        drawer_title.setObjectName('sectionTitle')
        drawer_header.addWidget(drawer_title)
        drawer_header.addStretch()
        close_drawer = button('×',lambda:self.set_controls_visible(False))
        close_drawer.setObjectName('closeDrawer')
        close_drawer.setAccessibleName('Close settings')
        close_drawer.setToolTip('Close settings')
        close_drawer.setFixedSize(28,28)
        drawer_header.addWidget(close_drawer)
        side.addLayout(drawer_header)
        self.tabs = QTabWidget()
        side.addWidget(self.tabs, 1)
        self.arrange_actions = QWidget()
        actions = QHBoxLayout(self.arrange_actions)
        actions.setContentsMargins(0,8,0,8)
        actions.addWidget(button('Cancel',lambda: self.end_arrange(False)))
        actions.addWidget(button('Done',lambda: self.end_arrange(True),True))
        side.addWidget(self.arrange_actions)
        self.arrange_actions.hide()
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0,0,0,0)
        right_layout.setSpacing(0)
        self.viewer = Viewer(layout)
        self.native_controls_timer = QTimer(self)
        self.native_controls_timer.setInterval(25)
        self.native_controls_timer.timeout.connect(self.native_actions)
        self.native_controls_timer.start()
        self.viewer.problem.connect(self.render_problem)
        self.viewer.escape.connect(self.leave_immersive)
        self.viewer.fullscreen_requested.connect(self.toggle_immersive)
        self.viewer.recentered.connect(lambda: self.message.setText('Centered.'))
        self.viewer.play_pause.connect(self.toggle_play)
        self.viewer.screen_selected.connect(self.select_display)
        self.viewer.layout_changed.connect(self.refresh_layout_editor)
        self.viewer.edit_finished.connect(self.end_arrange)
        right_layout.addWidget(self.viewer, 1)
        self.footer = QWidget()
        footer_layout = QVBoxLayout(self.footer)
        footer_layout.setContentsMargins(22,10,22,12)
        self.message = QLabel('Open a video or start your workspace.' if args.no_desktop else 'Connecting monitors to your desktop…')
        self.message.setWordWrap(True)
        self.message.setMaximumHeight(42)
        self.message.setObjectName('muted')
        self.stats = QLabel('')
        self.stats.setWordWrap(True)
        self.stats.setObjectName('muted')
        footer_layout.addWidget(self.message)
        right_layout.addWidget(self.footer)
        row.addWidget(right, 1)
        row.addWidget(self.controls)
        self.controls.hide()
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(.7)
        self.player.setAudioOutput(self.audio)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.video_frames = VideoFrames()
        self.viewer.video_frames = self.video_frames
        self.sink.videoFrameChanged.connect(self.video_frame)
        self.player.errorOccurred.connect(lambda *a: self.problem('Video: '+self.player.errorString()))
        self.build_desktop_tab()
        self.build_video_tab()
        self.build_view_tab()
        self.display_combo = QComboBox()
        self.refresh_screens()
        self.display_combo.currentIndexChanged.connect(self.refresh_sources)
        QApplication.instance().screenAdded.connect(lambda *_: self.refresh_screens())
        QApplication.instance().screenRemoved.connect(lambda *_: self.refresh_screens())
        self.output_controls = QWidget()
        output_box = QVBoxLayout(self.output_controls)
        output_box.setContentsMargins(0,0,0,0)
        output_title = QLabel('OUTPUT DISPLAY')
        output_title.setObjectName('eyebrow')
        output_box.addWidget(output_title)
        output_box.addWidget(self.display_combo)
        output_box.addWidget(note('Esc  Controls      Ctrl+Alt+R  Recenter'))
        side.addWidget(self.output_controls)
        for key, fn in [('Ctrl+Alt+R', self.viewer.recenter), ('Ctrl+Alt+F', self.toggle_immersive),
                        ('Ctrl+Alt+A', self.toggle_arrange),
                        ('Ctrl+Alt+Tab', lambda: self.desktop_command(type='cycle')),
                        ('Ctrl+Alt+Left', lambda: self.desktop_command(type='move', delta=-1)),
                        ('Ctrl+Alt+Right', lambda: self.desktop_command(type='move', delta=1))]:
            shortcut = QShortcut(QKeySequence(key), self)
            def activate(fn=fn):
                self.viewer.release_input()
                fn()
            shortcut.activated.connect(activate)
        if not args.demo and not args.smoke_seconds and not args.profile_seconds:
            self.glasses_fov_control.setValue(self.settings.value('glasses_fov', 26., type=float))
            self.fov.setValue(self.settings.value('preview_fov', 55., type=float))
            self.panel_size.setValue(self.settings.value('screen_degrees', 44., type=float))
            self.screen_gap.setValue(self.settings.value('gap_degrees', 3., type=float))
            self.smoothing.setValue(self.settings.value('smoothing_ms', 0., type=float))
            self.anchor.setChecked(self.settings.value('anchored', True, type=bool))
            self.sharp_text.setChecked(self.settings.value('sharp_text', True, type=bool))
            if not self.sdk:
                self.sdk = self.settings.value('sdk', '', type=str) or None
            self.restore_monitor_layout()
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(500)
        if args.web_video:
            QTimer.singleShot(100,lambda:self.open_browser_video(args.web_video))
        elif args.video:
            QTimer.singleShot(100, lambda: self.open_video(args.video))
        elif not args.no_desktop:
            QTimer.singleShot(100, self.start_desktop)
        if not args.demo:
            try:
                self.sdk = library_path(self.sdk)
                self.sdk_edit.setText(self.sdk)
                QTimer.singleShot(250, self.connect_tracking)
            except RuntimeError:
                pass

    def tab(self, name):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        box = QVBoxLayout(page)
        box.setContentsMargins(0,20,6,12)
        box.setSpacing(14)
        self.tabs.addTab(scroll, name)
        return box

    def set_controls_visible(self, visible):
        self.controls.setVisible(visible)
        self.settings_button.setChecked(visible)

    def toggle_controls(self):
        self.set_controls_visible(not self.controls.isVisible())

    def show_video_controls(self):
        if self.viewer.arranging:
            self.end_arrange(True)
        self.tabs.setCurrentIndex(1)
        self.set_controls_visible(True)
        self.video_mode()

    def prompt_application(self):
        command, ok = QInputDialog.getText(self, 'Open application', 'Application command',
                                          text=self.command_edit.text())
        if ok and command.strip():
            self.command_edit.setText(command.strip())
            self.launch_command()

    def launch_note(self):
        if not self.desktop:
            self.problem('Wait for the workspace to start, then open a note.')
            return
        self.show_desktop()
        self.desktop.launch([sys.executable, '-m', 'spacewalker.workspace_home', '1'])

    def build_desktop_tab(self):
        box = self.tab('Displays')
        box.addWidget(QLabel('Number of monitors'))
        self.count_combo = QComboBox()
        self.count_combo.setAccessibleName('Number of monitors')
        for count in range(1,6):
            self.count_combo.addItem(str(count),count)
        self.count_combo.activated.connect(lambda:self.change_monitor_count(self.count_combo.currentData()))
        box.addWidget(self.count_combo)
        self.source_label = QLabel('Source')
        self.source_combo = QComboBox()
        self.source_combo.activated.connect(self.change_source)
        box.addWidget(self.source_label)
        box.addWidget(self.source_combo)
        self.display_summary = QLabel('')
        box.addWidget(self.display_summary)
        self.update_mode_controls()
        self.arrange_entry = button('Arrange displays',self.begin_arrange,True)
        box.addWidget(self.arrange_entry)
        self.layout_editor = LayoutEditor(self.layout)
        self.layout_editor.selected.connect(self.select_display)
        self.layout_editor.changed.connect(self.viewer.update)
        self.layout_editor.place_here.connect(self.viewer.place_selected_here)
        self.layout_editor.move_app_here.connect(lambda: self.desktop_command(
            type='move_to',screen=self.layout_editor.selected_screen))
        box.addWidget(self.layout_editor)
        self.layout_editor.hide()
        self.workspace_actions = QWidget()
        workspace_box = QVBoxLayout(self.workspace_actions)
        workspace_box.setContentsMargins(0,0,0,0)
        workspace_box.setSpacing(12)
        box.addWidget(self.workspace_actions)
        self.start_button = button('Start workspace', self.start_desktop)
        workspace_box.addWidget(self.start_button)
        workspace_box.addWidget(button('Show workspace', self.show_desktop))
        self.command_edit = QLineEdit(self)
        self.command_edit.hide()
        self.command_edit.setPlaceholderText('e.g. firefox --no-remote')
        self.command_edit.returnPressed.connect(self.launch_command)
        self.command_edit.setToolTip('Open an application on the XR monitors.')
        self.existing_window_button = button('Move an existing window…', self.choose_existing_window)
        workspace_box.addWidget(self.existing_window_button)
        workspace_box.addWidget(button('Next window', lambda: self.desktop_command(type='cycle')))
        moves = QHBoxLayout()
        moves.addWidget(button('Move left', lambda: self.desktop_command(type='move', delta=-1)))
        moves.addWidget(button('Move right', lambda: self.desktop_command(type='move', delta=1)))
        workspace_box.addLayout(moves)
        self.monitor_help = note('Native monitors share your desktop’s applications, mouse and keyboard.')
        workspace_box.addWidget(self.monitor_help)
        box.addStretch()

    @property
    def remember_settings(self):
        return not self.args.demo and not self.args.smoke_seconds and not self.args.profile_seconds

    def update_mode_controls(self):
        self.count_combo.setCurrentIndex(self.count_combo.findData(self.layout.count))
        self.source_label.setVisible(self.screen_mode == 'single')
        self.source_combo.setVisible(self.screen_mode == 'single')
        self.display_summary.setText(f'{self.layout.count} screen'+('s' if self.layout.count!=1 else '')+
                                     f' · {self.layout.width} × {self.layout.height}')

    def refresh_sources(self):
        if not hasattr(self,'display_combo'):
            return
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem('Separate monitor','')
        screens = [s for s in QApplication.screens() if not s.name().startswith(PREFIX)
                   and s.name()!=self.display_combo.currentData()]
        if self.args.desktop_backend != 'private':
            for screen in screens:
                self.source_combo.addItem('Mirror '+screen.name(),screen.name())
        if self.single_source == 'auto':
            self.single_source = self.source_combo.itemData(1) if self.source_combo.count()>1 else ''
        index = self.source_combo.findData(self.single_source)
        if index<0:
            self.source_combo.addItem('Unavailable: '+self.single_source,self.single_source)
            index = self.source_combo.count()-1
        self.source_combo.setCurrentIndex(index)
        self.source_combo.blockSignals(False)
        self.update_mirror_preview()

    def change_source(self):
        source = self.source_combo.currentData()
        if source != self.single_source:
            self.change_workspace('single',source)

    def replace_layout(self,layout):
        self.layout = self.viewer.layout = layout
        self.layout_editor.set_layout(layout)
        self.viewer.selected_screen = layout.count//2
        cached = self.layout_cache.get(self.layout_settings_key)
        if cached:
            layout.restore(cached)
        elif self.remember_settings:
            self.restore_monitor_layout()
        self.layout_editor.refresh()
        self.update_mode_controls()
        self.viewer.update()

    def change_monitor_count(self,count):
        self.change_workspace('single' if count==1 else 'multiple',count=count)

    def change_workspace(self,mode,source=None,count=None):
        if self.desktop_busy or self.closing:
            self.update_mode_controls()
            self.refresh_sources()
            return
        count = count if count is not None else (1 if mode=='single' else self.multiple_count)
        if mode==self.screen_mode and count==self.layout.count and (source is None or source==self.single_source):
            return
        if self.desktop and not self.desktop.native:
            self.update_mode_controls()
            self.refresh_sources()
            self.problem('Choose the monitor count before starting a private X11 workspace. Live switching requires native Hyprland monitors.')
            return
        try:
            new_layout = Layout(count,*self.monitor_resolution,self.layout.distance,
                                self.layout.screen_degrees,self.layout.gap_degrees)
        except ValueError as e:
            self.update_mode_controls()
            self.problem(str(e))
            return
        self.stop_browser_video()
        if self.viewer.arranging:
            self.end_arrange(True)
        self.save_monitor_layout()
        old = self.desktop
        self.viewer.release_input()
        self.desktop = self.viewer.desktop = None
        self.viewer.has_source = False
        self.viewer.uploaded_generations = ()
        self.viewer.render_error = None
        self.viewer.timer.start(100)
        self.viewer.suppress_desktop = False
        self.player.pause()
        self.viewer.switch_scene(0)
        self.screen_mode = mode
        if count>1:
            self.multiple_count = count
        if mode == 'single':
            self.anchor.setChecked(True)
        if source is not None:
            self.single_source = source
        self.replace_layout(new_layout)
        self.workspace_button.setChecked(True)
        self.video_button.setChecked(False)
        def detached(_=None):
            self.desktop_busy = False
            if not self.closing:
                self.start_desktop()
        if old:
            self.desktop_busy = True
            self.set_desktop_controls_enabled(False)
            self.message.setText('Switching screens…')
            def detach_failed(message):
                self.desktop_busy = False
                self.set_desktop_controls_enabled(True)
                self.start_button.setEnabled(True)
                self.problem(message)
            self.run_job(old.close,detached,detach_failed)
        else:
            detached()

    def set_desktop_controls_enabled(self,enabled):
        can_switch = enabled and (not self.desktop or self.desktop.native)
        self.count_combo.setEnabled(can_switch)
        self.source_combo.setEnabled(can_switch)
        self.arrange_button.setEnabled(enabled)
        self.arrange_entry.setEnabled(enabled)

    def showEvent(self,event):
        super().showEvent(event)
        if not getattr(self,'screen_signal_connected',False) and self.windowHandle():
            self.windowHandle().screenChanged.connect(self.update_mirror_preview)
            self.screen_signal_connected = True
        self.update_mirror_preview()

    def update_mirror_preview(self):
        if not hasattr(self,'viewer'):
            return
        source = getattr(self.desktop,'source',None)
        screen = self.windowHandle().screen() if self.windowHandle() else None
        # Never recursively render a capture of the viewer onto its own source.
        self.viewer.suppress_desktop = bool(source and screen and screen.name()==source)
        self.viewer.update()

    def choose_existing_window(self):
        if not self.desktop or not self.desktop.native:
            self.problem('Existing windows require native monitors. Start with --desktop-backend hyprland.')
            return
        try:
            windows = self.desktop.windows()
            if not windows:
                self.message.setText('No other windows are open.')
                return
            labels = [f'{i+1}. {w["title"][:100]} · {w.get("class", "")}' for i,w in enumerate(windows)]
            selected, accepted = QInputDialog.getItem(self, 'Move an existing window', 'Window', labels, 0, False)
            if not accepted:
                return
            choices = [f'Monitor {i+1}' for i in range(self.layout.count)]
            target, accepted = QInputDialog.getItem(self, 'Choose monitor', 'Place window on', choices,
                                                    self.viewer.selected_screen, False)
            if accepted:
                self.desktop.command(type='move_to',screen=choices.index(target),address=windows[labels.index(selected)]['address'])
                self.message.setText(f'Window moved to {target.lower()}. Click that monitor to move your pointer there.')
        except (OSError, RuntimeError) as e:
            self.problem(str(e))

    def native_actions(self):
        if not self.desktop or not getattr(self.desktop, 'native', False):
            return
        for action in self.desktop.poll_actions():
            if action == 'recenter':
                self.viewer.recenter()
            elif action == 'fullscreen':
                self.toggle_immersive()
            elif action == 'arrange':
                self.leave_immersive()
                self.raise_()
                self.activateWindow()
                self.toggle_arrange()
                self.desktop.command(type='focus_viewer')
            elif action == 'controls':
                self.leave_immersive()
                self.raise_()
                self.activateWindow()
                self.desktop.command(type='focus_viewer')
            elif action.startswith('move:'):
                self.desktop.command(type='move_to',screen=int(action.split(':')[1]))
            elif action == 'diagnostics':
                report = self.viewer.performance_report()
                report.update(layout=self.layout.to_dict(),texture_size=self.viewer.texture_size,
                              viewer_size=[self.viewer.width(),self.viewer.height()],
                              fullscreen=self.isFullScreen(),sharp_text=self.viewer.sharp_text,
                              tracking_connected=bool(self.tracker),fov=self.viewer.fov,
                              view_rotation=self.viewer.rotation.tolist(),world_up=list(self.layout.world_up),
                              anchored=self.viewer.anchored,stereo=self.viewer.stereo,
                              gl_error=self.viewer.gl_error,render_error=self.viewer.render_error)
                Path(self.desktop.temp.name,'diagnostics.json').write_text(json.dumps(report,indent=2)+'\n')

    def begin_arrange(self):
        if self.viewer.arranging:
            return
        self.show_desktop()
        self.layout_snapshot = self.layout.to_dict()
        self.viewer.set_arranging(True)
        self.arrange_button.setChecked(True)
        self.arrange_entry.hide()
        self.workspace_actions.hide()
        self.arrange_actions.show()
        self.output_controls.hide()
        self.layout_editor.show()
        self.layout_editor.refresh()
        if not self.isFullScreen():
            self.set_controls_visible(True)
        self.message.setText('Drag a display to place it. Scroll for distance. Enter to finish; Esc to cancel.')

    def toggle_arrange(self):
        self.end_arrange(True) if self.viewer.arranging else self.begin_arrange()

    def select_display(self,index):
        self.viewer.selected_screen = index
        if self.layout_editor.selected_screen != index:
            self.layout_editor.select(index)

    def refresh_layout_editor(self):
        self.layout_editor.refresh()

    def end_arrange(self,apply=True):
        if not self.viewer.arranging:
            return
        if not apply and self.layout_snapshot is not None:
            self.layout.restore(self.layout_snapshot)
        self.viewer.set_arranging(False)
        self.layout_snapshot = None
        self.arrange_button.setChecked(False)
        self.layout_editor.hide()
        self.arrange_entry.show()
        self.workspace_actions.show()
        self.arrange_actions.hide()
        self.output_controls.show()
        self.set_controls_visible(False)
        self.layout_editor.refresh()
        if apply:
            self.save_monitor_layout()
        self.message.setText('Displays placed.' if apply else 'Arrangement restored.')
        self.viewer.setFocus()

    @property
    def layout_settings_key(self):
        return f'layouts/{self.layout.count}-{self.layout.width}x{self.layout.height}'

    def save_monitor_layout(self):
        self.layout_cache[self.layout_settings_key] = self.layout.to_dict()
        if not self.args.demo and not self.args.smoke_seconds and not self.args.profile_seconds:
            self.settings.setValue(self.layout_settings_key,json.dumps(self.layout.to_dict()))
            self.settings.sync()

    def restore_monitor_layout(self):
        saved = self.settings.value(self.layout_settings_key,'',type=str)
        # Preserve placement when upgrading the original 720p default to Full HD.
        if not saved and (self.layout.width,self.layout.height)==(1920,1080):
            previous = self.settings.value(f'layouts/{self.layout.count}-1280x720','',type=str)
            if previous:
                try:
                    data = json.loads(previous)
                    if (data.get('width'),data.get('height')) == (1280,720):
                        data.update(width=1920,height=1080)
                        saved = json.dumps(data)
                except (ValueError,TypeError,AttributeError):
                    pass
        if saved:
            try:
                self.layout.restore(json.loads(saved))
            except (ValueError,TypeError) as e:
                self.problem(f'Could not load saved monitor positions: {e}')
        self.layout_editor.refresh()

    def build_video_tab(self):
        box = self.tab('Video')
        box.addWidget(button('Open video…', self.choose_video, True))
        box.addWidget(button('Browser 360…',self.open_browser_video))
        self.video_name = note('Local video files · playback with audio')
        box.addWidget(self.video_name)
        self.projection = QComboBox()
        self.projection.addItems(['Flat screen', 'VR180 · equirectangular', '360° · equirectangular'])
        self.projection.setCurrentIndex({'flat':0, '180':1, '360':2}[self.args.projection])
        self.projection.currentIndexChanged.connect(self.video_mode)
        box.addWidget(QLabel('Projection'))
        box.addWidget(self.projection)
        self.packing = QComboBox()
        self.packing.addItems(['Mono', 'Side by side · left/right', 'Top/bottom · left/right'])
        self.packing.setCurrentIndex({'mono':0, 'sbs':1, 'tb':2}[self.args.packing])
        self.packing.currentIndexChanged.connect(self.video_mode)
        box.addWidget(QLabel('Video eye layout'))
        box.addWidget(self.packing)
        swap = QCheckBox('Swap left and right eyes')
        swap.toggled.connect(lambda state: setattr(self.viewer, 'swap_eyes', state))
        box.addWidget(swap)
        self.play_button = button('Play / pause', self.toggle_play)
        box.addWidget(self.play_button)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0,0)
        self.seek.sliderReleased.connect(lambda: self.player.setPosition(self.seek.value()))
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(lambda value: self.seek.setRange(0, value))
        self.time_label = note('00:00 / 00:00')
        box.addWidget(self.seek)
        box.addWidget(self.time_label)
        volume = QSlider(Qt.Orientation.Horizontal)
        volume.setRange(0,100)
        volume.setValue(70)
        volume.valueChanged.connect(lambda value: self.audio.setVolume(value/100))
        box.addWidget(QLabel('Volume'))
        box.addWidget(volume)
        self.packing.setToolTip('Source eye layout. For stereo playback, also enable SBS output in View and switch the glasses to 3D.')
        self.projection.setToolTip('VR180 and 360° must be equirectangular. Fisheye projection is not supported.')
        box.addStretch()

    def build_view_tab(self):
        box = self.tab('View')
        anchor = QCheckBox('Anchor screens in space')
        self.anchor = anchor
        anchor.setChecked(True)
        anchor.toggled.connect(lambda value: setattr(self.viewer, 'anchored', value))
        box.addWidget(anchor)
        anchor.setToolTip('Keep displays fixed as you turn. Turn off to let them follow your head.')
        box.addWidget(button('Recenter here', self.viewer.recenter))
        self.sharp_text = QCheckBox('Sharper text')
        self.sharp_text.setChecked(True)
        self.sharp_text.toggled.connect(lambda value: setattr(self.viewer, 'sharp_text', value))
        self.sharp_text.setToolTip('Preserve desktop text edge contrast as head movement shifts pixels between display pixels.')
        box.addWidget(self.sharp_text)
        self.mouse = QCheckBox('Mouse preview · right-drag to look')
        self.mouse.setChecked(True)
        self.mouse.toggled.connect(lambda value: setattr(self.viewer, 'mouse_look', value))
        box.addWidget(self.mouse)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.fov = QDoubleSpinBox()
        self.fov.setRange(15,110)
        self.fov.setValue(55)
        self.fov.setSuffix('°')
        self.fov.valueChanged.connect(self.set_preview_fov)
        self.glasses_fov_control = QDoubleSpinBox()
        self.glasses_fov_control.setRange(15,60)
        self.glasses_fov_control.setValue(self.glasses_fov)
        self.glasses_fov_control.setSuffix('°')
        self.glasses_fov_control.valueChanged.connect(self.set_glasses_fov)
        form.addRow('Glasses field of view', self.glasses_fov_control)
        form.addRow('Preview field of view', self.fov)
        panel = QDoubleSpinBox()
        self.panel_size = panel
        panel.setRange(20,70)
        panel.setValue(44)
        panel.setSuffix('°')
        panel.valueChanged.connect(lambda value: setattr(self.layout, 'screen_degrees', value))
        form.addRow('Screen angular width', panel)
        self.screen_gap = QDoubleSpinBox()
        self.screen_gap.setRange(0,20)
        self.screen_gap.setValue(self.layout.gap_degrees)
        self.screen_gap.setSuffix('°')
        self.screen_gap.valueChanged.connect(lambda value: setattr(self.layout, 'gap_degrees', value))
        form.addRow('Preset screen spacing', self.screen_gap)
        self.screen_gap.setToolTip('Spacing used when choosing the Around me preset in Arrange.')
        smoothing = QDoubleSpinBox()
        self.smoothing = smoothing
        smoothing.setRange(0,100)
        smoothing.setValue(0)
        smoothing.setSuffix(' ms')
        smoothing.valueChanged.connect(lambda value: setattr(self.viewer, 'smoothing_ms', value))
        form.addRow('Tracking smoothing', smoothing)
        box.addLayout(form)
        self.glasses_fov_control.setToolTip('Vertical optical calibration used in Glasses view. Start at 26° for Pro 2; adjust only if motion has the correct axes but the wrong scale.')
        self.fov.setToolTip('Only changes the wider desktop preview. Use Glasses view for the calibrated view through the lenses.')
        smoothing.setToolTip('Reduces small movements but adds latency. Zero is the most responsive.')
        self.sbs = QCheckBox('Render SBS output (two eyes)')
        self.sbs.toggled.connect(lambda value: setattr(self.viewer, 'stereo', value))
        box.addWidget(self.sbs)
        box.addWidget(button('Switch glasses to 3D', lambda: self.set_hardware_stereo(True)))
        box.addWidget(button('Restore glasses display mode', lambda: self.set_hardware_stereo(False)))
        self.sbs.setToolTip('Requires an extended 3840 × 1080 glasses display in 3D mode.')
        box.addWidget(QLabel('VITURE tracking SDK'))
        self.sdk_edit = QLineEdit(self.sdk or '')
        self.sdk_edit.setPlaceholderText('/path/to/libglasses.so')
        box.addWidget(self.sdk_edit)
        box.addWidget(button('Select SDK library…', self.choose_sdk))
        self.connect_button = button('Connect tracking', self.connect_tracking)
        box.addWidget(self.connect_button)
        box.addWidget(button('Disconnect tracking', self.disconnect_tracking))
        box.addWidget(self.stats)
        box.addStretch()

    def set_preview_fov(self,value):
        self.preview_fov = value
        if not self.isFullScreen():
            self.viewer.fov = value

    def set_glasses_fov(self,value):
        self.glasses_fov = value
        if self.isFullScreen():
            self.viewer.fov = value

    def run_job(self, fn, ready, failed):
        job = Job(fn, self)
        self.jobs.append(job)
        job.ready.connect(ready)
        job.failed.connect(failed)
        job.finished.connect(lambda: self.job_finished(job))
        job.start()

    def job_finished(self, job):
        self.jobs.remove(job)
        job.deleteLater()
        if self.closing and not self.jobs:
            self.close()

    def start_desktop(self):
        if self.desktop or self.desktop_busy or self.closing:
            return
        self.desktop_busy = True
        self.set_desktop_controls_enabled(False)
        self.start_button.setEnabled(False)
        self.message.setText('Starting workspace…')
        layout = self.layout
        source = self.single_source if self.screen_mode=='single' else None
        def start():
            desktop = create_desktop(layout, self.args.capture_fps, self.args.desktop_backend,source=source or None)
            desktop.start()
            return desktop
        def ready(desktop):
            self.desktop_busy = False
            if desktop.layout is not self.layout:
                self.replace_layout(desktop.layout)
            self.desktop = desktop
            self.update_mirror_preview()
            self.viewer.has_source = False
            self.viewer.uploaded_generations = ()
            self.viewer.desktop = desktop
            self.viewer.resume_rendering()
            self.set_desktop_controls_enabled(True)
            self.start_button.setText('Monitors connected' if desktop.native else 'Private workspace running')
            self.existing_window_button.setVisible(desktop.native)
            if desktop.native:
                help_text = ('Your monitors are attached. Use Open → Existing window to move a window onto them. '
                             'Mouse and keyboard work as on any other monitor.')
                keys = [f'Ctrl+Alt+{s["key"]}' for s in desktop.shortcuts if s['action'].startswith('move:')]
                if keys:
                    help_text += ' Move the focused window with '+', '.join(keys)+'.'
                enabled = {s['action'] for s in desktop.shortcuts}
                if 'recenter' in enabled:
                    help_text += ' Ctrl+Alt+R recenters.'
                if 'controls' in enabled:
                    help_text += ' Ctrl+Alt+0 returns to controls.'
                self.monitor_help.setText(help_text)
                if getattr(desktop,'source',None):
                    self.start_button.setText('Desktop mirrored')
                    self.monitor_help.setText('Your existing desktop stays on '+desktop.source+
                        '. Use Glasses view to see it on one anchored screen. Recenter sets the view; Arrange changes its position and size.')
                    self.message.setText('Mirroring '+desktop.source+'. Enter Glasses view, then Ctrl+Alt+R to anchor it in front of you.')
                elif self.layout.count==1:
                    self.message.setText('Single monitor connected. Move an app here with Ctrl+Alt+1. Recenter anchors it in front of you.')
                else:
                    self.message.setText(f'{self.layout.count} monitors connected. Open → Existing window to place your apps.')
                self.command_edit.setToolTip('Launch in your existing desktop session. Applications keep running when XR monitors disconnect.')
            else:
                self.monitor_help.setText('Private X11 workspace. Open apps here; click a screen to interact.')
                self.message.setText('Private workspace running. Open an app to get started.')
        def failed(message):
            self.desktop_busy = False
            self.set_desktop_controls_enabled(True)
            self.start_button.setEnabled(True)
            self.problem(message)
        self.run_job(start, ready, failed)

    def show_desktop(self):
        self.stop_browser_video()
        self.player.pause()
        self.viewer.switch_scene(0)
        self.tabs.setCurrentIndex(0)
        self.workspace_button.setChecked(True)
        self.video_button.setChecked(False)
        if not self.desktop:
            self.start_desktop()

    def desktop_command(self, **command):
        if self.desktop:
            self.desktop.command(**command)

    def launch_command(self):
        if not self.desktop:
            self.problem('Start the workspace before launching an application.')
            return
        try:
            self.show_desktop()
            self.desktop.launch(self.command_edit.text())
            self.message.setText('Application opened. Click its monitor to move your pointer there.  ·  Ctrl+Alt+R to recenter.')
        except (OSError, ValueError, RuntimeError) as e:
            self.problem(str(e))

    def launch_terminal(self):
        if not self.desktop:
            self.problem('Start the workspace first.')
            return
        if self.desktop.native and shutil.which('gnome-terminal'):
            command = ['gnome-terminal','--window']
        elif shutil.which('xterm'):
            command = ['xterm', '-fa', 'Monospace', '-fs', '14']
        elif shutil.which('gnome-terminal') and shutil.which('dbus-run-session'):
            command = ['dbus-run-session', '--', 'gnome-terminal', '--wait']
        else:
            self.problem('Install xterm, or enter your terminal command in Launch app.')
            return
        try:
            self.show_desktop()
            self.desktop.launch(command)
            self.message.setText('Click the terminal to type.')
        except (OSError, RuntimeError) as e:
            self.problem(str(e))

    def choose_video(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open a video', '', 'Video (*.mp4 *.mkv *.webm *.mov *.avi *.m4v);;All files (*)')
        if path:
            self.open_video(path)

    def open_video(self, path):
        p = Path(path).expanduser().resolve()
        if not p.is_file():
            self.problem(f'Video file does not exist: {p}')
            return
        if self.viewer.arranging:
            self.end_arrange(True)
        self.player.stop()
        self.video_frames.reset()
        self.viewer.has_source = False
        self.viewer.pending_image = None
        self.viewer.video_image = None
        self.viewer.resume_rendering()
        self.player.setSource(QUrl.fromLocalFile(str(p)))
        self.video_name.setText(p.name)
        self.tabs.setCurrentIndex(1)
        self.set_controls_visible(True)
        self.video_mode()
        self.player.play()

    def video_frame(self,frame):
        # Keep the Qt/FFmpeg callback on the GUI thread and hand off only a reference.
        # Calling Python directly from FFmpeg's render thread can deadlock stop()/seek().
        self.video_frames.submit(frame)

    def video_mode(self):
        self.stop_browser_video()
        self.viewer.switch_scene(self.projection.currentIndex()+1)
        self.viewer.packing = self.packing.currentIndex()
        self.workspace_button.setChecked(False)
        self.video_button.setChecked(True)
        if self.viewer.video_image is not None:
            self.viewer.set_video_image(self.viewer.video_image)

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.video_mode()
            self.player.play()

    def open_browser_video(self,url=''):
        from .browser_video import BrowserVideo
        from .browser_launch import launch
        if self.viewer.arranging:
            self.end_arrange(True)
        if self.isFullScreen():
            self.leave_immersive()
        self.player.pause()
        try:
            if self.browser_video is None:
                self.browser_video = BrowserVideo()
            address = self.browser_video.url(url if isinstance(url,str) else '')
            self.browser_timer.start()
            self.update_browser_video()
            def opened(native_window):
                if not native_window and not QDesktopServices.openUrl(QUrl(address)):
                    self.problem('Could not open the browser. Check your default browser setting.')
            self.run_job(lambda:launch(address),opened,self.problem)
            self.tabs.setCurrentIndex(1)
            self.set_controls_visible(True)
            self.message.setText('Browser 360 is open. Paste a video link, choose Move to glasses, then Fullscreen and Recenter. Keep this app running.')
        except (OSError,RuntimeError) as e:
            self.problem(str(e))

    def update_browser_video(self):
        bridge = self.browser_video
        if bridge is None:
            return
        while True:
            try:
                action = bridge.commands.get_nowait()
            except queue.Empty:
                break
            if action == 'recenter':
                self.viewer.recenter()
            elif action == 'controls':
                self.leave_immersive()
                self.raise_()
                self.activateWindow()
                self.set_controls_visible(True)
                if self.desktop and self.desktop.native:
                    self.desktop.command(type='focus_viewer')
            elif action == 'glasses' and not self.browser_moving:
                from .browser_launch import move_to_output
                if self.isFullScreen():
                    self.leave_immersive()
                self.browser_moving = True
                title,output = bridge.title,self.display_combo.currentData()
                def moved(_=None):
                    self.browser_moving = False
                    self.message.setText('Browser moved to the glasses. Click Fullscreen in the browser player, then Recenter.')
                def failed(message):
                    self.browser_moving = False
                    self.problem(message)
                self.run_job(lambda:move_to_output(title,output),moved,failed)
        if bridge.clients:
            self.browser_had_client = True
            # Browser output is already projected; stop the unused desktop
            # redraw loop while it renders directly on the physical glasses.
            self.viewer.timer.stop()
        elif self.browser_had_client:
            self.viewer.timer.start(100)
            self.browser_had_client = False
        if self.tracker:
            q,age = self.tracker.pose.snapshot()
        elif self.args.demo:
            q = multiply(axis_angle([0,1,0],self.viewer.yaw),axis_angle([1,0,0],self.viewer.pitch))
            age = 0.
        else:
            q,age = IDENTITY,None
        bridge.publish(q,age,self.glasses_fov,self.viewer.stereo,simulated=self.args.demo and not self.tracker)

    def stop_browser_video(self):
        if self.browser_video:
            self.browser_timer.stop()
            self.browser_video.close()
            self.browser_video = None
            self.browser_had_client = False
            self.viewer.timer.start(100)

    def position_changed(self, position):
        if not self.seek.isSliderDown():
            self.seek.setValue(position)
        def stamp(ms):
            s = ms//1000
            return f'{s//60:02d}:{s%60:02d}'
        self.time_label.setText(f'{stamp(position)} / {stamp(self.player.duration())}')

    def choose_sdk(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Select VITURE SDK libglasses.so', '', 'VITURE SDK (libglasses.so)')
        if path:
            self.sdk_edit.setText(path)

    def connect_tracking(self):
        if self.tracker or self.tracking_busy or self.closing:
            return
        self.tracking_busy = True
        self.connect_button.setEnabled(False)
        self.tracking_status.setText('Connecting…')
        sdk = self.sdk_edit.text().strip() or None
        def connect():
            tracker = VitureTracker(sdk, self.args.pid)
            tracker.start()
            return tracker
        def ready(tracker):
            self.tracking_busy = False
            self.tracker = self.viewer.tracker = tracker
            self.mouse.setChecked(False)
            self.viewer.recenter()
            if self.disconnect_requested:
                self.disconnect_tracking()
        def failed(message):
            self.tracking_busy = False
            self.disconnect_requested = False
            self.connect_button.setEnabled(True)
            self.tracking_status.setText('Mouse preview')
            self.problem(message)
        self.run_job(connect, ready, failed)

    def disconnect_tracking(self):
        if self.tracking_busy:
            self.disconnect_requested = True
            return
        self.disconnect_requested = False
        if self.tracker:
            tracker = self.tracker
            self.tracker = self.viewer.tracker = None
            self.tracking_busy = True
            self.connect_button.setEnabled(False)
            def finished(errors=None):
                self.tracking_busy = False
                self.connect_button.setEnabled(True)
                if errors:
                    self.problem('; '.join(errors))
            def failed(message):
                finished()
                self.problem(message)
            self.run_job(tracker.close,finished,failed)
        else:
            self.connect_button.setEnabled(True)
        self.mouse.setChecked(True)
        self.tracking_status.setText('Mouse preview')

    def set_hardware_stereo(self, enabled):
        if self.tracking_busy or self.closing:
            return
        if not self.tracker:
            self.problem('Connect tracking first, or use the physical 3D switch on your glasses and enable SBS output.')
            return
        self.tracking_busy = True
        tracker = self.tracker
        self.message.setText('Changing glasses display mode…')
        def finished():
            self.tracking_busy = False
            if self.disconnect_requested:
                self.disconnect_tracking()
        def ready(_):
            self.sbs.setChecked(enabled)
            self.message.setText('Display mode changed. Select the glasses output and enter glasses view.')
            QTimer.singleShot(2500, self.refresh_screens)
            finished()
        def failed(message):
            self.problem(message)
            finished()
        self.run_job(lambda:tracker.set_stereo(enabled),ready,failed)

    def refresh_screens(self):
        current = self.display_combo.currentData()
        self.display_combo.blockSignals(True)
        self.display_combo.clear()
        screens = [s for s in QApplication.screens() if not s.name().startswith(PREFIX)]
        target = 0
        for index, screen in enumerate(screens):
            geo = screen.geometry()
            label = f'{screen.name()} · {geo.width()} × {geo.height()}'
            self.display_combo.addItem(label, screen.name())
            if current == screen.name() or (current is None and 'viture' in (screen.manufacturer()+screen.model()).lower()):
                target = index
        self.display_combo.setCurrentIndex(target)
        self.display_combo.blockSignals(False)
        self.refresh_sources()

    def enter_immersive(self):
        if self.viewer.arranging:
            self.end_arrange(True)
        screen = next((s for s in QApplication.screens() if s.name()==self.display_combo.currentData()), None)
        if screen is None or screen.name().startswith(PREFIX):
            return
        if screen.name()==getattr(self.desktop,'source',None):
            self.problem('Choose an output display different from the mirrored desktop in Settings.')
            return
        self.stop_browser_video()
        self.windowHandle().setScreen(screen)
        self.setGeometry(screen.geometry())
        self.viewer.fov = self.glasses_fov
        self.drawer_was_visible = self.controls.isVisible()
        self.set_controls_visible(False)
        self.toolbar.hide()
        self.footer.hide()
        self.showFullScreen()
        self.update_mirror_preview()
        self.viewer.setFocus()

    def leave_immersive(self):
        was_fullscreen = self.isFullScreen()
        self.showNormal()
        if was_fullscreen:
            self.viewer.fov = self.fov.value()
        self.toolbar.show()
        if was_fullscreen:
            self.set_controls_visible(getattr(self, 'drawer_was_visible', False))
        self.footer.show()
        self.viewer.clearFocus()
        self.update_mirror_preview()

    def toggle_immersive(self):
        self.leave_immersive() if self.isFullScreen() else self.enter_immersive()

    def update_status(self):
        self.stats.setText(f'{self.viewer.fps:.0f} render fps   ·   {self.args.capture_fps} capture fps target   ·   '
                           + ('Anchored in space' if self.viewer.anchored else 'Follows head'))
        if self.tracker:
            age = self.tracker.pose.age
            if age < .5:
                self.tracking_status.setText('Tracking on' if self.isFullScreen() else 'Tracking · Preview')
                self.tracking_status.setToolTip(f'VITURE connected · {age*1000:.0f} ms since latest sample. '
                                               'Use Glasses view for calibrated head movement through the lenses.')
            else:
                self.tracking_status.setText('Tracking lost')
                self.tracking_status.setToolTip('View held still. Reconnect tracking in Settings → View.')

    def render_problem(self, message):
        self.problem(message)
        if self.desktop and self.viewer.scene == 0:
            # Detach after paintGL releases any borrowed mmap pixels.
            QTimer.singleShot(0,self.detach_failed_desktop)

    def detach_failed_desktop(self):
        if not self.desktop or self.desktop_busy or self.closing:
            return
        desktop = self.desktop
        self.viewer.release_input()
        self.desktop = self.viewer.desktop = None
        self.viewer.has_source = False
        self.desktop_busy = True
        self.set_desktop_controls_enabled(False)
        def finished(_=None):
            self.desktop_busy = False
            self.set_desktop_controls_enabled(True)
            self.start_button.setText('Restart workspace')
            self.start_button.setEnabled(True)
            self.viewer.resume_rendering()
        def failed(message):
            finished()
            self.problem(message)
        self.run_job(desktop.close,finished,failed)

    def problem(self, message):
        message = message or 'An operation failed without an error message.'
        summary = message.splitlines()[0]
        if message.startswith('Native monitors could not start.'):
            # A worker traceback otherwise leaves only "Traceback ..." in the
            # footer, concealing the actual reason at the end of the message.
            reason = next((line.removeprefix('RuntimeError: ').strip() for line in reversed(message.splitlines())
                           if line.startswith('RuntimeError: ')),None)
            if reason:
                summary = 'Could not connect monitors: '+reason
        if message.startswith('Desktop stopped.'):
            summary = 'The desktop stopped. Save work in other apps and restart the workspace.'
        self.message.setText(summary[:220])
        self.message.setToolTip(message)
        self.message.setStyleSheet('color: #f3b991;')
        print(message, file=sys.stderr, flush=True)
        # Keep errors visible even when the controls were hidden for the glasses.
        if self.isFullScreen():
            self.leave_immersive()

    def closeEvent(self, event):
        self.closing = True
        if self.jobs:
            self.message.setText('Finishing device startup before closing…')
            event.ignore()
            return
        if self.tracker:
            self.disconnect_tracking()
            event.ignore()
            return
        self.stop_browser_video()
        self.viewer.timer.stop()
        self.save_monitor_layout()
        if not self.args.demo and not self.args.smoke_seconds and not self.args.profile_seconds:
            self.settings.setValue('glasses_fov', self.glasses_fov)
            self.settings.setValue('preview_fov', self.fov.value())
            self.settings.setValue('screen_degrees', self.layout.screen_degrees)
            self.settings.setValue('gap_degrees', self.layout.gap_degrees)
            self.settings.setValue('smoothing_ms', self.viewer.smoothing_ms)
            self.settings.setValue('anchored', self.viewer.anchored)
            self.settings.setValue('sharp_text', self.viewer.sharp_text)
            self.settings.setValue('sdk', self.sdk_edit.text())
            self.settings.setValue('screen_mode',self.screen_mode)
            self.settings.setValue('single_source',self.single_source)
            self.settings.setValue('multiple_count',self.multiple_count)
        self.sink.videoFrameChanged.disconnect(self.video_frame)
        self.player.stop()
        self.video_frames.close()
        self.viewer.video_frames = None
        self.viewer.release_input()
        if self.desktop:
            self.desktop.close()
            self.desktop = self.viewer.desktop = None
        event.accept()
