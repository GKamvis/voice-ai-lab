import unittest
import numpy as np
from app.vad.energy_vad import frame_decisions, speech_segments
from app.vad.segments import pad_segments
from app.vad.pipeline import transcribe


class VADTests(unittest.TestCase):
    def test_partial_frame_and_strict_threshold(self):
        audio = np.r_[np.zeros(480), np.full(481, 0.1)]
        self.assertEqual(speech_segments(audio), [{'start': 480, 'end': 961}])
        self.assertEqual(frame_decisions(np.full(480, 0.03))[0]['result'], 'silence')
        self.assertEqual(speech_segments(np.zeros(100)), [])
        self.assertEqual(speech_segments(np.array([], dtype=float)), [])

    def test_pcm_rejected(self):
        with self.assertRaises(ValueError):
            speech_segments(np.array([32767], dtype=np.int16))

    def test_padding_merges_and_clamps(self):
        self.assertEqual(pad_segments([{'start': 100, 'end': 300}, {'start': 450, 'end': 900}],
                                      1000, 1000, 200, 300), [{'start': 0, 'end': 1000}])

    def test_pipeline_skips_silence_and_orders_chunks(self):
        class Model:
            def __init__(self): self.calls = []
            def transcribe(self, audio, **options):
                self.calls.append(len(audio))
                return {'text': str(len(audio))}
        model = Model()
        result = transcribe(model, np.zeros(16000), lambda a, sr: [])
        self.assertEqual(result['transcript'], '')
        self.assertEqual(model.calls, [])
        result = transcribe(model, np.zeros(16000), lambda a, sr: [dict(start=100, end=200), dict(start=400, end=600)])
        self.assertEqual(result['transcript'], '100 200')
        self.assertEqual(result['segments'][1]['start'], 400/16000)


if __name__ == '__main__':
    unittest.main()
