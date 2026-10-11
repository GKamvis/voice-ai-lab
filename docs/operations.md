# Speech AI: işlətmə və müşahidə

## Lokal Docker

Python/Whisper host-da lazım deyil. Docker Compose 2.24.4+ (`!override` integration test üçündür), ən az 4 CPU / 6 GB VM RAM və image/model üçün 8–10 GB boş disk tövsiyə olunur.

```sh
cp .env.example .env
docker compose up -d --build
docker compose ps
docker compose logs -f speech-api asr-worker
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl -F file=@samples/01_clean.wav http://localhost:8000/jobs
curl http://localhost:8000/jobs/JOB_ID
```

- API/docs: http://localhost:8000/docs
- Metrics: http://localhost:8000/metrics
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000/d/speech-ai (`admin` / `.env`-dəki `GRAFANA_ADMIN_PASSWORD`; lokal default `local-development-only`).
- İlk job zamanı `ASR_MODEL=small` çəkiləri yüklənir; model cache volume-də saxlanılır. İlk işə internet lazımdır. Növbəti işlər eyni model instance-dan istifadə edir.
- WAV/MP3, 25 MiB, 0.25–300 saniyə. Əvvəlcə normalizasiya, sonra Silero VAD və Whisper. Korlanmış audio qəbuldan sonra `failed` olur; boş və dəstəklənməyən fayl HTTP 400-dür.
- `/health` prosesin işlədiyini, `/ready` Redis-in əlçatanlığını göstərir. Worker vəziyyəti `asr_workers_alive` ilə ayrıca yoxlanılır.
- Köhnə `/transcribe` yerinə `/jobs` istifadə et; standart serverdə `/transcribe` HTTP 410 qaytarır. Köhnə queue kodu əvvəlki unit testlər və müqayisə üçün saxlanır.

## Reliability

`queued → processing → completed/failed`; müvəqqəti bağlantı və timeout xətaları `processing → retrying → processing` yaradır. Status sətirləri API-də kiçik hərflədir.

Redis DB 0 Celery broker, DB 1 job state/audio/outbox üçündür. Job, audio və outbox bir Redis transaction-da yazılır. HTTP 202 yalnız saxlanmadan sonra qaytarılır. API dispatcher brokerə göndərilməyən işi təkrar ötürür. Redis AOF `appendfsync always`, persistent volume və `noeviction` istifadə edir. Redis volume-ni silmək job-ları silir; volume backup ayrıca əməliyyatdır. Bu bir node sistemidir, HA deyil.

- **Retry/backoff:** transient xəta üçün 2, 4, 8 saniyə + jitter; maksimum 4 ümumi cəhd. Normal validation/inference xətası yenidən sınanmır.
- **Timeout:** soft 540 s, hard 600 s, lease 630 s, broker visibility 690 s. Qəza zamanı bərpa lease bitdikdən sonra başlayır; dərhal olmaya bilər. Model cold-start da task deadline-a daxildir.
- **Acknowledgment:** `acks_late` işi bitirdikdən sonra ACK verir; `reject_on_worker_lost` qəza zamanı redelivery-yə icazə verir. Redis outbox hard-timeout/itmiş broker mesajını da bərpa edir.
- **Idempotency:** `Idempotency-Key` ilə eyni audio eyni job ID qaytarır. Eyni açar + fərqli audio HTTP 409-dur. Açar daxil edilməsə hər sorğu yeni job-dur.
- **At-least-once:** qəza olmuş inference yenidən hesablana bilər; tam olaraq bir dəfə hesablama zəmanəti yoxdur. Lease token köhnə worker-in yeni nəticəni dəyişməsinə mane olur. Terminal nəticə dəyişməzdir.
- **Graceful shutdown:** Compose worker-ə 11 dəqiqə verir. `docker compose stop asr-worker` aktiv işi bitirməyə imkan verir; SIGKILL ayrıca sınaqdır.
- **Retention:** aktiv işlər silinmir, maksimum 20 aktiv iş (limit dolduqda 503). Audio terminal statusda dərhal silinir, nəticə və idempotency açarı 24 saat sonra expire olur. Redis AOF/backup-da köhnə audio fiziki silinənə/compact edilənə qədər qala bilər.

```sh
curl -H 'Idempotency-Key: recording-001' -F file=@samples/01_clean.wav http://localhost:8000/jobs
```

Loglar JSON-dur: `timestamp`, `level`, `event`, `request_id`, `job_id`, `model`, `processing_time`, `status`, `error`. Error yalnız təhlükəsiz kateqoriyadır. Fayl adı, transcript, exception mətnləri, request body, tokenlər loglanmır. Job ID-lər metrik label deyil.

## Load test və bottleneck

```sh
python scripts/load_jobs.py samples/01_clean.wav --concurrency 1 5 10 --output outputs/load.json
```

Öncə bir warm-up job işlət; cold və warm nəticələri qarışdırma. Script job tamamlanana qədər poll edir, yalnız submit vaxtını ölçmür. 1/5/10 kiçik smoke batch-dir: P95/P99 bu sayda job üçün statistik SLA deyil.

