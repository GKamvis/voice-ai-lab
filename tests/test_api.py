import io
import subprocess
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
from app.api.main import create_app
from app.services.transcription_service import TranscriptionService


def wav(seconds=1, rate=16000, channels=1):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as handle:
        handle.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
        handle.writeframes(b'\0\0' * round(seconds * rate) * channels)
    return buffer.getvalue()


class APITests(unittest.TestCase):
    def setUp(self):
        self.model = Mock()
        self.model.transcribe.return_value = {'text': ' Salam '}
        self.detector = Mock(return_value=[{'start': 0, 'end': 16000}])
        self.service = TranscriptionService(self.model, self.detector)
        self.factory = Mock(return_value=self.service)
        self.app = create_app(self.factory)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.assertIsNone(self.app.state.service)

    def post(self, name, data):
        return self.client.post('/transcribe', files={'file': (name, data)})

    def test_health_and_single_load_for_three_requests(self):
        self.assertEqual(self.client.get('/health').json(),
                         {'status': 'healthy', 'model': 'whisper-small'})
        for _ in range(3):
            response = self.post('audio.wav', wav(rate=44100, channels=2))
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data['text'], 'Salam')
            self.assertEqual(data['language'], 'az')
            self.assertEqual(data['duration'], 1)
            self.assertAlmostEqual(data['rtf'], data['processing_time'])
            self.assertEqual(data['segments'], [{'start': 0, 'end': 1, 'text': 'Salam'}])
        self.factory.assert_called_once()
        self.assertEqual(self.model.transcribe.call_count, 3)
        audio = self.model.transcribe.call_args.args[0]
        self.assertEqual(audio.shape, (16000,))

    def test_invalid_inputs(self):
        for name, data in [('empty.wav', b''), ('note.txt', b'hello'),
                           ('corrupt.wav', b'not audio'), ('corrupt.mp3', b'bad'),
                           ('short.wav', wav(.1))]:
            with self.subTest(name=name):
                self.assertEqual(self.post(name, data).status_code, 400)
        self.model.transcribe.assert_not_called()
        self.assertEqual(self.client.post('/transcribe').status_code, 422)

    def test_mp3(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'a.wav', Path(folder) / 'a.mp3'
            source.write_bytes(wav())
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), str(target)], check=True)
            self.assertEqual(self.post('a.mp3', target.read_bytes()).status_code, 200)

    def test_silence(self):
        self.detector.return_value = []
        response = self.post('silence.wav', wav())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['segments'], [])
        self.assertEqual(response.json()['text'], '')
        self.model.transcribe.assert_not_called()

    def test_internal_failure_is_sanitized_and_lock_released(self):
        self.model.transcribe.side_effect = RuntimeError('private details')
        with self.assertLogs('app.api.routes', level='ERROR'):
            response = self.post('audio.wav', wav())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {'detail': 'Audio processing failed'})
        self.assertFalse(self.service.lock.locked())

    def test_health_stays_responsive_and_second_request_is_busy(self):
        entered, release = threading.Event(), threading.Event()
        def slow(*args, **kwargs):
            entered.set()
            release.wait(5)
            return {'text': 'Salam'}
        self.model.transcribe.side_effect = slow
        results = []
        worker = threading.Thread(target=lambda: results.append(self.post('a.wav', wav())))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.client.get('/health').status_code, 200)
            self.assertEqual(self.post('b.wav', wav()).status_code, 503)
        finally:
            release.set()
            worker.join(5)
        self.assertEqual(results[0].status_code, 200)

    def test_size_and_duration_limits(self):
        from unittest.mock import patch
        with patch('app.services.transcription_service.MAX_UPLOAD_BYTES', 10):
            self.assertEqual(self.post('large.wav', wav()).status_code, 400)
        with patch('app.services.transcription_service.MAX_DURATION', 1):
            self.assertEqual(self.post('long.wav', wav(2)).status_code, 400)


if __name__ == '__main__':
    unittest.main()
