"""All internal boundaries are half-open sample indices, not seconds."""
import math


def pad_segments(segments, audio_length, sample_rate=16000, pre_ms=0, post_ms=0):
    if sample_rate <= 0 or audio_length < 0 or any(not math.isfinite(x) or x < 0 for x in (pre_ms, post_ms)):
        raise ValueError('Invalid padding, sample rate or audio length')
    merged = []
    for segment in sorted(segments, key=lambda s: s['start']):
        if not 0 <= segment['start'] < segment['end'] <= audio_length:
            raise ValueError('Invalid segment boundaries')
        start = max(0, segment['start'] - round(pre_ms * sample_rate / 1000))
        end = min(audio_length, segment['end'] + round(post_ms * sample_rate / 1000))
        if merged and start <= merged[-1]['end']:
            merged[-1]['end'] = max(merged[-1]['end'], end)
        else:
            merged.append(dict(start=start, end=end))
    return merged


def seconds(segments, sample_rate=16000):
    return [dict(start=s['start'] / sample_rate, end=s['end'] / sample_rate) for s in segments]
