import mmap
import multiprocessing
import time
import numpy as np
import pytest
from spacewalker.frames import FrameExchange, next_capture_deadline


def producer(path, size, connection):
    with open(path,'r+b') as file, mmap.mmap(file.fileno(),0) as buffer:
        exchange = FrameExchange(file,buffer,size)
        while (sequence := connection.recv()) is not None:
            now = time.monotonic()
            connection.send(exchange.publish(bytes([sequence])*size,sequence,now,now))


def test_slow_reader_never_blocks_producer_or_receives_torn_pixels(tmp_path):
    size = 128*128*4
    path = tmp_path/'frames'
    path.write_bytes(bytes(FrameExchange.size(size)))
    context = multiprocessing.get_context('spawn')
    parent,child = context.Pipe()
    process = context.Process(target=producer,args=(path,size,child))
    process.start()
    try:
        with open(path,'r+b') as file, mmap.mmap(file.fileno(),0) as buffer:
            exchange = FrameExchange(file,buffer,size)
            with exchange.read(0) as frame:
                assert frame is None
            parent.send(1)
            assert parent.poll(5) and parent.recv()
            with exchange.read(0) as frame:
                assert frame.sequence == 1
                for sequence in range(2,9):
                    parent.send(sequence)
                    assert parent.poll(2) and parent.recv()
                    assert np.all(frame.pixels == 1)  # Held frame remains intact while eight frames publish.
            del frame
            with exchange.read(1) as frame:
                assert frame.sequence == 8  # Skip obsolete frames; there is no replay queue.
                assert np.all(frame.pixels == 8)
            del frame
            with exchange.read(8) as frame:
                assert frame is None
    finally:
        parent.send(None)
        process.join(3)
        if process.is_alive():
            process.terminate()
            process.join(3)
    assert process.exitcode == 0


def test_capture_schedule_accounts_for_work_without_catchup_bursts():
    period = 1/60
    assert next_capture_deadline(10,10.006,period) == pytest.approx(10+period)
    assert next_capture_deadline(10,10.052,period) == pytest.approx(10+4*period)
