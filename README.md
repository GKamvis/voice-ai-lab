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
