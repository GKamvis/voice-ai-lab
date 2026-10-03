"""Run from project root: python -m benchmark.vad_compare."""
import argparse
import csv
import importlib.metadata
import json
import platform
import random
import statistics
import time
from pathlib import Path

import numpy as np
import torch
import whisper

from app.vad.energy_vad import frame_decisions, speech_segments
from app.vad.pipeline import transcribe
from app.vad.segments import seconds
from app.vad.silero_vad import SileroVAD
from benchmark.evaluate import normalize, edit_distance
from samples.make_vad_fixture import read_wav

ROOT = Path(__file__).resolve().parents[1]


def save_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def errors(reference, prediction):
    ref, pred = normalize(reference), normalize(prediction)
    if not ref:
        raise ValueError('Reference must not be empty')
    return dict(WER=edit_distance(ref.split(), pred.split()) / len(ref.split()),
                CER=edit_distance(ref.replace(' ', ''), pred.replace(' ', '')) / len(ref.replace(' ', '')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='base', choices=['base', 'small'])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--vad-only', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'benchmark/vad_results')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    metadata = json.loads((ROOT / 'samples/vad_fixture.json').read_text())
    audio = read_wav(ROOT / 'samples' / metadata['audio_file'])
    duration = len(audio) / 16000
    detectors = {f'energy_{t}': (lambda a, sr=16000, t=t: speech_segments(a, sr, t)) for t in (0.01, 0.03, 0.05)}
    detectors['silero'] = SileroVAD()
    for threshold in (0.01, 0.03, 0.05):
        rows = frame_decisions(audio, threshold=threshold)
        save_csv(args.output / f'frames_{threshold}.csv', rows)
    detection, coverage = {}, []
    for name, detector in detectors.items():
        detector(audio)  # warm up model/runtime
        timings = []
        for _ in range(args.repeats):
            start = time.perf_counter()
            segments = detector(audio)
            timings.append(time.perf_counter() - start)
        detection[name] = dict(segments=seconds(segments), median_seconds=statistics.median(timings), times=timings)
        for block in metadata['blocks']:
            start, end = round(block['start'] * 16000), round(block['end'] * 16000)
            retained = sum(max(0, min(end, s['end']) - max(start, s['start'])) for s in segments)
            coverage.append(dict(detector=name, block=block['label'], start=block['start'], end=block['end'],
                                 retained_fraction=retained/(end-start), detector_seconds=statistics.median(timings)))
    save_csv(args.output / 'coverage.csv', coverage)
    (args.output / 'detections.json').write_text(json.dumps(detection, indent=2))
    if args.vad_only:
        return
    model = whisper.load_model(args.model, device='cpu')
    model.eval()
    options = dict(language='az', task='transcribe', fp16=False, temperature=0.0,
                   beam_size=5, condition_on_previous_text=False, verbose=None)
    variants = [('without_vad', None, 0, 0), ('energy', detectors['energy_0.03'], 0, 0),
                ('energy_padding', detectors['energy_0.03'], 200, 300),
                ('silero', detectors['silero'], 0, 0), ('silero_padding', detectors['silero'], 200, 300)]
    runs = []
    with torch.inference_mode():
        model.transcribe(audio[5*16000:12*16000], **options)
        for repeat in range(args.repeats):
            order = variants.copy()
            random.Random(42 + repeat).shuffle(order)
            for name, detector, pre, post in order:
                random.seed(42)
                np.random.seed(42)
                torch.manual_seed(42)
                result = transcribe(model, audio, detector, pre_ms=pre, post_ms=post, **options)
                result.update(variant=name, repeat=repeat+1, model=args.model, audio_duration=duration,
                              RTF=result['inference_time']/duration, **errors(metadata['transcript'], result['transcript']))
                runs.append(result)
                (args.output / 'runs.json').write_text(json.dumps(runs, ensure_ascii=False, indent=2))
                print(f"{name} [{repeat+1}]: {result['inference_time']:.2f}s WER={result['WER']:.2%} CER={result['CER']:.2%}", flush=True)
    summary = []
    for name, *_ in variants:
        subset = [r for r in runs if r['variant'] == name]
        summary.append(dict(variant=name, model=args.model, repeats=args.repeats,
                            **{key: statistics.median(r[key] for r in subset) for key in
                               ('audio_duration', 'inference_time', 'vad_time', 'asr_time', 'retained_seconds', 'RTF', 'WER', 'CER')},
                            min_time=min(r['inference_time'] for r in subset), max_time=max(r['inference_time'] for r in subset)))
    save_csv(args.output / 'summary.csv', summary)
    environment = dict(platform=platform.platform(), threads=4, device='cpu', options=options,
                       versions={p: importlib.metadata.version(p) for p in ('numpy', 'torch', 'openai-whisper', 'silero-vad')},
                       note='Warm inference, audio loading and model loading excluded. VAD, padding and per-segment ASR included. RTF uses original audio duration. Energy threshold 0.03, frames 30 ms. Padding 200/300 ms; overlapping ranges merged. Seeded shuffled variant order.')
    (args.output / 'environment.json').write_text(json.dumps(environment, indent=2))
    print(f'Results: {args.output}')


if __name__ == '__main__':
    main()
