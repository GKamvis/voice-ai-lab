"""Real HTTP bursts; latency includes upload, queue wait, and processing."""
import argparse
import asyncio
import csv
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


async def burst(client, url, audio, count):
    gate = asyncio.Event()

    async def send(index):
        await gate.wait()
        started = time.perf_counter()
        try:
            response = await client.post(url + '/transcribe', files={'file': (audio[0], audio[1])})
            return dict(index=index, latency=time.perf_counter() - started,
                        success=response.is_success, status=response.status_code,
                        request_id=response.headers.get('x-request-id'),
                        body=response.json())
        except (httpx.HTTPError, ValueError) as exc:
            return dict(index=index, latency=time.perf_counter() - started,
                        success=False, error=str(exc))

    tasks = [asyncio.create_task(send(i)) for i in range(count)]
    started = time.perf_counter()
    gate.set()
    results = await asyncio.gather(*tasks)
    total = time.perf_counter() - started
    latencies = [r['latency'] for r in results]
    successes = sum(r['success'] for r in results)
    return dict(concurrent_requests=count, avg_latency=statistics.mean(latencies),
                min_latency=min(latencies), max_latency=max(latencies), total_time=total,
                success_count=successes, failure_count=count - successes), results


async def main(args):
    audio = (args.audio.name, args.audio.read_bytes())
    url = args.url.rstrip('/')
    rows, runs = [], []
    async with httpx.AsyncClient(timeout=args.timeout,
                                limits=httpx.Limits(max_connections=max(args.concurrency))) as client:
        health = await client.get(url + '/health')
        health.raise_for_status()
        if args.warmup:
            warm = await client.post(url + '/transcribe', files={'file': audio})
            warm.raise_for_status()
        for count in args.concurrency:
            row, requests = await burst(client, url, audio, count)
            rows.append(row)
            runs.append(dict(summary=row, requests=requests))
            print(row, flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'summary.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    table = '| Concurrent requests | Avg latency | Min latency | Max latency | Total time | Success | Errors |\n'
    table += '| --- | --- | --- | --- | --- | --- | --- |\n'
    for row in rows:
        table += (f"| {row['concurrent_requests']} | {row['avg_latency']:.3f}s | "
                  f"{row['min_latency']:.3f}s | {row['max_latency']:.3f}s | "
                  f"{row['total_time']:.3f}s | {row['success_count']} | {row['failure_count']} |\n")
    (args.output / 'summary.md').write_text(table)
    (args.output / 'runs.json').write_text(json.dumps(dict(
        timestamp=datetime.now(timezone.utc).isoformat(), url=url, audio=str(args.audio),
        health=health.json(), warmup=args.warmup, timeout=args.timeout, runs=runs), indent=2))
    print(table)
    return int(any(row['failure_count'] for row in rows))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, default=Path('samples/01_clean.wav'))
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--concurrency', type=int, nargs='+', default=[1, 5, 10])
    parser.add_argument('--timeout', type=float, default=360)
    parser.add_argument('--warmup', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('benchmark/load_results'))
    args = parser.parse_args()
    if any(count < 1 for count in args.concurrency) or args.timeout <= 0:
        parser.error('Concurrency and timeout must be positive')
    raise SystemExit(asyncio.run(main(args)))
