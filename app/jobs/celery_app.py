from celery.signals import setup_logging, heartbeat_sent
from app.observability.logging import configure_logging
from celery import Celery
from app.jobs import config

celery_app = Celery('speech', broker=config.REDIS_URL, include=['app.jobs.tasks'])
celery_app.conf.update(
    task_default_queue='asr', task_serializer='json', accept_content=['json'],
    task_ignore_result=True, task_acks_late=True, task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1, worker_cancel_long_running_tasks_on_connection_loss=True,
    task_soft_time_limit=config.SOFT_LIMIT, task_time_limit=config.HARD_LIMIT,
    broker_transport_options={'visibility_timeout': config.VISIBILITY},
    broker_connection_retry_on_startup=True, broker_connection_timeout=3,
    task_publish_retry=False, worker_hijack_root_logger=False,
)




@setup_logging.connect
def setup_worker_logging(**kwargs):
    configure_logging()


@heartbeat_sent.connect
def worker_heartbeat(sender=None, **kwargs):
    from app.jobs.store import JobStore
    try:
        JobStore().redis.set('asr:worker:' + sender.eventer.hostname, '1', ex=15)
    except Exception:
        pass  # Broker and job recovery remain independent of monitoring.
