"""Shared broker/state settings; deadlines are ordered to make redelivery safe."""
import os

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
STATE_URL = os.getenv('STATE_REDIS_URL', 'redis://localhost:6379/1')
MODEL = os.getenv('ASR_MODEL', 'small')
SOFT_LIMIT = int(os.getenv('ASR_SOFT_LIMIT', '540'))
HARD_LIMIT = int(os.getenv('ASR_HARD_LIMIT', '600'))
LEASE = HARD_LIMIT + 30
VISIBILITY = LEASE + 60
RETENTION = int(os.getenv('ASR_RESULT_TTL', '86400'))
MAX_ACTIVE = int(os.getenv('ASR_MAX_ACTIVE_JOBS', '20'))
MAX_ATTEMPTS = 4
assert 0 < SOFT_LIMIT < HARD_LIMIT
assert RETENTION > 0 and MAX_ACTIVE > 0
