import json
import logging
from datetime import datetime, timezone

FIELDS = ('request_id', 'job_id', 'model', 'processing_time', 'error', 'status')


class JSONFormatter(logging.Formatter):
    def format(self, record):
        # Never serialize message arguments, exception tracebacks or audio/result data.
        payload = dict(timestamp=datetime.now(timezone.utc).isoformat(), level=record.levelname,
                       event=getattr(record, 'event', 'runtime_log'), logger=record.name)
        payload.update({field: getattr(record, field, None) for field in FIELDS})
        return json.dumps(payload)


def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access', 'celery'):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
