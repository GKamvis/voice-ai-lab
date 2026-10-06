# Lokal Whisper base — CPU, 4 thread

Audio: `samples/01_clean.wav`; bir warm-up, hər səviyyədə bir burst. Docker daxilində ölçülməyib.

| Concurrent requests | Avg latency | Min latency | Max latency | Total time | Success | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2.233s | 2.233s | 2.233s | 2.233s | 1 | 0 |
| 5 | 6.645s | 2.206s | 11.109s | 11.110s | 5 | 0 |
| 10 | 12.261s | 2.225s | 22.284s | 22.286s | 10 | 0 |
