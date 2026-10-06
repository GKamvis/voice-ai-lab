"""One process-local consumer; blocking preprocessing/inference runs off-loop."""
import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger('uvicorn.error')


@dataclass
class Job:
    request_id: str
    upload: object
    future: asyncio.Future


class ASRQueue:
    def __init__(self, service, capacity=10):
        if capacity < 1:
            raise ValueError('ASR_QUEUE_SIZE must be positive')
        self.service = service
        self.queue = asyncio.Queue(maxsize=capacity)
        self.accepting = True
        self.task = asyncio.create_task(self.run())

    def submit(self, request_id, upload):
        if not self.accepting:
            raise asyncio.QueueFull
        future = asyncio.get_running_loop().create_future()
        self.queue.put_nowait(Job(request_id, upload, future))
        logger.info('[request_id=%s] queued queue_size=%d', request_id, self.queue.qsize())
        return future

    async def run(self):
        while True:
            job = await self.queue.get()
            try:
                if job is None:
                    return
                if job.future.cancelled():
                    logger.info('[request_id=%s] skipped expired request', job.request_id)
                    continue
                logger.info('[request_id=%s] processing queue_size=%d', job.request_id, self.queue.qsize())
                try:
                    result = await asyncio.to_thread(self.service.transcribe, job.upload, job.request_id)
                except Exception as exc:
                    if not job.future.done():
                        job.future.set_exception(exc)
                    logger.exception('[request_id=%s] failed', job.request_id)
                else:
                    if not job.future.done():
                        job.future.set_result(dict(result, request_id=job.request_id))
                    logger.info('[request_id=%s] completed', job.request_id)
            finally:
                if job is not None:
                    job.upload.file.close()
                self.queue.task_done()

    async def close(self):
        self.accepting = False
        await self.queue.put(None)
        await self.task
