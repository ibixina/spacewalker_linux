"""Three shared frame slots: publish the latest frame without queuing or waiting.

The short metadata flock protects slot selection. A per-slot POSIX lock protects
the pixels while the renderer uploads directly from mmap. The producer always
has another slot available; neither process waits for the other to finish a frame.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
import struct
import time
import numpy as np

HEADER = 64
SLOT_HEADER = 32
SLOTS = 3


@dataclass
class Frame:
    sequence: int
    started: float
    captured: float
    published: float
    pixels: np.ndarray
    # Native capture publishes per-monitor generations in the spare header.
    # An all-zero tuple denotes a producer that always updates the whole atlas.
    generations: tuple = ()


class FrameExchange:
    def __init__(self, file, buffer, frame_bytes):
        self.file, self.buffer, self.frame_bytes = file, buffer, frame_bytes
        self.stride = SLOT_HEADER+frame_bytes
        self.next_slot = 0

    @staticmethod
    def size(frame_bytes):
        return HEADER+SLOTS*(SLOT_HEADER+frame_bytes)

    def offset(self, slot):
        return HEADER+slot*self.stride

    def lock_slot(self, slot, operation):
        fcntl.lockf(self.file, operation, 1, self.offset(slot), os.SEEK_SET)

    def publish(self, pixels, sequence, started, captured):
        current = struct.unpack_from('QdQ',self.buffer)[2]
        for advance in range(SLOTS):
            slot = (self.next_slot+advance)%SLOTS
            if slot == current:
                continue
            try:
                self.lock_slot(slot,fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            try:
                offset = self.offset(slot)
                self.buffer[offset+SLOT_HEADER:offset+self.stride] = pixels
                struct.pack_into('Qddd',self.buffer,offset,sequence,started,captured,time.monotonic())
                try:
                    fcntl.flock(self.file,fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return False
                try:
                    struct.pack_into('QdQ',self.buffer,0,sequence,captured,slot)
                finally:
                    fcntl.flock(self.file,fcntl.LOCK_UN)
                self.next_slot = (slot+1)%SLOTS
                return True
            finally:
                self.lock_slot(slot,fcntl.LOCK_UN)
        return False

    @contextmanager
    def read(self, after_sequence):
        slot = None
        metadata_locked = False
        frame = None
        try:
            try:
                fcntl.flock(self.file,fcntl.LOCK_SH | fcntl.LOCK_NB)
                metadata_locked = True
                sequence,_,candidate = struct.unpack_from('QdQ',self.buffer)
                if sequence and sequence != after_sequence:
                    self.lock_slot(candidate,fcntl.LOCK_SH | fcntl.LOCK_NB)
                    slot = candidate
                    values = struct.unpack_from('Qddd',self.buffer,self.offset(slot))
                    pixels = np.frombuffer(self.buffer,dtype=np.uint8,count=self.frame_bytes,
                                           offset=self.offset(slot)+SLOT_HEADER)
                    frame = Frame(*values,pixels,struct.unpack_from('5Q',self.buffer,24))
            except BlockingIOError:
                pass
            finally:
                if metadata_locked:
                    fcntl.flock(self.file,fcntl.LOCK_UN)
            yield frame
        finally:
            if slot is not None:
                self.lock_slot(slot,fcntl.LOCK_UN)


def next_capture_deadline(previous, now, period):
    """Account for capture time and skip missed slots, never accumulate a backlog."""
    following = previous+period
    if following <= now:
        following += (int((now-following)/period)+1)*period
    return following
