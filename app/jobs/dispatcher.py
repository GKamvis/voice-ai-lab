"""Replay the persisted outbox, including jobs abandoned by a killed worker."""
import logging
from app.jobs.celery_app import celery_app

logger = logging.getLogger(__name__)


def dispatch_once(store, publish=None):
    # Each delivery needs its own Celery ID: an expired message is revoked by ID.
    # The stable logical job ID lives in the argument and is fenced by JobStore.
    publish = publish or (lambda job_id: celery_app.send_task(
        'speech.transcribe', args=[job_id], expires=25))
    for job_id in store.due():
        if store.reserve_delivery(job_id):
            # If publishing fails, the reservation expires in 30 seconds.
            publish(job_id)


def run_dispatcher(store, stop):
    while not stop.is_set():
        try:
            dispatch_once(store)
        except Exception:
            logger.warning('dispatch_unavailable', extra={'event': 'dispatch_unavailable'})
        stop.wait(1)
