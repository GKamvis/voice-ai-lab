"""Sample-clock endpointing using the existing RMS VAD."""
from collections import deque
from dataclasses import dataclass
import numpy as np
from app.vad.energy_vad import rms, validate_audio

SR = 16000
FRAME = 480

@dataclass
class Utterance:
    audio: np.ndarray
    start: int
    speech_start: int
    speech_end: int
    detected: int
    reason: str

class EndpointBuffer:
    def __init__(self, threshold=0.03, silence_ms=690, pre_ms=210, max_seconds=30):
        if not np.isfinite(threshold) or threshold < 0 or not 600 <= silence_ms <= 800 or pre_ms < 0 or max_seconds <= 0:
            raise ValueError('Invalid endpoint settings')
        self.threshold = threshold
        self.silence = round(SR * silence_ms / 1000)
        self.limit = round(SR * max_seconds)
        self.pre = deque(maxlen=round(pre_ms / 30))
        self.parts = []
        self.position = self.start = self.last_speech = 0

    def push(self, frame):
        frame = validate_audio(frame, SR).copy()
        if not 0 < len(frame) <= FRAME:
            raise ValueError('Expected 1–480 samples')
        begin = self.position
        self.position += len(frame)
        speech = rms(frame) > self.threshold
        if speech and not self.parts:
            self.speech_start = begin
            self.parts = list(self.pre)
            self.start = begin - sum(map(len, self.parts))
            self.pre.clear()
        if speech:
            self.last_speech = self.position
        if self.parts or speech:
            self.parts.append(frame)
            if self.position - self.last_speech >= self.silence:
                return self.flush('silence')
            if self.position - self.start >= self.limit:
                return self.flush('max_duration')
        else:
            self.pre.append(frame)
        return None

    def flush(self, reason='eof'):
        if not self.parts:
            return None
        result = Utterance(np.concatenate(self.parts), self.start, self.speech_start, self.last_speech, self.position, reason)
        self.parts = []
        self.pre.clear()
        return result
