"""Compose existing attributed recordings; never synthesize reference transcripts."""
import json
import wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SR = 16000


def read_wav(path):
    with wave.open(str(path), 'rb') as f:
        if (f.getnchannels(), f.getsampwidth(), f.getframerate()) != (1, 2, SR):
            raise ValueError('Expected mono PCM16 16 kHz WAV')
        return np.frombuffer(f.readframes(f.getnframes()), dtype='<i2').astype(np.float32) / 32768


def main():
    source = json.loads((ROOT / 'samples/sources.json').read_text())
    items = {s['file']: s for s in source['samples']}
    clean = read_wav(ROOT / 'samples/01_clean.wav')
    technical = read_wav(ROOT / 'samples/05_technical.wav')
    long = read_wav(ROOT / 'samples/04_numbers_names.wav')
    rng = np.random.default_rng(42)
    parts, blocks, texts = [], [], []
    def add(label, audio, filename=None, modification=None):
        start = sum(len(a) for a in parts) / SR
        parts.append(audio.astype(np.float32))
        blocks.append(dict(label=label, start=start, end=start + len(audio) / SR,
                           source=filename, modification=modification))
        if filename:
            texts.append(items[filename]['transcript'])
    add('silence', np.zeros(5 * SR))
    add('clean_speech', clean, '01_clean.wav', 'unchanged')
    add('silence', np.zeros(2 * SR))
    add('quiet_speech', technical * 0.08, '05_technical.wav', 'gain 0.08')
    add('noise', rng.normal(0, 0.02, 7 * SR), modification='seed 42 white noise RMS 0.02')
    noise_rms = float(np.sqrt(np.mean(long ** 2))) / 10 ** (8 / 20)
    add('speech_noise', long + rng.normal(0, noise_rms, len(long)), '04_numbers_names.wav', 'white noise at nominal 8 dB SNR')
    add('silence', np.zeros(5 * SR))
    audio = np.concatenate(parts)
    if np.max(np.abs(audio)) >= 1:
        raise ValueError('Fixture clips')
    output = ROOT / 'samples/vad_fixture.wav'
    with wave.open(str(output), 'wb') as f:
        f.setparams((1, 2, SR, 0, 'NONE', 'not compressed'))
        f.writeframes(np.round(audio * 32767).astype('<i2').tobytes())
    metadata = dict(audio_file=output.name, duration=len(audio)/SR, sample_rate=SR,
                    transcript=' '.join(texts), blocks=blocks, attribution=source,
                    note='Synthetic conditions from real recordings. Block boundaries are NOT word-level speech ground truth; source transcripts not manually verified.')
    (ROOT / 'samples/vad_fixture.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    print(f'{output}: {len(audio)/SR:.2f}s')


if __name__ == '__main__':
    main()
