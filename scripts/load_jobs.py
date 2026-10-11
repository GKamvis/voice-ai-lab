"""Measure real asynchronous completion at concurrency 1, 5, 10; never log text."""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import httpx


def percentile(values, fraction):
    values = sorted(values)
    return values[min(len(values) - 1, round((len(values) - 1) * fraction))]


async def run_batch(url, path, concurrency, timeout):
    audio = path.read_bytes()
    headers = {'Authorization': 'Bearer ' + os.environ['API_TOKEN']} if os.getenv('API_TOKEN') else {}
    async with httpx.AsyncClient(base_url=url, timeout=30, headers=headers) as client:
        async def one():
            started = time.monotonic()
            response = await client.post('/jobs', files={'file': (path.name, audio)})
            response.raise_for_status()
            accepted = time.monotonic() - started
            job_id = response.json()['job_id']
            while time.monotonic() - started < timeout:
                response = await client.get('/jobs/' + job_id)
                response.raise_for_status()
                job = response.json()
                if job['status'] in {'completed', 'failed'}:
                    result = job.get('result') or {}
                    return dict(job_id=job_id, status=job['status'], submit_seconds=accepted,
                                total_seconds=time.monotonic() - started,
                                processing_seconds=result.get('processing_time'),
                                inference_seconds=result.get('inference_time'))
                await asyncio.sleep(.5)
            raise TimeoutError('Job completion deadline exceeded')
        started = time.monotonic()
        results = await asyncio.gather(*(one() for _ in range(concurrency)))
        elapsed = time.monotonic() - started
    return dict(concurrency=concurrency, wall_seconds=elapsed,
                throughput_jobs_per_second=concurrency / elapsed,
                failed=sum(r['status'] == 'failed' for r in results),
                submit_p95_seconds=percentile([r['submit_seconds'] for r in results], .95),
                completion_p50_seconds=percentile([r['total_seconds'] for r in results], .5),
                completion_p95_seconds=percentile([r['total_seconds'] for r in results], .95),
                completion_p99_seconds=percentile([r['total_seconds'] for r in results], .99), jobs=results)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('audio', type=Path)
    parser.add_argument('--url', default='http://localhost:8000')
    parser.add_argument('--concurrency', type=int, nargs='+', default=[1, 5, 10])
    parser.add_argument('--timeout', type=float, default=1800)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    reports = []
    for concurrency in args.concurrency:
        report = await run_batch(args.url, args.audio, concurrency, args.timeout)
        reports.append(report)
        print(json.dumps(report), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(reports, indent=2) + '\n')
    if any(report['failed'] for report in reports):
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
