# voice-ai-lab

## VAD təcrübəsi

Audio → 30 ms frame → RMS → speech/silence → segmentlər → Whisper → birləşdirilmiş mətn.

Quraşdırma (lokal Whisper; API açarı lazım deyil):

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-vad.txt
.venv/bin/python -m samples.make_vad_fixture
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m benchmark.vad_compare --model base --repeats 3
# İstəyə görə daha böyük model:
.venv/bin/python -m benchmark.vad_compare --model small --repeats 3 --output benchmark/vad_results_small
# Frame cədvəli və timestamp JSON:
.venv/bin/python -m app.vad.energy_vad samples/vad_fixture.wav --threshold 0.03 --segments benchmark/vad_results/energy_segments.json
# Yalnız VAD müqayisəsi:
.venv/bin/python -m benchmark.vad_compare --vad-only
```

İlk Whisper istifadəsi model çəkilərini endirə bilər. Fixture PCM16 WAV-dan birbaşa oxunur.

- `app/vad/energy_vad.py`: float mono audio üçün RMS və ciddi `RMS > threshold` qərarı. Son natamam frame saxlanılır. Heç bir smoothing tətbiq edilmir: bu, qərarın necə yarandığını göstərən sadə təcrübədir.
- `app/vad/silero_vad.py`: Silero 6.2.3, threshold 0.5, minimum speech 250 ms, minimum silence 100 ms, daxili padding 0. [Rəsmi API](https://github.com/snakers4/silero-vad/blob/master/src/silero_vad/utils_vad.py).
- `app/vad/pipeline.py`: hər segment ayrıca Whisper-ə verilir. Mətnlər zaman sırası ilə birləşdirilir. Səssizlikdə ASR çağırılmır. Daxildə sample indeksləri, JSON-da saniyələr istifadə edilir.
- `app/vad/segments.py`: 200 ms pre / 300 ms post padding, audio sərhədlərində kəsmə, üst-üstə düşən segmentləri birləşdirmə. Bu, eyni audionun iki dəfə transkripsiyasının qarşısını alır.

### Test audiosu

`samples/vad_fixture.wav` — 44,65 saniyə: 5 s silence → 7,01 s clean speech → 2 s silence → 5,31 s quiet speech → 7 s noise → 13,33 s speech + noise → 5 s silence.

Mövcud LocalDoc yazılarından hazırlanır. Quiet speech gain=0.08, noise RMS=0.02, speech+noise nominal SNR=8 dB, random seed=42. Bu, təbii zəif danışıq və real mühit küyü deyil. Mənbə, lisenziya, dəyişikliklər və istinad transkripti `samples/vad_fixture.json` daxilindədir. Mənbə transkriptləri əl ilə yoxlanılmayıb. Blok sərhədləri dəqiq speech annotasiyası deyil; blokun içində pauzalar ola bilər.

### Nəticə faylları

`benchmark/vad_results/`:

- `frames_0.01.csv`, `frames_0.03.csv`, `frames_0.05.csv`: time, RMS, speech/silence və sample sərhədləri; eyni audio üzərində threshold müqayisəsi.
- `detections.json`: hər detektorun saniyə ilə segmentləri və təkrar VAD vaxtları.
- `coverage.csv`: hər blokun speech kimi saxlanılan hissəsi. Bu göstərici precision/recall deyil.
- `runs.json`: hər təkrarın tam transkripti, segmentlər, segment mətnləri, WER/CER və vaxtlar.
- `summary.csv`: üç təkrarın medianı və minimum/maksimum vaxtı.
- `environment.json`: versiyalar, cihaz və decoding parametrləri.

Beş variant: VAD-sız, Energy 0.03, Energy + padding, Silero, Silero + padding. Variant sırası hər təkrarda deterministik qarışdırılır. CPU, 4 thread, eyni Whisper modeli və decoding parametrləri istifadə edilir. Model/audio yükləmə və isinmə ölçülmür; VAD, padding, kəsmə, ASR və birləşdirmə ümumi inference vaxtına daxildir. `RTF = ümumi inference vaxtı / ilkin audio müddəti`.

WER/CER əvvəlki `benchmark/evaluate.py` normalizasiyasını və edit-distance hesablamasını istifadə edir: Azərbaycan registr qaydaları, durğu işarələrinin çıxarılması, CER-də boşluqların çıxarılması. Padding accuracy-yə kömək edə və segment sayını azalda bilər; sürət üstünlüyü əvvəlcədən qəbul edilmir. Tək süni nümunə üzrə nəticə ümumi keyfiyyət zəmanəti deyil.

## Real-time mikrofon və streaming benchmark

```sh
.venv/bin/pip install -r requirements-streaming.txt
# 16 kHz mono, 480 sample = 30 ms; 690 ms silence → endpoint
.venv/bin/python -m app.streaming.streaming_asr --seconds 30
# Mikrofon əvəzinə eyni pipeline-a real vaxt sürəti ilə WAV:
.venv/bin/python -m app.streaming.streaming_asr --wav samples/04_numbers_names.wav --output benchmark/streaming_results/realtime_replay.json
.venv/bin/python -m benchmark.streaming_compare
# Öz 10–20 saniyəlik yazınız və əl ilə yoxlanılmış transkript:
.venv/bin/python -m benchmark.streaming_compare --audio benchmark/live_results.wav --reference reference.txt
```

`--device` ilə sounddevice cihaz indeksini seçmək mümkündür. macOS mikrofon icazəsi istəyə bilər. Model əvvəlcədən yüklənir və isindirilir. Mikrofon hazır mesajından sonra danışın; Ctrl-C yazını bitirir və gözləyən ASR işlərini tamamlayır. WAV və JSON `benchmark/live_results.*` fayllarına yazılır. Təkrar çağırış həmin output-u əvəz edir.

Mövcud RMS detektoru (`threshold=0.03`) hər frame-də işləyir. 210 ms pre-roll söz başlanğıcını saxlayır; qısa pauzalar audio buffer-də qalır. 690 ms səssizlik endpoint yaradır. 30 saniyəlik limit uzun fasiləsiz çıxışı hissələrə bölür (`max_duration`); EOF ayrıca qeyd olunur, bunlar təbii endpoint deyil. Küy speech sayıla bilər, zəif səs isə itə bilər; threshold mikrofonun gain-inə həssasdır.

Capture callback yalnız frame-ləri bounded queue-ya əlavə edir; ASR ayrıca thread-də işləyir. Capture və ASR növbəsi daşanda səssiz frame itirmək əvəzinə xəta verilir. Audio sample vaxtı PortAudio ADC saatından monotonic saata çevrilir. JSON-da speech end, endpoint aşkarlanması, ASR start və transcript ready timestamp-ləri saxlanılır. `total_latency = endpoint_delay + queue_delay + asr_inference`. Speech duration ilk və son speech frame arasındakı müddətdir, aradakı pauzalar daxildir. Danışığın sonu RMS-in son speech frame-i ilə təxmin olunur; əl ilə annotasiya edilmiş akustik son deyil. WAV replay nəticələri real wall-clock ölçüləridir, mikrofon/ADC latency-sini ölçmür.

Benchmark-da `No VAD` 5 saniyəlik hissələri gəldikcə transkripsiya edir. `VAD` endpoint-də bütöv utterance verir. `VAD + overlap` endpoint-də həmin utterance-ı 5 saniyəlik, 1 saniyə overlap olan hissələrə bölür. Sonuncu strategiya kontekst müqayisəsidir və utterance bitməmiş nəticə vermir. Ayrı `boundary_overlap.json` VAD-sız 0–5, 4–9, 8–13… pəncərələrini yoxlayır: bunu `No VAD` ilə müqayisə etmək overlap təsirini ayırır.

`runs.json` bütün chunk mətnlərini və sərhədlərini saxlayır. Overlap birləşdirməsi yalnız normallaşdırılmış dəqiq suffix/prefix uyğunluğunu silir; ASR eyni sözü fərqli yazarsa dublikat qala bilər, həqiqi təkrar da silinə bilər. Raw transkript və raw WER buna görə ayrıca saxlanılır. Söz timestamp-ləri/əl annotasiyası olmadan konkret səhvin sərhəd səbəbli olduğunu qəti demək olmaz.

`summary.csv`: WER, processing time, RTF və **simulyasiya edilmiş** latency. ASR vaxtı faktiki ölçülür; stream cədvəli audio sample saatı və tək ASR worker əsasında modelləşdirilir. Latency fayl sonundan son nəticəyədək hesablanır; canlı latency deyil. RTF = VAD + ASR + birləşdirmə emal vaxtı / ilkin audio müddəti. Audio/model yükləmə və warm-up daxil deyil. VAD üçün 1 saniyə səssizlik əlavə edilir, RTF denominator-una daxil edilmir. Bir nümunə, bir təkrar və yoxlanılmamış dataset transkripti ümumi keyfiyyət nəticəsi vermir.

## Concurrent API, queue və Docker Compose

[Təcrübə və anlayışların izahı](docs/concurrency.md). Endpoint indi async-dir; limitli `asyncio.Queue` və tək ASR worker ilə request-lər ardıcıl emal edilir. UUID loglarda və response-da verilir.

```sh
ASR_MODEL=base docker compose up --build
docker compose ps
docker compose logs -f
# Ayrı terminalda:
.venv/bin/pip install -r requirements-api.txt
.venv/bin/python tests/load_test.py --audio samples/01_clean.wav --warmup
```

Ölçülər: [nəticə cədvəli](benchmark/load_results/summary.md), CSV və hər request üçün JSON. Default `ASR_QUEUE_SIZE=10`, `ASR_REQUEST_TIMEOUT=300`; dolu queue `503`, vaxt limiti `504` qaytarır. Docker image default olaraq tək Uvicorn worker ilə işləyir.
