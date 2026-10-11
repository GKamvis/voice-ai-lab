import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile
from redis.exceptions import RedisError
from app.jobs.store import IdempotencyConflict, QueueFull
from app.services.transcription_service import MAX_UPLOAD_BYTES

router = APIRouter()


def public_job(job):
    fields = ('job_id', 'status', 'attempts', 'created_at', 'updated_at', 'result', 'error', 'model')
    return {key: job[key] for key in fields if key in job}


@router.post('/jobs', status_code=202)
async def create_job(request: Request, file: UploadFile = File(...),
                     idempotency_key: str = Header(default=None, max_length=200)):
    try:
        suffix = Path(file.filename or '').suffix.lower()
        if suffix not in {'.wav', '.mp3'}:
            raise HTTPException(400, 'Only WAV and MP3 files are supported')
        audio = await file.read(MAX_UPLOAD_BYTES + 1)
        if not audio:
            raise HTTPException(400, 'Audio file is empty')
        if len(audio) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, 'Audio exceeds the 25 MiB upload limit')
        job = await asyncio.to_thread(request.app.state.job_store.submit, audio, suffix,
                                      request.state.request_id, idempotency_key)
        return public_job(job)
    except IdempotencyConflict:
        raise HTTPException(409, 'Idempotency-Key was used with different audio') from None
    except QueueFull:
        raise HTTPException(503, 'Job capacity reached', headers={'Retry-After': '30'}) from None
    except RedisError:
        raise HTTPException(503, 'Job storage unavailable', headers={'Retry-After': '5'}) from None
    finally:
        await file.close()


@router.get('/jobs/{job_id}')
async def get_job(job_id: UUID, request: Request):
    try:
        job = await asyncio.to_thread(request.app.state.job_store.get, str(job_id))
    except RedisError:
        raise HTTPException(503, 'Job storage unavailable') from None
    if job is None:
        raise HTTPException(404, 'Job not found or expired')
    return public_job(job)
