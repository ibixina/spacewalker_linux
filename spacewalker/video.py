"""Convert only the newest decoded video frame, away from the rendering thread."""
from collections import deque
import threading
import time
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QVideoFrame


def upload_image(image):
    # Preserve layouts OpenGL can upload directly, avoiding an extra full-frame channel shuffle.
    if image.format() in (QImage.Format.Format_RGB32,QImage.Format.Format_ARGB32,
                          QImage.Format.Format_RGBA8888,QImage.Format.Format_RGBX8888):
        return image
    return image.convertToFormat(QImage.Format.Format_RGBA8888)


class VideoFrames:
    def __init__(self):
        self.condition = threading.Condition()
        self.pending = self.latest = None
        self.sequence = self.generation = 0
        self.stopping = False
        self.error = None
        self.conversion_ms = deque(maxlen=600)
        self.thread = threading.Thread(target=self.run,name='video-conversion',daemon=True)
        self.thread.start()

    def submit(self, frame):
        # A shallow frame reference replaces pending work; pixel conversion never runs here.
        if frame.isValid():
            with self.condition:
                if not self.stopping:
                    self.pending = (self.generation,QVideoFrame(frame))
                    self.condition.notify()

    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopping or self.pending is not None)
                if self.stopping:
                    return
                generation,frame = self.pending
                self.pending = None
            started = time.monotonic()
            try:
                image = self.convert(frame)
                if image.isNull():
                    raise RuntimeError('Could not convert the decoded video frame.')
                with self.condition:
                    if generation == self.generation and not self.stopping:
                        self.latest = image
                        self.sequence += 1
                        self.conversion_ms.append((time.monotonic()-started)*1000)
            except Exception as e:
                with self.condition:
                    if generation == self.generation:
                        self.error = str(e)
            finally:
                del frame

    @staticmethod
    def convert(frame):
        return upload_image(frame.toImage())

    def take(self, after_sequence):
        with self.condition:
            if self.error:
                message,self.error = self.error,None
                raise RuntimeError(message)
            return (self.sequence,self.latest) if self.latest is not None and self.sequence != after_sequence else None

    def reset(self):
        with self.condition:
            self.generation += 1
            self.pending = self.latest = self.error = None
            self.conversion_ms.clear()

    def close(self):
        with self.condition:
            self.stopping = True
            self.pending = self.latest = None
            self.condition.notify()
        self.thread.join(timeout=3)
