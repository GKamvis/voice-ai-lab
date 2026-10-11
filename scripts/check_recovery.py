"""Exercise stopped workers, SIGKILL recovery and Redis restart on an isolated stack."""
import io
import subprocess
import time
import wave
import httpx

COMPOSE = ['docker', 'compose', '-p', 'speech-test', '-f', 'compose.yaml', '-f', 'compose.test.yaml']


def compose(*args):
    subprocess.run(COMPOSE + list(args), check=True)


def wait(client, job_id, expected, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get('/jobs/' + job_id)
        response.raise_for_status()
        job = response.json()
        if job['status'] in expected:
            return job
        if job['status'] == 'failed':
            raise AssertionError(job['error'])
        time.sleep(.1)
    raise TimeoutError('Recovery deadline exceeded')


def main():
    data = io.BytesIO()
    with wave.open(data, 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\x01\x00' * 16000)
    with httpx.Client(base_url='http://localhost:18000', timeout=15) as client:
        def submit(payload=None):
            response = client.post('/jobs', files={'file': ('a.wav', data.getvalue() if payload is None else payload)})
            response.raise_for_status()
            return response.json()['job_id']
        assert client.get('/health').status_code == 200
        assert wait(client, submit(), {'completed'})['attempts'] == 1
        bad = wait(client, submit(b'corrupt'), {'failed'})
        assert bad['error'] == 'Invalid or corrupted audio'
        print('normal and corrupted audio: PASS', flush=True)
        compose('stop', 'asr-worker')
        job_id = submit()
        time.sleep(2)
        assert client.get('/jobs/' + job_id).json()['status'] == 'queued'
        compose('restart', 'redis')
        for _ in range(50):
            if client.get('/ready').status_code == 200:
                break
            time.sleep(.2)
        assert client.get('/jobs/' + job_id).json()['status'] == 'queued'
        compose('start', 'asr-worker')
        assert wait(client, job_id, {'completed'})['attempts'] == 1
        print('worker stop/start and Redis AOF restart: PASS', flush=True)
        job_id = submit()
        wait(client, job_id, {'processing'})
        compose('kill', '-s', 'SIGKILL', 'asr-worker')
        compose('start', 'asr-worker')
        job = wait(client, job_id, {'completed'})
        assert job['attempts'] == 2
        print('worker SIGKILL, lease recovery, same job ID: PASS', flush=True)
        assert client.get('/metrics').status_code == 200
    compose('exec', '-T', 'redis', 'redis-cli', '-n', '1', 'DBSIZE')


if __name__ == '__main__':
    main()
