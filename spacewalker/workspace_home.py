"""Optional notes app, launched on demand from the Open menu."""
import sys
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QFileDialog
from PySide6.QtGui import QFont


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    windows = []
    for i in range(int(sys.argv[1])):
        w = QWidget()
        w.setWindowTitle('Untitled · Notes')
        w.setStyleSheet('QWidget { background: #191919; color: #ddd; font-size: 16px; } '
                       'QPlainTextEdit { background: #191919; border: 0; padding: 20px; } '
                       'QPushButton { background: #252525; border: 1px solid #444; padding: 8px 18px; border-radius: 4px; }')
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 16, 24, 24)
        bar = QHBoxLayout()
        bar.addWidget(QLabel('Untitled'))
        bar.addStretch()
        layout.addLayout(bar)
        editor = QPlainTextEdit()
        editor.setFont(QFont('Monospace', 15))
        editor.setPlaceholderText('Write a note…')
        layout.addWidget(editor, 1)
        save = QPushButton('Save note…')
        def save_note(checked=False, editor=editor, w=w):
            path, _ = QFileDialog.getSaveFileName(w, 'Save note', '', 'Text (*.txt)')
            if path:
                from pathlib import Path
                from PySide6.QtWidgets import QMessageBox
                try:
                    Path(path).write_text(editor.toPlainText())
                except OSError as e:
                    QMessageBox.warning(w, 'Cannot save', str(e))
        save.clicked.connect(save_note)
        bar.addWidget(save)
        w.resize(1000, 650)
        w.show()
        windows.append(w)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
