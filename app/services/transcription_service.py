import logging
import subprocess
import threading
import time
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from app.vad.pipeline import transcribe

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_DURATION = 300
MIN_DURATION = 0.25
SR = 16000
logger = logging.getLogger('uvicorn.error')


class AudioValidationError(ValueError):
    pass


class ServiceBusyError(RuntimeError):
    pass


class TranscriptionService:
    def __init__(self, model, detector, model_name='small'):
        self.model = model
        self.detector = detector
        self.model_name = model_name
        self.lock = threading.Lock()

    def transcribe(self, upload, request_id=None):
        # Fail fast instead of building an unbounded inference queue. Silero and
        # Whisper share mutable state and must not run concurrent inference.
        if not self.lock.acquire(blocking=False):
            raise ServiceBusyError('Transcription is busy; retry later')
        started = time.perf_counter()
        try:
            with TemporaryDirectory(prefix='asr-') as directory:
                logger.info('[request_id=%s] preprocessing', request_id)
                audio = self._prepare(upload, Path(directory))
                logger.info('[request_id=%s] inference', request_id)
                result = transcribe(
                    self.model, audio, detector=self.detector, pre_ms=200, post_ms=300,
                    language='az', fp16=False, temperature=0.0, beam_size=5,
                    condition_on_previous_text=False, verbose=None,
                )
                duration = len(audio) / SR
                elapsed = time.perf_counter() - started
                return dict(language='az', duration=duration, processing_time=elapsed,
                            rtf=elapsed / duration, text=result['transcript'],
                            segments=result['chunks'])
        finally:
            self.lock.release()

    def _prepare(self, upload, directory):
        suffix = Path(upload.filename or '').suffix.lower()
        if suffix not in {'.wav', '.mp3'}:
            raise AudioValidationError('Only WAV and MP3 files are supported')
        source = directory / ('input' + suffix)
        size = 0
        with source.open('wb') as handle:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise AudioValidationError('Audio exceeds the 25 MiB upload limit')
                handle.write(chunk)
        if not size:
            raise AudioValidationError('Audio file is empty')
        target = directory / 'normalized.wav'
        try:
            # Decode at most limit + 1 seconds: reject excess, never silently trim.
            subprocess.run([
                'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror',
                '-protocol_whitelist', 'file,pipe', '-i', str(source), '-map', '0:a:0',
                '-t', str(MAX_DURATION + 1), '-vn', '-ac', '1', '-ar', str(SR),
                '-c:a', 'pcm_s16le', '-y', str(target),
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise AudioValidationError('Audio is corrupted, unsupported, or cannot be decoded') from exc
        with wave.open(str(target), 'rb') as handle:
            duration = handle.getnframes() / SR
            if duration < MIN_DURATION:
                raise AudioValidationError('Audio must be at least 0.25 seconds')
            if duration > MAX_DURATION:
                raise AudioValidationError('Audio must not exceed 300 seconds')
            return np.frombuffer(handle.readframes(handle.getnframes()), dtype='<i2').astype(np.float32) / 32768
