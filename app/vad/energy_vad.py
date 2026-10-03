"""Educational RMS detector. Input: mono float audio normalized to [-1, 1]."""
import numpy as np


def validate_audio(audio, sample_rate):
    audio = np.asarray(audio)
    if sample_rate <= 0 or audio.ndim != 1:
        raise ValueError('Expected mono audio and a positive sample rate')
    if not np.issubdtype(audio.dtype, np.floating):
        raise ValueError('Normalize PCM to floating point [-1, 1] first')
    if not np.all(np.isfinite(audio)) or np.any(np.abs(audio) > 1):
        raise ValueError('Audio must be finite and within [-1, 1]')
    return audio


def rms(frame):
    frame = np.asarray(frame, dtype=np.float64)
    return float(np.sqrt(np.mean(frame ** 2))) if frame.size else 0.0


def frame_decisions(audio, sample_rate=16000, threshold=0.03, frame_ms=30):
    audio = validate_audio(audio, sample_rate)
    if not np.isfinite(threshold) or threshold < 0 or not np.isfinite(frame_ms) or frame_ms <= 0:
        raise ValueError('Invalid threshold or frame duration')
    size = max(1, round(sample_rate * frame_ms / 1000))
    rows = []
    for start in range(0, len(audio), size):
        end = min(start + size, len(audio))
        value = rms(audio[start:end])
        rows.append(dict(start=start, end=end, time=start / sample_rate,
                         rms=value, result='speech' if value > threshold else 'silence'))
    return rows


def speech_segments(audio, sample_rate=16000, threshold=0.03, frame_ms=30):
    segments = []
    for row in frame_decisions(audio, sample_rate, threshold, frame_ms):
        if row['result'] == 'speech':
            if segments and segments[-1]['end'] == row['start']:
                segments[-1]['end'] = row['end']
            else:
                segments.append(dict(start=row['start'], end=row['end']))
    return segments


def main():
    import argparse
    import json
    import wave
    from pathlib import Path
    from app.vad.segments import seconds
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path)
    parser.add_argument('--threshold', type=float, default=0.03)
    parser.add_argument('--frame-ms', type=float, default=30)
    parser.add_argument('--segments', type=Path, help='Optional output JSON')
    args = parser.parse_args()
    with wave.open(str(args.audio), 'rb') as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            parser.error('Expected mono PCM16 WAV')
        sample_rate = handle.getframerate()
        audio = np.frombuffer(handle.readframes(handle.getnframes()), dtype='<i2').astype(np.float32) / 32768
    print('Time      RMS       Result')
    for row in frame_decisions(audio, sample_rate, args.threshold, args.frame_ms):
        print(f"{row['time']:<9.2f} {row['rms']:<9.6f} {row['result']}")
    if args.segments:
        result = speech_segments(audio, sample_rate, args.threshold, args.frame_ms)
        args.segments.write_text(json.dumps({'segments': seconds(result, sample_rate)}, indent=2))


if __name__ == '__main__':
    main()
