import logging
import math
import os
import shutil
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.routes import router
from app.services.asr_queue import ASRQueue
from app.asr.whisper_model import load_model
from app.services.transcription_service import TranscriptionService
from app.vad.silero_vad import SileroVAD

logger = logging.getLogger('uvicorn.error')


def create_app(service_factory=None):
    @asynccontextmanager
    async def lifespan(app):
        capacity = int(os.environ.get('ASR_QUEUE_SIZE', '10'))
        timeout = float(os.environ.get('ASR_REQUEST_TIMEOUT', '300'))
        if capacity < 1 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Queue size and timeout must be positive and finite')
        app.state.request_timeout = timeout
        started = time.perf_counter()
        if service_factory is None:
            if shutil.which('ffmpeg') is None:
                raise RuntimeError('Install ffmpeg before starting the API')
            name = os.environ.get('ASR_MODEL', os.environ.get('WHISPER_MODEL', 'small'))
            model, loading_time = load_model(name)
            app.state.model_loading_time = loading_time
            app.state.service = TranscriptionService(model, SileroVAD(), name)
            logger.info('Model loading time: %.3f s (whisper-%s)', loading_time, name)
        else:
            app.state.service = service_factory()
        app.state.asr_queue = ASRQueue(app.state.service, capacity)
        logger.info('Service startup time: %.3f s', time.perf_counter() - started)
        try:
            yield
        finally:
            await app.state.asr_queue.close()
            app.state.service = None

    app = FastAPI(title='Voice AI Lab ASR', lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
