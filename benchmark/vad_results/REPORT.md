# VAD — real ölçmə nəticələri

44,65 saniyəlik süni şəraitli Azərbaycan dili audiosu; lokal Whisper base, CPU, 4 thread, 3 təkrarın medianı. Model və fayl yükləmə xaricdir; VAD və bütün segment ASR çağırışları daxildir.

| Variant | Vaxt (s) | RTF | WER | CER | Saxlanılan audio (s) |
|---|---:|---:|---:|---:|---:|
| without_vad | 20.39 | 0.457 | 84.62% | 123.90% | 44.650 |
| energy | 87.40 | 1.957 | 169.23% | 484.91% | 18.780 |
| energy_padding | 6.93 | 0.155 | 78.85% | 45.91% | 21.160 |
| silero | 22.43 | 0.502 | 67.31% | 146.23% | 24.768 |
| silero_padding | 8.79 | 0.197 | 73.08% | 32.39% | 27.356 |

Silero + 200/300 ms padding: 2.32× sürətli, vaxt 56.9% azdır. WER -11.54 faiz bəndi dəyişir; bu nümunədə accuracy pisləşmir. Padding-siz Silero daha yavaşdır və CER pisləşir. Energy padding-siz ən pis variantdır; xırda parçalar çoxsaylı ASR çağırışlarına və təkrar mətnə səbəb olur.

## Detektor müqayisəsi

Aşağıdakı faiz blok müddətinin speech kimi saxlanılan hissəsidir. Speech bloklarında pauzalar da var: bu, precision/recall və ya həqiqi speech recall ölçüsü deyil. Küy blokundakı Silero nəticəsinə əvvəlki nitqin sonundan keçən sərhəd də təsir edir.

| Blok | Energy 0.01 | Energy 0.03 | Energy 0.05 | Silero |
|---|---:|---:|---:|---:|
| clean_speech | 86.45% | 77.46% | 59.91% | 93.27% |
| noise | 100.00% | 0.14% | 0.00% | 6.97% |
| quiet_speech | 6.21% | 0.00% | 0.00% | 99.89% |
| speech_noise | 100.00% | 100.00% | 72.24% | 93.14% |
| VAD vaxtı | 6.28 ms | 6.42 ms | 6.31 ms | 154.67 ms |

0.01 küyün hamısını speech kimi seçir. 0.03 və 0.05 zəif nitqi tam itirir. 0.05 təmiz və küylü nitqdən daha çox hissəni çıxarır. Padding aşkarlanmayan bütöv zəif nitq blokunu geri qaytarmır.

## Məhdudiyyətlər

Bir 44,65 saniyəlik kompozit səs, süni ağ küy və gain ilə zəiflədilmiş nitq istifadə olunub. İstinad mətnləri əl ilə yoxlanılmayıb; WER/CER mənbə transkriptinə görədir. 100%-dən yüksək səhv faizi əlavə/təkrar söz və simvollardan yaranır. Hər variantın transkripti üç təkrarda eyni olub. Small üçün kod hazırdır, burada yalnız base ölçülüb. Vaxtlar bu cihaz və iş şəraitinə aiddir; ayrıca proses izolyasiyası tətbiq olunmayıb.

Tam nəticələr: `runs.json`, `summary.csv`, `coverage.csv`, `detections.json`, `environment.json`. Əsas edge-case testləri 4/4 keçdi; Silero üçün silence, sərhəd və state-reset yoxlamaları da keçdi.
