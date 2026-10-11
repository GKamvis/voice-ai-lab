FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HOME=/home/asr
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 asr
COPY requirements-api.txt requirements-vad.txt ./
# Avoid downloading CUDA runtimes for a CPU deployment.
RUN pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements-api.txt
COPY --chown=asr:asr app ./app
RUN mkdir -p /home/asr/.cache/whisper && chown -R asr:asr /home/asr/.cache
USER asr
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
