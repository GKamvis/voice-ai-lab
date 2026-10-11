"""Isolated Compose test entry point: real Celery/FFmpeg, deterministic mock ASR."""
import time
from unittest.mock import Mock
from app.jobs import tasks
from app.jobs.celery_app import celery_app
from app.services.transcription_service import TranscriptionService


def transcribe(*args, **kwargs):
    time.sleep(2)
    return {'text': 'integration fixture'}


model = Mock()
model.transcribe.side_effect = transcribe
service = TranscriptionService(model, lambda audio, sr: [{'start': 0, 'end': len(audio)}])
tasks.get_service = lambda: service

if __name__ == '__main__':
    celery_app.worker_main(['worker', '--loglevel=INFO', '--concurrency=1', '--hostname=test@%h'])
