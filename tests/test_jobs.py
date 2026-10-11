from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import time

import fakeredis
import pytest
from fastapi.testclient import TestClient
from celery.exceptions import Retry

from app.api.main import create_app
from app.jobs import config, tasks
from app.jobs.dispatcher import dispatch_once
from app.jobs.store import JobStore, OUTBOX
from app.services.transcription_service import TranscriptionService
from test_api import wav


@pytest.fixture
def store():
    return JobStore(fakeredis.FakeRedis())


@pytest.fixture
def client(store):
    with TestClient(create_app(job_store=store, dispatch=False)) as client:
        yield client


def submit(client, data=None, **kwargs):
    return client.post('/jobs', files={'file': ('audio.wav', wav() if data is None else data)}, **kwargs)


def test_health(client):
    assert client.get('/health').status_code == 200


def test_five_concurrent_jobs(client):
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: submit(client), range(5)))
    assert all(r.status_code == 202 for r in responses)
    assert len({r.json()['job_id'] for r in responses}) == 5
    for response in responses:
        assert client.get('/jobs/' + response.json()['job_id']).json()['status'] == 'queued'


def test_validation(client):
    assert submit(client, b'').status_code == 400
    assert client.post('/jobs', files={'file': ('a.txt', b'hello')}).status_code == 400
    assert client.get('/jobs/not-a-uuid').status_code == 422
    assert client.get('/jobs/00000000-0000-0000-0000-000000000000').status_code == 404


def test_idempotency(client):
    headers = {'Idempotency-Key': 'one'}
    first = submit(client, headers=headers)
    second = submit(client, headers=headers)
    assert first.json()['job_id'] == second.json()['job_id']
    assert submit(client, b'different', headers=headers).status_code == 409


def test_outbox_survives_publish_failure(store):
    job = store.submit(wav(), '.wav', 'request')
    with pytest.raises(ConnectionError):
        dispatch_once(store, Mock(side_effect=ConnectionError))
    assert store.get(job['job_id'])['status'] == 'queued'
    assert store.redis.zscore(OUTBOX, job['job_id']) is not None


def test_worker_normal_and_duplicate(store, monkeypatch):
    model = Mock()
    model.transcribe.return_value = {'text': 'Salam'}
    service = TranscriptionService(model, Mock(return_value=[{'start': 0, 'end': 16000}]))
    monkeypatch.setattr(tasks, 'JobStore', lambda: store)
    monkeypatch.setattr(tasks, 'get_service', lambda: service)
    job_id = store.submit(wav(), '.wav', 'r')['job_id']
    tasks.transcribe_audio.run(job_id)
    tasks.transcribe_audio.run(job_id)
    job = store.get(job_id)
    assert job['status'] == 'completed'
    assert job['result']['text'] == 'Salam'
    assert model.transcribe.call_count == 1
    assert store.redis.get('asr:audio:' + job_id) is None
    assert store.redis.ttl(store.key(job_id)) > 0


@pytest.mark.parametrize('data,service,error', [
    (b'broken audio', TranscriptionService(Mock(), Mock()), 'Invalid or corrupted audio'),
    (wav(), Mock(transcribe=Mock(side_effect=RuntimeError('private'))), 'Audio processing failed'),
])
def test_worker_failure(store, monkeypatch, data, service, error):
    monkeypatch.setattr(tasks, 'JobStore', lambda: store)
    monkeypatch.setattr(tasks, 'get_service', lambda: service)
    job_id = store.submit(data, '.wav', 'r')['job_id']
    tasks.transcribe_audio.run(job_id)
    assert store.get(job_id)['status'] == 'failed'
    assert store.get(job_id)['error'] == error


def test_retry_backoff_and_budget(store, monkeypatch):
    monkeypatch.setattr(tasks, 'JobStore', lambda: store)
    monkeypatch.setattr(tasks, 'get_service', Mock(side_effect=ConnectionError('secret')))
    monkeypatch.setattr(tasks.transcribe_audio, 'retry', Mock(side_effect=Retry()))
    job_id = store.submit(wav(), '.wav', 'r')['job_id']
    for attempt in range(1, config.MAX_ATTEMPTS + 1):
        if attempt < config.MAX_ATTEMPTS:
            with pytest.raises(Retry):
                tasks.transcribe_audio.run(job_id)
            assert store.get(job_id)['status'] == 'retrying'
            countdown = tasks.transcribe_audio.retry.call_args.kwargs['countdown']
            assert 2 ** attempt <= countdown <= 2 ** attempt + 1
            # Move retry eligibility into the past without sleeping.
            store._change(job_id, lambda j: j.update(retry_at=0, next_delivery=0) or True)
        else:
            tasks.transcribe_audio.run(job_id)
    assert store.get(job_id)['status'] == 'failed'
    assert store.get(job_id)['attempts'] == 4


def test_crash_recovery_and_fencing(store):
    job_id = store.submit(wav(), '.wav', 'r')['job_id']
    first = store.claim(job_id)
    assert store.claim(job_id) is None
    store._change(job_id, lambda j: j.update(lease_until=time.time() - 1, next_delivery=0) or True)
    second = store.claim(job_id)
    assert second['attempts'] == 2
    assert store.finish(job_id, first['token'], result={'text': 'stale'}) is None
    assert store.finish(job_id, second['token'], result={'text': 'fresh'})['status'] == 'completed'


def test_capacity(client, monkeypatch):
    monkeypatch.setattr(config, 'MAX_ACTIVE', 1)
    assert submit(client).status_code == 202
    assert submit(client).status_code == 503


def test_metrics_include_worker_results_and_no_job_labels(client, store):
    job_id = submit(client).json()['job_id']
    job = store.claim(job_id)
    store.finish(job_id, job['token'], result={'inference_time': 1.2, 'processing_time': 1.5})
    response = client.get('/metrics')
    assert response.status_code == 200
    assert 'asr_jobs_completed_total 1.0' in response.text
    assert 'asr_inference_duration_seconds_count 1.0' in response.text
    assert 'asr_queue_length 0.0' in response.text
    assert job_id not in response.text


def test_structured_logging_drops_private_data():
    import json
    import logging
    from app.observability.logging import JSONFormatter
    record = logging.LogRecord('test', logging.ERROR, '', 1, 'private transcript %s', ('private path',), None)
    record.event = 'transcription_failed'
    record.job_id = 'opaque-id'
    data = JSONFormatter().format(record)
    assert 'private' not in data
    assert json.loads(data)['job_id'] == 'opaque-id'
