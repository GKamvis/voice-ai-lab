import logging
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from app.api.schemas import HealthResponse, TranscriptionResponse
from app.services.transcription_service import AudioValidationError, ServiceBusyError

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
                        503: {'description': 'Model not ready or busy'}})
def transcribe(request: Request, file: UploadFile = File(...)):
    # FastAPI executes this synchronous handler in its worker thread pool.
    try:
        service = getattr(request.app.state, 'service', None)
        if service is None:
            raise HTTPException(503, 'Model is not ready')
        return service.transcribe(file)
    except AudioValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ServiceBusyError as exc:
        raise HTTPException(503, str(exc), headers={'Retry-After': '1'}) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception('Transcription failed')
        raise HTTPException(500, 'Audio processing failed') from exc
    finally:
        file.file.close()
