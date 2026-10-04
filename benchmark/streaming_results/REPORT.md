# Streaming sınağı — 2026-10-04

Whisper base, CPU / 4 thread, Azərbaycan dili. Mövcud 13,33 saniyəlik `04_numbers_names.wav`; bir təkrar. İstinad LocalDoc transkriptidir, əl ilə yoxlanılmayıb. Mikrofon cihazları aşkarlandı, canlı istifadəçi danışığı qeydə alınmadı.

| Method | WER | Simulyasiya latency | RTF | Processing |
|---|---:|---:|---:|---:|
| No VAD | 80,77% | 1,247 s | 0,310 | 4,128 s |
| VAD | 76,92% | 3,050 s | 0,205 | 2,738 s |
| VAD + overlap | 96,15% | 4,802 s | 0,337 | 4,488 s |

Cədvəlin latency-si faylın sonundan son transkriptə qədər modelləşdirilmiş tək-worker cədvəlidir. Emal vaxtları faktiki ölçülüb. VAD-sız emal danışıq davam edərkən başlayır, VAD variantları endpoint-i gözləyir; buna görə daha az emal vaxtı daha az yekun latency demək deyil.

## Real vaxt sürətli replay

Eyni WAV 30 ms frame-lərlə wall-clock sürətində streaming pipeline-dan keçirildi:

- VAD speech span: 12,84 s
- Endpoint delay: 696,9 ms
- ASR queue: 2,7 ms
- ASR inference: 2831,6 ms
- Ümumi latency: 3531,2 ms

Bunlar faktiki replay ölçüləridir, mikrofon ölçüləri deyil. Speech end son RMS-positive frame-dir, əl annotasiyası deyil. Replay ASR-ə endpoint səssizliyini də verir; offline benchmark son speech frame-dən sonra 150 ms saxlayır. Buna görə iki inference vaxtı tam eyni input-un ölçüsü deyil.

## Chunk sərhədləri

5 saniyə, overlapsız: 0–5, 5–10, 10–13,33. Ayrı overlap sınağı: 0–5, 4–9, 8–13, 12–13,33.

- Overlapsız çıxışda Python sözü 10 saniyə ətrafında `pay` / `Pək təm` kimi parçalanır.
- Overlap çıxışında `Payton` daha bütöv gəlir, lakin `o zamanlar` təkrarı və son `nəşrətti` variantı yaranır.
- VAD-sız overlap WER: 88,46%; overlapsız: 80,77%. Bu nümunədə overlap ümumi keyfiyyəti yaxşılaşdırmadı.
- VAD + overlap son qısa 12–13,11 hissəsini də emal edir; bu əlavə ASR çağırışı və təkrar mətn yaradır. Son qısa pəncərəni birləşdirmək növbəti optimizasiya ola bilər.
- Dəqiq suffix/prefix dedup bu fərqli yazılışları silmədi: raw WER və merged WER eynidir. Avtomatik birləşdirmə problemi həll olunmuş sayılmamalıdır.

Bunlar chunk mətnlərinin müşahidəsidir; word-level zaman annotasiyası olmadığı üçün bütün səhvləri sərhədlərə aid etmək olmaz. Tam mətnlər, pəncərələr və vaxtlar JSON fayllarındadır. 9 unit test keçdi. Canlı 10–20 saniyəlik istifadəçi səsi və onun əl ilə yazılmış istinadı ilə ayrıca təsdiq qalır.
