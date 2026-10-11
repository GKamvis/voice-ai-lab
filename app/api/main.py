import hmac
import logging
import math
import os
import threading
import asyncio
import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from redis.exceptions import RedisError
from app.observability.logging import configure_logging
from app.observability.metrics import create_metrics
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
        configure_logging()
        app.state.job_store = job_store or JobStore()
        app.state.metrics = create_metrics(app.state.job_store)
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
        token = os.getenv('API_TOKEN')
        if token and request.url.path.startswith('/jobs'):
            if not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + token):
                return Response(status_code=401, headers={'WWW-Authenticate': 'Bearer'})
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get('route')
        path = route.path if route else 'unmatched'
        if path not in ('/metrics', '/health', '/ready'):
            _, counter, histogram = request.app.state.metrics
            counter.labels(request.method, path, str(response.status_code)).inc()
            elapsed = time.perf_counter() - started
            histogram.labels(request.method, path).observe(elapsed)
            logger.info('http_request', extra={'event': 'http_request', 'request_id': request.state.request_id,
                        'processing_time': elapsed, 'status': response.status_code})
        response.headers['X-Request-ID'] = request.state.request_id
        return response

    @app.get('/ready')
    async def ready():
        try:
            await asyncio.to_thread(app.state.job_store.redis.ping)
        except RedisError:
            raise HTTPException(503, 'Redis unavailable') from None
        return {'status': 'ready'}

    @app.get('/metrics', include_in_schema=False)
    async def metrics():
        try:
            data = await asyncio.to_thread(generate_latest, app.state.metrics[0])
        except RedisError:
            raise HTTPException(503, 'Metrics storage unavailable') from None
        return Response(data, media_type=CONTENT_TYPE_LATEST)

    app.include_router(jobs_router)
    app.include_router(router)
    return app


app = create_app()
