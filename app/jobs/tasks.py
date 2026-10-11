import io
import logging
import random
from functools import lru_cache

from billiard.exceptions import SoftTimeLimitExceeded
from fastapi import UploadFile
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from app.jobs import config
from app.jobs.celery_app import celery_app
from app.jobs.store import JobStore
from app.services.transcription_service import AudioValidationError

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_service():
    from app.asr.whisper_model import load_model
    from app.services.transcription_service import TranscriptionService
    from app.vad.silero_vad import SileroVAD
    model, _ = load_model(config.MODEL)
    return TranscriptionService(model, SileroVAD(), config.MODEL)


@celery_app.task(bind=True, name='speech.transcribe', max_retries=3)
def transcribe_audio(self, job_id):
    store = JobStore()
    job = store.claim(job_id)
    if not job or job['status'] != 'processing':
        return
    context = dict(request_id=job['request_id'], job_id=job_id, model=job['model'])
    logger.info('transcription_started', extra={**context, 'event': 'transcription_started', 'status': 'processing'})
    try:
        data = store.redis.get('asr:audio:' + job_id)
        if data is None:
            raise AudioValidationError('Audio payload is unavailable')
        with io.BytesIO(data) as handle:
            upload = UploadFile(filename='audio' + job['suffix'], file=handle)
            result = get_service().transcribe(upload, job['request_id'])
    except (ConnectionError, TimeoutError, RedisConnectionError, RedisTimeoutError,
            SoftTimeLimitExceeded):
        delay = min(60, 2 ** job['attempts']) + random.uniform(0, 1)
        updated = store.finish(job_id, job['token'], error='Temporary processing failure', retry_delay=delay)
        logger.warning('transcription_retry', extra={**context, 'event': 'transcription_retry',
                       'status': updated['status'] if updated else 'retrying', 'error': 'transient'})
        if updated and updated['status'] == 'retrying':
            raise self.retry(countdown=delay)
    except Exception as exc:
        message = 'Invalid or corrupted audio' if isinstance(exc, AudioValidationError) else 'Audio processing failed'
        store.finish(job_id, job['token'], error=message)
        # Deliberately exclude exception messages, filenames, and transcripts.
        logger.error('transcription_failed', extra={**context, 'event': 'transcription_failed',
                     'status': 'failed', 'error': type(exc).__name__})
    else:
        store.finish(job_id, job['token'], result=result)
        logger.info('transcription_completed', extra={**context, 'event': 'transcription_completed',
                    'status': 'completed', 'processing_time': result['processing_time']})
