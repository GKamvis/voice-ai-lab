import asyncio
import io
import threading
import unittest
from unittest.mock import patch
from fastapi import UploadFile
from fastapi.testclient import TestClient
from app.api.main import create_app
from app.services.asr_queue import ASRQueue


class SlowService:
    model_name = 'test'

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.contents = []

    def transcribe(self, upload, request_id):
        self.calls.append(request_id)
        self.entered.set()
        if not self.release.wait(5):
            raise RuntimeError('Test release deadline exceeded')
        self.contents.append(upload.file.read())
        return dict(language='az', duration=1, processing_time=.01, rtf=.01, text='ok', segments=[])


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_fifo_capacity_and_expired_jobs(self):
        service = SlowService()
        queue = ASRQueue(service, capacity=2)
        uploads = [UploadFile(file=io.BytesIO(b'a')) for _ in range(4)]
        try:
            first = queue.submit('1', uploads[0])
            self.assertTrue(await asyncio.to_thread(service.entered.wait, 2))
            second = queue.submit('2', uploads[1])
            third = queue.submit('3', uploads[2])
            with self.assertRaises(asyncio.QueueFull):
                queue.submit('4', uploads[3])
            second.cancel()
            service.release.set()
            await asyncio.wait_for(asyncio.gather(first, third), 3)
            self.assertEqual(service.calls, ['1', '3'])
        finally:
            service.release.set()
            await queue.close()
            uploads[3].file.close()
        self.assertTrue(all(u.file.closed for u in uploads))


class DeadlineTests(unittest.TestCase):
    def test_timeout_keeps_worker_serial_and_upload_alive(self):
        service = SlowService()
        with patch.dict('os.environ', ASR_REQUEST_TIMEOUT='0.1', ASR_QUEUE_SIZE='1'):
            with TestClient(create_app(lambda: service)) as client:
                try:
                    first = client.post('/transcribe', files={'file': ('a.wav', b'audio')})
                    self.assertEqual(first.status_code, 504)
                    self.assertTrue(first.headers['x-request-id'])
                    self.assertEqual(client.get('/health').status_code, 200)
                    second = client.post('/transcribe', files={'file': ('b.wav', b'audio')})
                    self.assertEqual(second.status_code, 504)
                    full = client.post('/transcribe', files={'file': ('c.wav', b'audio')})
                    self.assertEqual(full.status_code, 503)
                    self.assertEqual(full.headers['retry-after'], '1')
                    self.assertTrue(full.headers['x-request-id'])
                finally:
                    service.release.set()
        self.assertEqual(len(service.calls), 1)
        self.assertEqual(service.contents, [b'audio'])
