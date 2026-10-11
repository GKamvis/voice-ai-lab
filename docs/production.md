# Linux VPS deployment (nəzəri/runbook)

Bu repository lokal işlədilmək üçün hazırlanıb. Hazır VPS/domen ayrılmayıb; aşağıdakı addımlar öz serverində deploy edən istifadəçi üçündür. Real public HTTPS sertifikatı və xarici firewall yoxlaması server olmadan təsdiqlənmir.

## Hazırlıq

```sh
uname -a
docker --version
docker compose version
free -h
df -h
```

Ən azı 4 CPU, 6 GB RAM və image/model/cache üçün 10 GB boş diskdən başla, öz audio batch-inlə ölç. Worker 3 GB container limiti ilə başlayır; böyük model üçün artır. Domen A/AAAA qeydləri serverə yönəlməli, TCP 80/443 (HTTP3 üçün UDP 443) açıq olmalıdır. SSH girişini məhdudlaşdır. Redis, API, Prometheus portlarını public firewall-da açma.

```sh
git clone https://github.com/GKamvis/voice-ai-lab.git
cd voice-ai-lab
cp .env.prod.example .env
chmod 600 .env
# .env-də API_DOMAIN, API_TOKEN, GRAFANA_ADMIN_PASSWORD doldur.
# Random token üçün: openssl rand -hex 32

docker compose -f compose.prod.yaml config --quiet
docker compose -f compose.prod.yaml up -d --build
docker compose -f compose.prod.yaml ps
```

`Internet → HTTPS/Caddy → speech-api → Redis/Celery → VAD/Whisper → nəticə`.

Production Compose tələb olunan sirrlər boş olduqda start etmir. `/jobs` və `/jobs/{id}` Bearer token tələb edir. Bu bir owner üçün shared-token auth-dur; çoxistifadəçili/tenant sistemi deyil. Eyni token sahibi bütün job-ları oxuya bilər. `/health` public; `/metrics`, `/ready` və docs Caddy-dən public açılmır. Redis üçün heç bir host port publish edilmir. Grafana yalnız host loopback 3000-dən açılır (SSH tunnel istifadə et). Caddy avtomatik HTTPS və 26 MB body limiti tətbiq edir.

## Production smoke

```sh
curl --fail https://api.example.com/health
curl --fail -H "Authorization: Bearer $API_TOKEN" \
  -F file=@samples/01_clean.wav https://api.example.com/jobs
curl --fail -H "Authorization: Bearer $API_TOKEN" \
  https://api.example.com/jobs/JOB_ID
# status completed olana qədər poll et; result.text cavabda olur.
docker compose -f compose.prod.yaml logs --tail=50 asr-worker
# Redis host mapping boş olmalıdır:
docker compose -f compose.prod.yaml port redis 6379
# Xarici maşından 6379 TCP bağlantısı alınmamalıdır.
# curl --fail HTTPS sertifikatını da doğrulayır; -k istifadə etmə.
docker compose -f compose.prod.yaml restart speech-api
curl --fail https://api.example.com/health
```

Tokeni shell history-yə literal yazma. `scripts/load_jobs.py --url https://api.example.com ...` environment `API_TOKEN` oxuyur.

Worker stop/start/crash ssenarilərini əvvəl lokal izolə olunmuş integration project-də et. Production-da planlı restart zamanı `stop_grace_period=11m` aktiv işə vaxt verir. Host/Redis outage zamanı AOF volume saxlanmalıdır. `down -v` production data-nı silir, deployment əmri kimi istifadə etmə.

## CI/CD və geri dönüş

GitHub Actions CI test/build/integration-i avtomatik yoxlayır. Server olmadığı üçün avtomatik CD və SSH secrets qoşulmayıb. Öz serverində yaşıl commit SHA seçərək manual deploy:

```sh
git fetch origin
# CI-si yaşıl olan seçilmiş commit:
git checkout COMMIT_SHA
docker compose -f compose.prod.yaml up -d --build
```

Əvvəlki işlək SHA-nı qeyd et. Rollback üçün həmin SHA-nı checkout edib eyni əmri işlət; Redis volume-ni qoruyub saxla. Bu Compose deploy-u zero-downtime zəmanəti vermir. Data schema dəyişikliklərində əvvəl backup və migration uyğunluğunu yoxla.

Redis data, Caddy sertifikat volume-si və lazım gələrsə Grafana volume-si üçün öz backup/restore prosedurunu qur. Queue/audio/nəticələr şəxsi məlumat daşıya bilər; backup-a giriş və saxlanma müddəti ayrıca idarə edilməlidir.
