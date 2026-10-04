"""Bounded callback capture; no inference in the audio callback."""
import queue
import time
import numpy as np
from app.streaming.buffer import SR, FRAME


def frames(seconds=30, device=None):
    import sounddevice as sd
    pending = queue.Queue(maxsize=100)
    failed = []
    def callback(data, count, timing, status):
        if status:
            failed.append(str(status))
        # PortAudio ADC timestamp mapped to the monotonic clock.
        end_time = time.perf_counter() + timing.inputBufferAdcTime + count / SR - timing.currentTime
        try:
            pending.put_nowait((data[:, 0].copy(), end_time))
        except queue.Full:
            failed.append('Capture queue overflow')
    with sd.InputStream(samplerate=SR, channels=1, dtype='float32', blocksize=FRAME,
                        device=device, callback=callback):
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            if failed:
                raise RuntimeError('; '.join(failed))
            try:
                yield pending.get(timeout=0.1)
            except queue.Empty:
                continue
        if failed:
            raise RuntimeError('; '.join(failed))
