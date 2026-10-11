import logging
import math
import os
import threading
import asyncio
import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.routes import router
from app.services.asr_queue import ASRQueue

from app.jobs.store import JobStore
from app.jobs.routes import router as jobs_router
from app.jobs.dispatcher import run_dispatcher

logger = logging.getLogger('uvicorn.error')


def create_app(service_factory=None, job_store=None, dispatch=True):
    @asynccontextmanager
    async def lifespan(app):
        capacity = int(os.environ.get('ASR_QUEUE_SIZE', '10'))
        timeout = float(os.environ.get('ASR_REQUEST_TIMEOUT', '300'))
        if capacity < 1 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Queue size and timeout must be positive and finite')
        app.state.request_timeout = timeout
        app.state.job_store = job_store or JobStore()
        if service_factory is None:
            stop = threading.Event()
            thread = threading.Thread(target=run_dispatcher, args=(app.state.job_store, stop), daemon=True)
            if dispatch:
                thread.start()
            try:
                yield
            finally:
                stop.set()
                if dispatch:
                    await asyncio.to_thread(thread.join, 10)
            return
        started = time.perf_counter()
        app.state.service = service_factory()
        app.state.asr_queue = ASRQueue(app.state.service, capacity)
        logger.info('Service startup time: %.3f s', time.perf_counter() - started)
        try:
            yield
        finally:
            await app.state.asr_queue.close()
            app.state.service = None

    app = FastAPI(title='Voice AI Lab ASR', lifespan=lifespan)
    @app.middleware('http')
    async def request_context(request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        return response

    app.include_router(jobs_router)
    app.include_router(router)
    return app


app = create_app()
