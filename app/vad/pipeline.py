import time
from app.vad.segments import pad_segments, seconds


def transcribe(model, audio, detector=None, sample_rate=16000, pre_ms=0, post_ms=0, **options):
    if sample_rate != 16000:
        raise ValueError('Whisper requires 16000 Hz audio')
    started = time.perf_counter()
    segments = detector(audio, sample_rate) if detector else ([dict(start=0, end=len(audio))] if len(audio) else [])
    segments = pad_segments(segments, len(audio), sample_rate, pre_ms, post_ms)
    vad_time = time.perf_counter() - started
    chunks = []
    asr_start = time.perf_counter()
    for segment, timestamp in zip(segments, seconds(segments, sample_rate)):
        result = model.transcribe(audio[segment['start']:segment['end']], **options)
        chunks.append(dict(**timestamp, text=result['text'].strip()))
    asr_time = time.perf_counter() - asr_start
    return dict(transcript=' '.join(c['text'] for c in chunks if c['text']),
                segments=seconds(segments, sample_rate), chunks=chunks,
                vad_time=vad_time, asr_time=asr_time,
                inference_time=time.perf_counter() - started,
                retained_seconds=sum(s['end'] - s['start'] for s in segments) / sample_rate)
