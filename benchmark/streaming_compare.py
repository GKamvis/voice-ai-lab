"""Measured offline ASR with simulated serial stream scheduling (not live latency)."""
import argparse
import csv
import json
import platform
import time
from pathlib import Path
import numpy as np
from app.streaming.buffer import EndpointBuffer, SR, FRAME
from app.streaming.streaming_asr import load_model, OPTIONS
from benchmark.evaluate import normalize, edit_distance
from samples.make_vad_fixture import read_wav

ROOT = Path(__file__).resolve().parents[1]


def windows(length, size=5*SR, overlap=0):
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError('Invalid window or overlap')
    start = 0
    while start < length:
        end = min(length, start+size)
        yield start, end
        if end == length:
            break
        start += size-overlap


def merge_text(previous, current):
    # Conservative exact normalized suffix/prefix match; raw output also retained.
    left, right = previous.split(), current.split()
    for n in range(min(20, len(left), len(right)), 0, -1):
        if normalize(' '.join(left[-n:])) == normalize(' '.join(right[:n])):
            return ' '.join(left + right[n:])
    return ' '.join(left + right)


def make_jobs(audio, method):
    if method in ('No VAD', 'Boundary overlap'):
        overlap = SR if method == 'Boundary overlap' else 0
        return [(s, e, e/SR, None) for s, e in windows(len(audio), overlap=overlap)]
    endpoint = EndpointBuffer()
    utterances = []
    # Silence tail allows natural endpointing; original audio duration is denominator.
    padded = np.concatenate([audio, np.zeros(SR, dtype=np.float32)])
    for i in range(0, len(padded), FRAME):
        u = endpoint.push(padded[i:i+FRAME])
        if u:
            utterances.append(u)
    u = endpoint.flush()
    if u:
        utterances.append(u)
    jobs = []
    for u in utterances:
        # Keep short pauses, drop trailing endpoint silence from ASR input.
        end = min(len(audio), u.speech_end + round(.15*SR))
        if method == 'VAD':
            jobs.append((u.start, end, u.detected/SR, u.speech_end/SR))
        else:
            for s, e in windows(end-u.start, overlap=SR):
                jobs.append((u.start+s, u.start+e, u.detected/SR, u.speech_end/SR))
    return jobs


def run(model, audio, reference, method):
    begin = time.perf_counter()
    jobs = make_jobs(audio, method)
    vad_time = time.perf_counter()-begin
    chunks, text, raw = [], '', []
    worker_ready = 0.0
    for start, end, available, speech_end in jobs:
        before = time.perf_counter()
        result = model.transcribe(audio[start:end], **OPTIONS)
        elapsed = time.perf_counter()-before
        scheduled_start = max(available, worker_ready)
        worker_ready = scheduled_start+elapsed
        part = result['text'].strip()
        raw.append(part)
        text = merge_text(text, part) if method in ('VAD + overlap', 'Boundary overlap') else ' '.join(raw)
        chunks.append(dict(start=start/SR, end=end/SR, available=available,
                           speech_end=speech_end, text=part, inference=elapsed,
                           simulated_ready=worker_ready, queue_delay=scheduled_start-available))
    processing = time.perf_counter()-begin
    words = normalize(reference).split()
    return dict(method=method, WER=edit_distance(words, normalize(text).split())/len(words),
                raw_WER=edit_distance(words, normalize(' '.join(raw)).split())/len(words),
                transcript=text, raw_transcript=' '.join(raw), chunks=chunks,
                processing_time=processing, vad_time=vad_time, RTF=processing/(len(audio)/SR),
                simulated_latency_from_file_end=max(0, worker_ready-len(audio)/SR))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', default='base')
    p.add_argument('--audio', type=Path, default=ROOT/'samples/04_numbers_names.wav')
    p.add_argument('--reference', type=Path, help='UTF-8 ground truth text for custom WAV')
    p.add_argument('--output', type=Path, default=ROOT/'benchmark/streaming_results')
    a = p.parse_args()
    if a.reference:
        reference = a.reference.read_text().strip()
    else:
        sources = json.loads((ROOT/'samples/sources.json').read_text())
        match = next((s for s in sources['samples'] if a.audio.resolve() == (ROOT/'samples'/s['file']).resolve()), None)
        if match is None:
            p.error('Custom audio requires --reference')
        reference = match['transcript']
    if not normalize(reference):
        p.error('Reference must contain words')
    audio = read_wav(a.audio)
    if not len(audio):
        p.error('Empty audio')
    model = load_model(a.model)
    a.output.mkdir(parents=True, exist_ok=True)
    runs = []
    for method in ('No VAD', 'VAD', 'VAD + overlap'):
        result = run(model, audio, reference, method)
        runs.append(result)
        print(f"{method}: WER={result['WER']:.2%}, simulated latency={result['simulated_latency_from_file_end']:.3f}s, RTF={result['RTF']:.3f}, processing={result['processing_time']:.3f}s", flush=True)
        (a.output/'runs.json').write_text(json.dumps(runs, ensure_ascii=False, indent=2))
    boundary = run(model, audio, reference, 'Boundary overlap')
    (a.output/'boundary_overlap.json').write_text(json.dumps(boundary, ensure_ascii=False, indent=2))
    print(f"Boundary overlap: WER={boundary['WER']:.2%}, raw WER={boundary['raw_WER']:.2%}", flush=True)
    columns = ['method', 'WER', 'raw_WER', 'simulated_latency_from_file_end', 'RTF', 'processing_time']
    with (a.output/'summary.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(runs)
    (a.output/'environment.json').write_text(json.dumps(dict(model=a.model, device='cpu', threads=4,
        options=OPTIONS, platform=platform.platform(), audio=str(a.audio), duration=len(audio)/SR,
        reference=reference, frame_ms=30, silence_ms=690, threshold=.03,
        latency='Simulated serial worker scheduling from file end; measured ASR inference; excludes capture and OS scheduling.',
        repeats=1), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
