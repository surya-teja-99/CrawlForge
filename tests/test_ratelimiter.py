"""RateLimiter unit tests."""

import asyncio
import time

import pytest

from crawlforge.crawler import RateLimiter


def test_invalid_rate_rejected():
    with pytest.raises(ValueError):
        RateLimiter(rate=0)


def test_burst_then_throttles():
    async def _run():
        rl = RateLimiter(rate=20.0, capacity=2)
        t0 = time.monotonic()
        await rl.acquire("example.com")
        await rl.acquire("example.com")
        burst_s = time.monotonic() - t0
        await rl.acquire("example.com")
        return burst_s, time.monotonic() - t0

    burst_s, total_s = asyncio.run(_run())
    assert burst_s < 0.05, "initial burst should not wait"
    assert total_s >= 0.04, "third acquire should wait ~1/rate seconds"


def test_domains_are_independent():
    async def _run():
        rl = RateLimiter(rate=1.0, capacity=1)
        await rl.acquire("a.com")  # consumes a.com's only token
        t0 = time.monotonic()
        await rl.acquire("b.com")  # different domain: must not wait
        return time.monotonic() - t0

    assert asyncio.run(_run()) < 0.2
