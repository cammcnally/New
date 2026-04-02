from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """Thread-safe token-bucket rate limiter.

    ``rate`` is tokens replenished per second; ``capacity`` is the burst size.
    Call ``wait()`` before each request to block until a token is available.
    """

    rate: float
    capacity: float
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def wait(self, tokens: float = 1.0) -> None:
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
            time.sleep(deficit / self.rate)


_LIMITERS: dict[str, TokenBucket] = {}
_GLOBAL_LOCK = threading.Lock()


def get_limiter(name: str, rate: float, capacity: float) -> TokenBucket:
    """Return a singleton limiter for *name*, creating one if needed."""
    with _GLOBAL_LOCK:
        if name not in _LIMITERS:
            _LIMITERS[name] = TokenBucket(rate=rate, capacity=capacity)
        return _LIMITERS[name]


def alpha_vantage_limiter(settings: object | None = None) -> TokenBucket:
    rpm = 5
    if settings and hasattr(settings, "av_requests_per_minute"):
        rpm = settings.av_requests_per_minute
    return get_limiter("alpha_vantage", rate=rpm / 60.0, capacity=1)


def sec_limiter(settings: object | None = None) -> TokenBucket:
    rps = 10.0
    if settings and hasattr(settings, "sec_requests_per_second"):
        rps = settings.sec_requests_per_second
    return get_limiter("sec", rate=rps, capacity=min(rps, 10))


def fred_limiter(settings: object | None = None) -> TokenBucket:
    rpm = 120
    if settings and hasattr(settings, "fred_requests_per_minute"):
        rpm = settings.fred_requests_per_minute
    return get_limiter("fred", rate=rpm / 60.0, capacity=5)
