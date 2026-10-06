import asyncio
import io
import logging
import uuid
from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from app.api.schemas import HealthResponse, TranscriptionResponse
from app.services.transcription_service import AudioValidationError, ServiceBusyError, MAX_UPLOAD_BYTES

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get('/health', response_model=HealthResponse)
async def health(request: Request):
    service = getattr(request.app.state, 'service', None)
    if service is None:
        raise HTTPException(503, 'Model is not ready')
    return dict(status='healthy', model='whisper-' + service.model_name)


@router.post('/transcribe', response_model=TranscriptionResponse,
             responses={400: {'description': 'Invalid audio'},
                        500: {'description': 'Internal processing failure'},
                        503: {'description': 'Model not ready or queue full'},
                        504: {'description': 'Queue and processing timeout'}})
async def transcribe(request: Request, response: Response, file: UploadFile = File(...)):
    request_id = str(uuid.uuid4())
    headers = {'X-Request-ID': request_id}
    response.headers.update(headers)
    logging.getLogger('uvicorn.error').info('[request_id=%s] received', request_id)
    owned_upload = None
    future = None
    try:
        queue = getattr(request.app.state, 'asr_queue', None)
        if queue is None:
            raise HTTPException(503, 'Model is not ready', headers=headers)
        if queue.queue.full() or not queue.accepting:
            raise asyncio.QueueFull
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise AudioValidationError('Audio exceeds the 25 MiB upload limit')
        # The worker owns a copy: a timed-out HTTP request may close its upload
        # while native inference is still running in the background thread.
        owned_upload = UploadFile(filename=file.filename, file=io.BytesIO(data))
        future = queue.submit(request_id, owned_upload)
        owned_upload = None
        return await asyncio.wait_for(future, timeout=request.app.state.request_timeout)
    except AudioValidationError as exc:
        raise HTTPException(400, str(exc), headers=headers) from exc
    except (asyncio.QueueFull, ServiceBusyError) as exc:
        logging.getLogger('uvicorn.error').warning('[request_id=%s] rejected queue full/busy', request_id)
        raise HTTPException(503, 'Transcription queue is full; retry later',
                            headers={**headers, 'Retry-After': '1'}) from exc
    except asyncio.TimeoutError as exc:
        logging.getLogger('uvicorn.error').warning('[request_id=%s] timeout', request_id)
        raise HTTPException(504, 'Transcription deadline exceeded', headers=headers) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception('[request_id=%s] Transcription failed', request_id)
        raise HTTPException(500, 'Audio processing failed', headers=headers) from exc
    finally:
        if future is not None and not future.done():
            future.cancel()
        if owned_upload is not None:
            owned_upload.file.close()
        await file.close()
