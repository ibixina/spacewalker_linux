"""Monitor placement controls. All drawing here belongs to the editor, never the XR scene."""
import math
import numpy as np
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QComboBox,
    QDoubleSpinBox, QFormLayout, QLabel, QPushButton, QSlider)


class ArrangementMap(QWidget):
    changed = Signal()
    selected = Signal(int)

    def __init__(self,layout,parent=None):
        super().__init__(parent)
        self.layout = layout
        self.selected_screen = layout.count//2
        self.drag = None
        self.scale = 1.
        self.setFixedHeight(180)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip('Top view. Drag a display around you or closer and farther away.')

    def origin(self):
        return QPointF(self.width()/2,self.height()/2)

    def screen_point(self,index):
        center = self.layout.placement(index).center
        origin = self.origin()
        return QPointF(origin.x()+center[0]*self.scale,origin.y()+center[2]*self.scale)

    def paintEvent(self,event):
        if self.drag is None:
            extent = max(4., max(self.layout.placement(i).distance for i in range(self.layout.count))+1.2)
            self.scale = (min(self.width(),self.height())-32)/(2*extent)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor('#111111'))
        o = self.origin()
        p.setPen(QPen(QColor('#282828'),1,Qt.PenStyle.DashLine))
        radius = self.scale*2.5
        p.drawEllipse(o,radius,radius)
        p.setPen(QColor('#777777'))
        p.drawText(QRectF(0,5,self.width(),20),Qt.AlignmentFlag.AlignCenter,'Front')
        p.drawText(QRectF(0,self.height()-25,self.width(),20),Qt.AlignmentFlag.AlignCenter,'Behind')
        p.setBrush(QColor('#aaaaaa'))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([o+QPointF(0,-6),o+QPointF(-4,4),o+QPointF(4,4)]))
        p.setPen(QColor('#aaaaaa'))
        p.drawText(QRectF(o.x()-20,o.y()+7,40,20),Qt.AlignmentFlag.AlignCenter,'You')
        for i in range(self.layout.count):
            center,right,up,normal,size = self.layout.panel_frame(i)
            c = self.screen_point(i)
            line = np.array([right[0],right[2]])*size[0]*self.scale
            if np.linalg.norm(line)<12:
                line = np.array([12.,0.])
            pen = QPen(QColor('#eeeeee' if i == self.selected_screen else '#777777'),4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(c-QPointF(*line),c+QPointF(*line))
            p.setPen(QColor('#eeeeee'))
            p.drawText(QRectF(c.x()-14,c.y()-25,28,20),Qt.AlignmentFlag.AlignCenter,str(i+1))
        p.end()

    def mousePressEvent(self,e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        distances = [(math.hypot((self.screen_point(i)-e.position()).x(),
                                  (self.screen_point(i)-e.position()).y()),i) for i in range(self.layout.count)]
        distance,index = min(distances)
        if distance <= 32:
            self.selected_screen = index
            self.drag = e.position()-self.screen_point(index)
            self.selected.emit(index)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.update()

    def mouseMoveEvent(self,e):
        if self.drag is None:
            return
        point = e.position()-self.drag-self.origin()
        x,z = point.x()/self.scale,point.y()/self.scale
        height = self.layout.placement(self.selected_screen).center[1]
        distance = float(np.clip(math.sqrt(x*x+z*z+height*height),.5,10))
        elevation = float(np.clip(math.degrees(math.atan2(height,max(.001,math.hypot(x,z)))),-80,80))
        self.layout.update_panel(self.selected_screen,azimuth=math.degrees(math.atan2(x,-z)),
                                 distance=distance,elevation=elevation)
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self,e):
        self.drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()


class LayoutEditor(QWidget):
    changed = Signal()
    selected = Signal(int)
    place_here = Signal()
    move_app_here = Signal()

    def __init__(self,layout,parent=None):
        super().__init__(parent)
        self.layout = layout
        self.selected_screen = layout.count//2
        box = QVBoxLayout(self)
        box.setContentsMargins(0,0,0,0)
        box.setSpacing(9)
        self.map = ArrangementMap(layout)
        box.addWidget(self.map)
        self.selector = QComboBox()
        self.selector.addItems([f'Display {i+1}' for i in range(layout.count)])
        self.selector.setCurrentIndex(self.selected_screen)
        self.selector.currentIndexChanged.connect(self.select)
        box.addWidget(self.selector)
        self.presets = QComboBox()
        self.presets.addItems(['Choose a layout…','Around me','Straight row','Vertical stack'])
        self.presets.activated.connect(self.apply_preset)
        box.addWidget(self.presets)
        self.map.selected.connect(self.select)
        self.map.changed.connect(self.edited)
        hint = QLabel('Drag a display in the view or on the map.\nScroll to change distance; Shift+scroll to resize.')
        hint.setObjectName('muted')
        hint.setWordWrap(True)
        box.addWidget(hint)
        place = QPushButton('Place where I’m looking')
        place.clicked.connect(self.place_here.emit)
        box.addWidget(place)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.fields = {}
        self.sliders = {}
        for key,label,lo,hi,step,suffix in [
                ('azimuth','Left / right',-180,180,1,'°'),
                ('elevation','Up / down',-80,80,1,'°'),
                ('distance','Distance',.5,10,.1,' m'),
                ('scale','Size',.25,3,.05,'×')]:
            spin = self.make_field(key,lo,hi,step,suffix)
            form.addRow(label,spin)
            form.addRow(self.make_slider(key,label))
        box.addLayout(form)
        angles = QPushButton('Screen angle ▸')
        angles.setObjectName('quiet')
        angles.setCheckable(True)
        box.addWidget(angles)
        angles_content = QWidget()
        angle_form = QFormLayout(angles_content)
        angle_form.setContentsMargins(0,0,0,0)
        for key,label,lo,hi in [('turn','Turn',-75,75),('tilt','Tilt',-75,75),('roll','Rotate',-180,180)]:
            angle_form.addRow(label,self.make_field(key,lo,hi,1,'°'))
            angle_form.addRow(self.make_slider(key,label))
        self.fields['tilt'].setToolTip('Lean forward or backward. At 0°, the display stands vertical.')
        box.addWidget(angles_content)
        angles_content.hide()
        angles.toggled.connect(angles_content.setVisible)
        angles.toggled.connect(lambda checked: angles.setText('Screen angle ▾' if checked else 'Screen angle ▸'))
        app_button = QPushButton('Move active app to this display')
        app_button.clicked.connect(self.move_app_here.emit)
        box.addWidget(app_button)
        self.refresh()

    def set_layout(self,layout):
        self.layout = self.map.layout = layout
        self.map.drag = None
        self.selector.blockSignals(True)
        self.selector.clear()
        self.selector.addItems([f'Display {i+1}' for i in range(layout.count)])
        self.selector.blockSignals(False)
        self.select(layout.count//2)

    def make_field(self,key,lo,hi,step,suffix):
        field = QDoubleSpinBox()
        field.setRange(lo,hi)
        field.setSingleStep(step)
        field.setDecimals(2 if key in ('distance','scale') else 1)
        field.setSuffix(suffix)
        field.setKeyboardTracking(False)
        field.valueChanged.connect(lambda value,key=key: self.change_field(key,value))
        self.fields[key] = field
        return field

    def make_slider(self,key,label):
        field = self.fields[key]
        precision = 10**field.decimals()
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(round(field.minimum()*precision),round(field.maximum()*precision))
        slider.setSingleStep(max(1,round(field.singleStep()*precision)))
        slider.setPageStep(slider.singleStep()*10)
        slider.setFixedHeight(22)
        slider.setAccessibleName(label)
        slider.setToolTip(label+' · updates the display as you drag')
        slider.setTracking(True)
        slider.valueChanged.connect(lambda value,key=key,precision=precision:
                                    self.change_field(key,value/precision))
        self.sliders[key] = slider
        return slider

    def select(self,index):
        self.selected_screen = index
        self.map.selected_screen = index
        self.selector.blockSignals(True)
        self.selector.setCurrentIndex(index)
        self.selector.blockSignals(False)
        self.refresh()
        self.selected.emit(index)

    def refresh(self):
        panel = self.layout.placement(self.selected_screen)
        for key,field in self.fields.items():
            field.blockSignals(True)
            field.setValue(getattr(panel,key))
            field.blockSignals(False)
            slider = self.sliders[key]
            slider.blockSignals(True)
            slider.setValue(round(getattr(panel,key)*10**field.decimals()))
            slider.blockSignals(False)
        self.map.update()

    def change_field(self,key,value):
        self.layout.update_panel(self.selected_screen,**{key:value})
        self.edited()

    def edited(self):
        self.refresh()
        self.changed.emit()

    def apply_preset(self,index):
        if index:
            self.layout.preset(('arc','flat','stack')[index-1])
            self.presets.setCurrentIndex(0)
            self.edited()
