import threading
import time
from PySide6.QtGui import QImage,QColor
from PySide6.QtMultimedia import QVideoFrame
from spacewalker.video import VideoFrames


def test_slow_conversion_skips_obsolete_frames_and_source_reset_discards_inflight_work():
    converter = VideoFrames()
    started,release = threading.Event(),threading.Event()
    converted = []
    convert = converter.convert
    def slow(frame):
        converted.append(frame.toImage().pixelColor(0,0).name())
        if len(converted) == 1:
            started.set()
            assert release.wait(3)
        return convert(frame)
    converter.convert = slow
    def submit(color):
        image = QImage(8,8,QImage.Format.Format_RGBA8888)
        image.fill(QColor(color))
        converter.submit(QVideoFrame(image))
    try:
        submit('red')
        assert started.wait(3)
        submit('green')
        submit('blue')
        converter.reset()
        submit('yellow')
        release.set()
        deadline = time.monotonic()+3
        while (result := converter.take(0)) is None and time.monotonic()<deadline:
            time.sleep(.005)
        assert result is not None
        sequence,image = result
        assert sequence == 1
        assert image.pixelColor(0,0).name() == '#ffff00'
        assert converted == ['#ff0000','#ffff00']
    finally:
        release.set()
        converter.close()
    assert not converter.thread.is_alive()
