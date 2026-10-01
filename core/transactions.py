"""Retry transient SQLite lock contention around an entire atomic service call."""
import time
from functools import wraps
from django.db import OperationalError, connection


def retry_locked(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        for attempt in range(8):
            try:
                return function(*args, **kwargs)
            except OperationalError as exc:
                if connection.vendor != 'sqlite' or 'locked' not in str(exc).lower() or connection.in_atomic_block or attempt == 7:
                    raise
                time.sleep(min(0.02 * (2 ** attempt), 0.3))
    return wrapped
