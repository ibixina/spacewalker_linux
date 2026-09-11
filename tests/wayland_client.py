"""A real host Wayland window for the opt-in native monitor integration test."""
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget


class Window(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(231, 43, 97))
        painter.fillRect(30, 30, 80, 80, QColor(17, 205, 63))


app = QApplication([])
window = Window()
window.setWindowTitle('Spacewalker native monitor integration test')
window.resize(420, 240)
window.show()
QTimer.singleShot(60000, app.quit)
app.exec()
