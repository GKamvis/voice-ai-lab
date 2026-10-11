"""API metrics are process-local; worker metrics are atomic Redis aggregates.

Redis aggregates survive worker restarts and include every prefork child. Deploy
one API process per container, and scrape each API container individually.
"""
from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, HistogramMetricFamily

BOUNDS = (.01, .05, .1, .25, .5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1200, 3600)
HISTOGRAMS = {
    'asr_inference_duration_seconds': 'Whisper inference time, completed jobs',
    'asr_preprocessing_duration_seconds': 'Audio decode and normalization time',
    'asr_vad_duration_seconds': 'Voice activity detection time',
    'asr_queue_wait_seconds': 'Time before first worker claim',
    'asr_job_duration_seconds': 'End-to-end time for terminal jobs, including queue and retries',
}


def observe(pipe, name, value):
    key = 'asr:hist:' + name
    pipe.hincrbyfloat(key, 'sum', value)
    pipe.hincrby(key, '+Inf', 1)
    for bound in BOUNDS:
        if value <= bound:
            pipe.hincrby(key, str(bound), 1)


class RedisCollector:
    def __init__(self, store):
        self.store = store

    def collect(self):
        client = self.store.redis
        pipe = client.pipeline(transaction=False)
        for status in ('queued', 'retrying', 'processing'):
            pipe.scard('asr:state:' + status)
        for status in ('failed', 'completed'):
            pipe.get('asr:metrics:jobs_' + status)
        for name in HISTOGRAMS:
            pipe.hgetall('asr:hist:' + name)
        queued, retrying, processing, failed, completed, *histograms = pipe.execute()
        yield GaugeMetricFamily('asr_queue_length', 'Jobs awaiting a worker or retry', value=queued + retrying)
        yield GaugeMetricFamily('asr_jobs_processing', 'Jobs holding a worker lease', value=processing)
        for status, value in [('failed', failed), ('completed', completed)]:
            yield CounterMetricFamily('asr_jobs_' + status, 'Terminal jobs', value=int(value or 0))
        # Only fixed service heartbeat keys; never use job IDs as metric labels.
        workers = sum(client.exists(key) for key in client.scan_iter('asr:worker:*'))
        yield GaugeMetricFamily('asr_workers_alive', 'Worker parent heartbeats in the last 15 seconds', value=workers)
        for (name, description), raw in zip(HISTOGRAMS.items(), histograms):
            values = {k.decode(): float(v) for k, v in raw.items()}
            buckets = [(str(b), values.get(str(b), 0)) for b in BOUNDS]
            buckets.append(('+Inf', values.get('+Inf', 0)))
            yield HistogramMetricFamily(name, description, buckets=buckets, sum_value=values.get('sum', 0))


def create_metrics(store):
    registry = CollectorRegistry()
    registry.register(RedisCollector(store))
    requests = Counter('asr_requests_total', 'HTTP requests', ['method', 'route', 'status'], registry=registry)
    duration = Histogram('asr_request_duration_seconds', 'HTTP response latency', ['method', 'route'],
                         buckets=BOUNDS, registry=registry)
    return registry, requests, duration
