"""Attempt limits for sign-up and sign-in, so emails cannot be checked or passwords guessed in bulk.

Counts live in this process, so a server running several workers limits each worker separately.
"""

import math
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

LOGIN_FAILURES_PER_EMAIL = (10, 15 * 60)
LOGIN_FAILURES_PER_CLIENT = (30, 15 * 60)
SIGNUPS_PER_CLIENT = (10, 60 * 60)


class AttemptLimiter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, window: float) -> deque:
        hits = self._hits.setdefault(key, deque())
        cutoff = self._clock() - window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def check(self, key: str, rule: tuple[int, float]) -> None:
        limit, window = rule
        with self._lock:
            hits = self._recent(key, window)
            if len(hits) >= limit:
                wait = max(1, math.ceil(hits[0] + window - self._clock()))
                minutes = math.ceil(wait / 60)
                raise HTTPException(
                    429,
                    f"Too many attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                    headers={"Retry-After": str(wait)},
                )

    def record(self, key: str, rule: tuple[int, float]) -> None:
        with self._lock:
            self._recent(key, rule[1]).append(self._clock())
            if len(self._hits) > 50_000:
                self._prune()

    def _prune(self) -> None:
        longest = max(LOGIN_FAILURES_PER_EMAIL[1], LOGIN_FAILURES_PER_CLIENT[1], SIGNUPS_PER_CLIENT[1])
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= self._clock() - longest]:
            del self._hits[key]


def client_key(request: Request) -> str:
    # Behind a reverse proxy this is the proxy's address unless uvicorn trusts it (FORWARDED_ALLOW_IPS).
    return request.client.host if request.client else "unknown"