| Əlamət | Ehtimal və yoxlama |
|---|---|
| POST API P95 yüksəlir, queue və inference normaldır | API CPU/RAM, upload şəbəkəsi, Redis disk latency; API log müddəti ilə müqayisə et |
| Queue length/wait artır, API sürətlidir, worker alive > 0 | Worker throughput gələn job sayına çatmır; concurrency/model/CPU-nu yoxla |
| Worker alive = 0, queue artır | Worker dayanıb, boot/broker bağlantısını və container exit/OOM statusunu yoxla |
| Worker processing qalır, inference müddəti artır | Model/CPU bottleneck; audio müddəti, model ölçüsü, `docker stats` və resurs limitlərini müqayisə et |
| Preprocessing P95 artır, inference sabitdir | FFmpeg decode, fayl ölçüsü/formatı və CPU/disk |
| End-to-end artır, model vaxtı sabitdir | Queue gözləməsi, retry və ya cold-start; job attempts və event loglarını müqayisə et |

**Counter** artan saydır (`asr_requests_total`, `asr_jobs_failed_total`). **Gauge** cari vəziyyətdir (`asr_queue_length`, `asr_workers_alive`). **Histogram** vaxtları bucket-lərə yığır. P50 median, P95/P99 işlərin 95/99%-nin aşağı qaldığı həddir; Prometheus qiyməti bucket əsasında təxmin edir.

```promql
# Throughput (tamamlanan iş/s)
sum(rate(asr_jobs_completed_total[5m]))
# API P95 (submit), HTTP qəbul vaxtı
histogram_quantile(0.95, sum by(le)(rate(asr_request_duration_seconds_bucket{route="/jobs",method="POST"}[5m])))
# Job P95, queue + retries + processing
histogram_quantile(0.95, sum by(le)(rate(asr_job_duration_seconds_bucket[5m])))
# Terminal error rate
sum(rate(asr_jobs_failed_total[5m])) / clamp_min(sum(rate(asr_jobs_failed_total[5m]) + rate(asr_jobs_completed_total[5m])), 0.00001)
```

Worker histogram/counter-ları Redis-də atomik yığılır və bütün prefork proseslərini əhatə edir. Inference/VAD/preprocessing histogram-ları tamamlanmış işləri ölçür; uğursuz cəhdlərin inference vaxtı daxil deyil. Queue wait yalnız ilk worker claim-ə qədərdir. End-to-end terminal nəticəyə qədər bütün cəhdləri əhatə edir. Worker heartbeat worker parent-in yaşamasıdır, modelin mütləq sağlamlığı deyil.

API counter/histogram bir proses üçündür: konteyner başına bir Uvicorn process. API restart həmin counter-ları sıfırlayır (`rate` bunu nəzərə alır). Bir neçə API replica eyni Redis aqreqatlarını expose edər; worker aqreqatları üçün yalnız bir API scrape et, HTTP metriklərini replica-lar üzrə scrape et. Hazır Compose bir API-dir.

Prometheus üç alert rule yükləyir: API əlçatmaz, worker yoxdur, davamlı queue backlog. Alertmanager/email bildiriş kanalı konfiqurasiya edilməyib.

## Testlər

```sh
python -m pip install -r requirements.txt
pytest tests/ -v
ruff check app/ tests/
docker build -t voice-ai-lab:local -f docker/Dockerfile .
docker compose -p speech-test -f compose.yaml -f compose.test.yaml up -d --no-build --wait speech-api asr-worker
python scripts/check_recovery.py
docker compose -p speech-test -f compose.yaml -f compose.test.yaml down -v
```

Unit testlər Whisper-i mock edir. Integration ayrıca `speech-test` project/volume/18000 portu istifadə edir: real Redis, Celery prefork, FFmpeg; yalnız model mock-dur. Normal/corrupted audio, worker stop/start, Redis AOF restart və real worker SIGKILL yoxlanılır. Lease vaxtı bu testdə 40 saniyədir.

CI hər main/codex branch push və main PR üçün install → Ruff → Pytest → Compose validation → Docker build → integration recovery işlədir. Real Whisper benchmark CI daxilində edilmir.

## Docker olmadan macOS lokal alternativ

Üç terminalda, aktiv venv ilə:

```sh
mkdir -p outputs/redis
redis-server --bind 127.0.0.1 --port 16379 --dir "$PWD/outputs/redis" --appendonly yes --appendfsync always
# Digər iki terminalda eyni Redis ünvanlarını export et:
export REDIS_URL=redis://127.0.0.1:16379/0
export STATE_REDIS_URL=redis://127.0.0.1:16379/1
export ASR_MODEL=small
uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --no-access-log
# Üçüncü terminal:
celery -A app.jobs.celery_app:celery_app worker --pool=solo --concurrency=1 --loglevel=INFO
```

macOS `solo` yalnız development üçündür: prefork hard/soft time limitləri və worker heartbeat/inspect aktiv inference zamanı eyni davranmır. Reliability yoxlamaları Linux Docker prefork ilə edilir. Dayandırmaq üçün həmin terminalda Ctrl-C; disk çatışmazlığı ilə yarımçıq qalmış Docker build-i native server dayanandan sonra təkrarla.

Mənbələr: [Celery task acknowledgment/retry](https://docs.celeryq.dev/en/stable/userguide/tasks.html), [Celery configuration](https://docs.celeryq.dev/en/stable/userguide/configuration.html), [Prometheus histogram](https://prometheus.io/docs/practices/histograms/).
