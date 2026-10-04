"""Local Whisper live stream: python -m app.streaming.streaming_asr."""
import argparse
import json
import queue
import threading
import time
from pathlib import Path
import numpy as np
from app.streaming.buffer import EndpointBuffer, SR
from app.streaming.microphone import frames

OPTIONS = dict(language='az', fp16=False, temperature=0.0, beam_size=5,
               condition_on_previous_text=False, verbose=None)


def load_model(name):
    import torch
    import whisper
    torch.set_num_threads(4)
    model = whisper.load_model(name, device='cpu')
    model.transcribe(np.zeros(SR, dtype=np.float32), **OPTIONS)
    return model


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', default='base')
    p.add_argument('--seconds', type=float, default=30)
    p.add_argument('--threshold', type=float, default=0.03)
    p.add_argument('--silence-ms', type=int, default=690)
    p.add_argument('--device', type=int)
    p.add_argument('--wav', type=Path, help='Replay PCM16 16 kHz mono WAV at real-time speed')
    p.add_argument('--output', type=Path, default=Path('benchmark/live_results.json'))
    a = p.parse_args()
    if a.seconds <= 0:
        p.error('--seconds must be positive')
    endpoint = EndpointBuffer(a.threshold, a.silence_ms)
    model = load_model(a.model)
    jobs = queue.Queue(maxsize=8)
    results, errors, recording = [], [], []
    def worker():
        while True:
            job = jobs.get()
            try:
                if job is None:
                    return
                utterance, detected, speech_end = job
                started = time.perf_counter()
                result = model.transcribe(utterance.audio, **OPTIONS)
                ready = time.perf_counter()
                row = dict(text=result['text'].strip(), reason=utterance.reason,
                           speech_duration=(utterance.speech_end-utterance.speech_start)/SR,
                           endpoint_delay=detected-speech_end, queue_delay=started-detected,
                           asr_inference=ready-started, total_latency=ready-speech_end,
                           speech_end=speech_end, vad_detected=detected, asr_started=started, transcript_ready=ready)
                results.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
            except Exception as exc:
                errors.append(str(exc))
            finally:
                jobs.task_done()
    thread = threading.Thread(target=worker)
    thread.start()
    def submit(u, end_time):
        if u:
            try:
                jobs.put_nowait((u, time.perf_counter(), end_time-(u.detected-u.speech_end)/SR))
            except queue.Full:
                raise RuntimeError('ASR backlog: job queue full; recording stopped')
    last_time = time.perf_counter()
    def source():
        if a.wav is None:
            yield from frames(a.seconds, a.device)
            return
        from samples.make_vad_fixture import read_wav
        audio = np.concatenate([read_wav(a.wav), np.zeros(SR, dtype=np.float32)])
        origin = time.perf_counter()
        for start in range(0, len(audio), 480):
            frame = audio[start:start+480]
            end = origin + (start+len(frame))/SR
            time.sleep(max(0, end-time.perf_counter()))
            yield frame, end
    print('Real-time WAV replay.' if a.wav else 'Microphone ready: speak now.', flush=True)
    try:
        for frame, last_time in source():
            if errors:
                raise RuntimeError(errors[0])
            recording.append(frame)
            submit(endpoint.push(frame), last_time)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        errors.append(str(exc))
        raise
    finally:
        try:
            submit(endpoint.flush(), last_time)
        finally:
            jobs.put(None)
            jobs.join()
            thread.join()
            a.output.parent.mkdir(parents=True, exist_ok=True)
            a.output.write_text(json.dumps(dict(source=str(a.wav) if a.wav else 'microphone', results=results, errors=errors), ensure_ascii=False, indent=2))
            if recording:
                import wave
                with wave.open(str(a.output.with_suffix('.wav')), 'wb') as f:
                    f.setparams((1, 2, SR, 0, 'NONE', 'not compressed'))
                    f.writeframes((np.clip(np.concatenate(recording), -1, 1)*32767).astype('<i2').tobytes())
    if errors:
        raise RuntimeError('; '.join(errors))

if __name__ == '__main__':
    main()
