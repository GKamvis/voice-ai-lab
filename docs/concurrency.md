# Eyni anda 10 audio gəlsə nə baş verir?

Bu implementasiyada tək Uvicorn prosesi, tək model və tək ASR worker var:

```text
Client → async FastAPI → limitli asyncio.Queue → ASR worker → Whisper → Future → response
```

Boş sistemə 10 request gəldikdə worker birini emal edir, qalanları qəbul olunma sırası ilə gözləyir. Şəbəkə/upload sırası client-in nömrələmə sırası ilə eyni olmaya bilər. Default queue tutumu 10 **gözləyən** işdir; aktiv iş buna daxil deyil. Model çağırışları üst-üstə düşmür. Hər iş təxminən T saniyə çəkirsə, 10 request üçün son cavab təxminən 10T, orta latency isə təxminən 5.5T olar. Bunlar eyni müddətli işlər üçün təxminlərdir; faktiki ölçülər `benchmark/load_results/` altındadır.

## Anlayışları kodla əlaqələndir

| Anlayış | Bu API-də mənası |
| --- | --- |
| sync | Adi funksiya çağırışı bitənədək çağıran thread gözləyir. |
| async | Endpoint `await future` zamanı event loop-u digər request-lərə verir. |
| concurrency | Bir neçə request eyni vaxt intervalında sistemdədir: biri işlənir, digərləri gözləyir. |
| parallelism | Bir neçə hesablamanın həqiqətən eyni anda icrası. Bu layihədə ayrı request-lərin inference-i paralel deyil; PyTorch bir inference daxilində CPU thread-ləri istifadə edə bilər. |
| blocking operation | ffmpeg gözləməsi, sinxron disk işi və model çağırışı çağıran thread-i tutur. |
| worker | Queue-dan bir iş götürüb bitənədək növbəti işi götürməyən consumer. Uvicorn worker prosesi ilə eyni anlayış deyil. |
| queue | İşləri yaddaşda FIFO sırası ilə saxlayan `asyncio.Queue`. |
| CPU-bound | Whisper CPU inference-i əsasən hesablama tələb edir. |
| I/O-bound | Şəbəkədən audio/nəticə gözləmək kimi işlərdə vaxt əsasən giriş-çıxışa gedir. |
| backpressure | Qəbul sürəti emaldan yüksəkdirsə queue böyüyür; dolanda `503` və `Retry-After: 1` qaytarılır. Client gecikmə/backoff tətbiq etməlidir. |
| timeout | Queue-ya qəbuldan nəticəyədək vaxt limiti; keçilərsə `504`. |
| request ID | Hər endpoint çağırışına serverin yaratdığı UUID; logları və cavabı əlaqələndirir. |

**`async ≠ parallel model inference`.** `async def` içində birbaşa `service.transcribe(...)` yazmaq blocking işi event loop üzərində icra edər. Burada worker `await asyncio.to_thread(...)` istifadə edir: event loop sərbəst qalır, amma consumer nəticəni gözlədiyindən ikinci inference başlamır. `to_thread` CPU işinin avtomatik daha sürətli olmasına zəmanət vermir.

Praktik yoxlama: load test zamanı loglarda çoxlu `received`/`queued`, amma hər `processing` üçün növbəti `processing`-dən əvvəl `completed` görəcəksən. `/health` emal zamanı cavab verə bilir. Testlər worker-i müvəqqəti saxlayaraq health cavabını, ardıcıl emalı, dolu queue-nu və timeout-u yoxlayır.

```sh
curl http://localhost:8000/health
# Başqa terminalda:
docker compose logs -f
```

Log mərhələləri: `[request_id=UUID] received`, `queued queue_size=N`, `processing`, `preprocessing`, `inference`, `completed` (və ya `failed`/`timeout`). `processing_time` preprocessing + VAD + inference vaxtıdır, queue gözləməsini əhatə etmir. Client latency isə upload + queue + emal + cavab ötürülməsini əhatə edir. Uğurlu JSON-da `request_id`, bütün handler cavablarında `X-Request-ID` var; FastAPI-nin handler-dən əvvəl yaratdığı validation xətaları istisnadır.

## Başlat və ölç

Layihənin `compose.yaml` olan qovluğunda:

```sh
.venv/bin/pip install -r requirements-api.txt  # httpx daxil olmaqla
ASR_MODEL=base docker compose up --build
# Default model small-dır:
# docker compose up --build

docker compose ps
docker compose logs -f
.venv/bin/python tests/load_test.py --audio samples/01_clean.wav --warmup
```

`Dockerfile` Python, ffmpeg, paketlər və koddan **image necə hazırlanır** sualına cavab verir. `compose.yaml` həmin image-dən **container necə başladılır**, port, environment, model cache volume və healthcheck necə bağlanır suallarını təsvir edir. Hazırda bir servis var, sonradan ayrıca queue/backend əlavə edilə bilər. Model çəkiləri ilk startup zamanı endirilə bilər, sonrakı startlarda volume-dan oxunur.

Docker olmadan:

```sh
ASR_MODEL=base .venv/bin/python -m uvicorn app.api.main:app --port 8000 --workers 1
```

Konfiqurasiya: `ASR_MODEL=small`, `ASR_QUEUE_SIZE=10`, `ASR_REQUEST_TIMEOUT=300` (saniyə). Köhnə `WHISPER_MODEL` yalnız `ASR_MODEL` yoxdursa fallback-dır. Compose shell dəyərini `${ASR_MODEL:-small}` vasitəsilə ötürür.

Load test 1, 5 və 10 request-lik üç burst göndərir. Hər burst ayrıca ölçülür, növbəti əvvəlki cavablar bitdikdən sonra başlayır. `--warmup` bir ölçülməyən request göndərir. HTTP connection limiti ən böyük burst-ə uyğundur. `summary.csv` və `summary.md`: avg/min/max latency, total time, success/failure; `runs.json`: hər request-in statusu, ID-si, cavabı və ölçüsü. Orta/min/max latency uğurlu və uğursuz **bütün** cəhdlər üçündür. Təkrar işə salmaq eyni output-u əvəz edir; `--output` ilə ayrı qovluq seç. Xəta varsa exit code 1 olur. `--timeout` httpx şəbəkə əməliyyatlarının vaxt limitidir.

Backpressure təcrübəsi üçün servisi `ASR_QUEUE_SIZE=2` ilə başlat və 10 request göndər; bir hissəsi `503` alacaq. `ASR_REQUEST_TIMEOUT=0.1` timeout-u göstərir. **Timeout işləyən native inference-i dayandırmır**: worker onu bitirir, sonra növbəti işə keçir; hələ başlamamış timeout olmuş işlər götürüləndə atlanır. Bu səbəbdən uğursuz burst-dən sonra yeni müqayisədən əvvəl worker-in boşalmasını gözlə.

Queue prosesdaxili və müvəqqətidir; restart zamanı işlər itir. `--workers 2` ayrı model və ayrı queue yaradar, tək ümumi queue deyil. Shutdown queue-nu boşaldır; Compose 6 dəqiqə gözləyir, daha uzun işlər zorla dayandırıla bilər. Upload multipart parsing-i handler-dən əvvəl baş verir; bu queue limiti bütün HTTP upload-lar üçün yaddaş/disk limiti deyil. Deployment üçün ingress səviyyəsində body və connection limitləri ayrıca lazımdır.
