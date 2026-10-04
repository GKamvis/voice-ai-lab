import unittest
import numpy as np
from app.streaming.buffer import EndpointBuffer, FRAME, SR
from benchmark.streaming_compare import windows, merge_text, make_jobs

class StreamingTests(unittest.TestCase):
    def test_endpoint_exact_and_pause_retained(self):
        b = EndpointBuffer()
        speech = np.full(FRAME, .1, dtype=np.float32)
        silence = np.zeros(FRAME, dtype=np.float32)
        for _ in range(7):
            self.assertIsNone(b.push(silence))
        b.push(speech)
        for _ in range(10):
            self.assertIsNone(b.push(silence))
        b.push(speech)
        for _ in range(22):
            self.assertIsNone(b.push(silence))
        u = b.push(silence)
        self.assertEqual(u.detected-u.speech_end, 23*FRAME)
        self.assertEqual(len(u.audio), 42*FRAME)
        self.assertIsNone(b.flush())

    def test_silence_never_submitted(self):
        self.assertEqual(make_jobs(np.zeros(2*SR, dtype=np.float32), 'VAD'), [])

    def test_max_duration_and_eof(self):
        b = EndpointBuffer(max_seconds=.06)
        frame = np.full(FRAME, .1, dtype=np.float32)
        b.push(frame)
        self.assertEqual(b.push(frame).reason, 'max_duration')
        b.push(frame)
        self.assertEqual(len(b.flush().audio), FRAME)

    def test_boundaries(self):
        self.assertEqual(list(windows(17, 5, 1)), [(0,5),(4,9),(8,13),(12,17)])
        self.assertEqual(list(windows(10,5)), [(0,5),(5,10)])
        with self.assertRaises(ValueError):
            list(windows(10,5,5))

    def test_merge(self):
        self.assertEqual(merge_text('Bu bir testdir.', 'testdir davam edir'), 'Bu bir testdir. davam edir')
        self.assertEqual(merge_text('salam', 'dünya'), 'salam dünya')

if __name__ == '__main__':
    unittest.main()
