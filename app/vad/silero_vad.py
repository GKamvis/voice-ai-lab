from app.vad.energy_vad import validate_audio


class SileroVAD:
    def __init__(self):
        from silero_vad import load_silero_vad
        self.model = load_silero_vad()

    def __call__(self, audio, sample_rate=16000):
        import torch
        from silero_vad import get_speech_timestamps
        audio = validate_audio(audio, sample_rate)
        if sample_rate not in (8000, 16000):
            raise ValueError('Silero requires 8000 or 16000 Hz')
        if not len(audio):
            return []
        return get_speech_timestamps(torch.from_numpy(audio.copy()).float(), self.model,
                                    sampling_rate=sample_rate, speech_pad_ms=0,
                                    min_speech_duration_ms=250, min_silence_duration_ms=100)
