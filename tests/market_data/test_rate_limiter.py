from __future__ import annotations

import time

import pytest

from market_data.common.rate_limiter import TokenBucket

pytestmark = pytest.mark.ingestion


def test_token_bucket_immediate() -> None:
    b = TokenBucket(rate=10.0, capacity=1.0)
    t0 = time.monotonic()
    b.wait(1.0)
    assert time.monotonic() - t0 < 0.05


def test_token_bucket_rate_limiting() -> None:
    b = TokenBucket(rate=5.0, capacity=1.0)
    b.wait(1.0)
    t0 = time.monotonic()
    b.wait(1.0)
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.15
