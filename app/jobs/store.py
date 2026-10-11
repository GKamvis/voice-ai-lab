"""Redis is the durable source of truth, including a transactional delivery outbox.

At-least-once delivery is intentional. A fenced lease prevents overlapping work,
terminal results are immutable, and only a matching lease owner can finish a job.
"""
import hashlib
import json
import time
import uuid

from redis import Redis, WatchError
from app.jobs import config

TERMINAL = {'completed', 'failed'}
OUTBOX = 'asr:outbox'


class QueueFull(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


class JobStore:
    def __init__(self, client=None):
        self.redis = client or Redis.from_url(config.STATE_URL, socket_timeout=3,
                                             socket_connect_timeout=3)

    @staticmethod
    def key(job_id):
        return 'asr:job:' + job_id

    def get(self, job_id):
        value = self.redis.get(self.key(job_id))
        return json.loads(value) if value else None

    def submit(self, audio, suffix, request_id, idempotency_key=None):
        fingerprint = hashlib.sha256(suffix.encode() + audio).hexdigest()
        identity = hashlib.sha256(idempotency_key.encode()).hexdigest() if idempotency_key else uuid.uuid4().hex
        idem = 'asr:idem:' + identity
        with self.redis.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(idem, OUTBOX)
                    existing = pipe.get(idem)
                    if existing:
                        job = self.get(existing.decode())
                        if job:
                            if job['fingerprint'] != fingerprint:
                                raise IdempotencyConflict
                            return job
                    if pipe.zcard(OUTBOX) >= config.MAX_ACTIVE:
                        raise QueueFull
                    now = time.time()
                    job_id = str(uuid.uuid4())
                    job = dict(job_id=job_id, request_id=request_id, status='queued',
                               suffix=suffix, model=config.MODEL, fingerprint=fingerprint,
                               created_at=now, updated_at=now, attempts=0, idem=idem)
                    # Active jobs do not expire. Audio is deleted at terminal state;
                    # terminal job and idempotency mapping expire together.
                    pipe.multi()
                    pipe.set(self.key(job_id), json.dumps(job))
                    pipe.set('asr:audio:' + job_id, audio)
                    pipe.set(idem, job_id)
                    pipe.zadd(OUTBOX, {job_id: now})
                    pipe.sadd('asr:state:queued', job_id)
                    pipe.execute()
                    return job
                except WatchError:
                    continue

    def _change(self, job_id, change):
        key = self.key(job_id)
        with self.redis.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    if not raw:
                        return None
                    job = json.loads(raw)
                    previous = job['status']
                    if previous in TERMINAL or not change(job):
                        return None
                    job['updated_at'] = time.time()
                    pipe.multi()
                    pipe.set(key, json.dumps(job))
                    pipe.srem('asr:state:' + previous, job_id)
                    if job['status'] in TERMINAL:
                        pipe.expire(key, config.RETENTION)
                        pipe.expire(job['idem'], config.RETENTION)
                        pipe.delete('asr:audio:' + job_id)
                        pipe.zrem(OUTBOX, job_id)
                        pipe.incr('asr:metrics:jobs_' + job['status'])
                    else:
                        pipe.sadd('asr:state:' + job['status'], job_id)
                        pipe.zadd(OUTBOX, {job_id: job['next_delivery']})
                    pipe.execute()
                    return job
                except WatchError:
                    continue

    def claim(self, job_id):
        def change(job):
            now = time.time()
            if job.get('lease_until', 0) > now or job.get('retry_at', 0) > now:
                return False
            if job['attempts'] >= config.MAX_ATTEMPTS:
                job.update(status='failed', error='Worker retry budget exhausted')
            else:
                job.update(status='processing', token=uuid.uuid4().hex,
                           attempts=job['attempts'] + 1, lease_until=now + config.LEASE,
                           next_delivery=now + config.LEASE + 1)
            return True
        return self._change(job_id, change)

    def finish(self, job_id, token, *, result=None, error=None, retry_delay=None):
        def change(job):
            if job.get('token') != token or job['status'] != 'processing':
                return False
            if retry_delay is not None and job['attempts'] < config.MAX_ATTEMPTS:
                retry_at = time.time() + retry_delay
                job.update(status='retrying', retry_at=retry_at, lease_until=0,
                           next_delivery=retry_at, error=error)
            else:
                job.update(status='failed' if error else 'completed', error=error, result=result)
            return True
        return self._change(job_id, change)

    def due(self):
        return [x.decode() for x in self.redis.zrangebyscore(OUTBOX, 0, time.time(), start=0, num=20)]

    def reserve_delivery(self, job_id):
        # WATCH the job so an API dispatcher cannot overwrite a newly claimed lease.
        def change(job):
            if job.get('next_delivery', 0) > time.time():
                return False
            job['next_delivery'] = time.time() + 30
            return True
        return self._change(job_id, change)
