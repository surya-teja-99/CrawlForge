"""Async web crawler: polite, rate-limited, robots.txt-aware.

Design:
  - One ``aiohttp`` session shared across all fetches.
  - Per-domain token-bucket rate limiting (see :class:`RateLimiter`).
  - robots.txt is fetched once per domain and parsed with
    :mod:`urllib.robotparser`; disallowed URLs are never requested.
  - BFS over (url, depth) with URL normalization + a seen-set for dedupe.
  - Timeouts and retries with exponential backoff on transient failures.
"""

from __future__ import annotations

import asyncio
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field

import aiohttp
from bs4 import BeautifulSoup

DEFAULT_USER_AGENT = "CrawlForge/0.1.0 (+https://github.com/ crawl-for-educational-use)"


class RateLimiter:
    """Per-domain token-bucket rate limiter.

    ``rate`` is the sustained requests-per-second allowed per domain.
    Bursts of up to ``capacity`` requests are permitted.
    """

    def __init__(self, rate: float = 1.0, capacity: int = 1) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = rate
        self.capacity = max(1, capacity)
        self._tokens: dict[str, float] = {}
        self._updated: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, domain: str) -> asyncio.Lock:
        lock = self._locks.get(domain)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[domain] = lock
        return lock

    async def acquire(self, domain: str) -> None:
        """Wait until one token is available for ``domain``, then consume it."""
        async with self._lock_for(domain):
            now = time.monotonic()
            tokens = self._tokens.get(domain, self.capacity)
            last = self._updated.get(domain, now)
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            wait = 0.0
            if tokens < 1.0:
                wait = (1.0 - tokens) / self.rate
                tokens = 0.0
            else:
                tokens -= 1.0
            self._tokens[domain] = tokens
            self._updated[domain] = now + wait
            if wait > 0:
                await asyncio.sleep(wait)


@dataclass
class CrawlStats:
    pages_fetched: int = 0
    pages_indexed: int = 0
    urls_skipped_robots: int = 0
    urls_failed: int = 0
    domains: set[str] = field(default_factory=set)
    total_latency_s: float = 0.0

    @property
    def avg_latency_s(self) -> float:
        return self.total_latency_s / self.pages_fetched if self.pages_fetched else 0.0


def normalize_url(url: str) -> str:
    """Normalize a URL for dedupe: lowercase scheme/host, drop fragment."""
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower() or "http"
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    return urllib.parse.urlunsplit((scheme, netloc, path, parts.query, ""))


def extract_links(html: str, base_url: str) -> list[str]:
    """Extract absolute http(s) links from a page."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        abs_url = urllib.parse.urljoin(base_url, tag["href"])
        parts = urllib.parse.urlsplit(abs_url)
        if parts.scheme in ("http", "https") and parts.netloc:
            links.append(normalize_url(abs_url))
    # preserve order, drop dupes
    return list(dict.fromkeys(links))


def extract_text(html: str) -> tuple[str, str]:
    """Return (title, clean visible text) for an HTML document."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    text = soup.get_text(separator=" ", strip=True)
    text = " ".join(text.split())  # collapse whitespace
    return title, text


class AsyncCrawler:
    """Polite async crawler writing pages into a :class:`SearchIndex`."""

    def __init__(
        self,
        index,
        *,
        max_pages: int = 100,
        max_depth: int = 2,
        same_domain: bool = True,
        rate_per_domain: float = 1.0,
        timeout_s: float = 10.0,
        max_retries: int = 2,
        user_agent: str = DEFAULT_USER_AGENT,
        concurrency: int = 4,
    ) -> None:
        self.index = index
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.same_domain = same_domain
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.user_agent = user_agent
        self.concurrency = max(1, concurrency)
        self.limiter = RateLimiter(rate=rate_per_domain)
        self.stats = CrawlStats()
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._seen: set[str] = set()

    # -- robots.txt -----------------------------------------------------

    async def _robots_for(self, session: aiohttp.ClientSession, url: str):
        """Return a parsed RobotFileParser for the URL's domain (cached).

        Missing/unreachable robots.txt means "allow everything" — the
        conservative choice that never invents restrictions.
        """
        parts = urllib.parse.urlsplit(url)
        domain = parts.netloc.lower()
        cached = self._robots_cache.get(domain)
        if cached is not None:
            return cached
        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout_s)
            async with session.get(
                robots_url, timeout=timeout, headers={"User-Agent": self.user_agent}
            ) as resp:
                if resp.status == 200:
                    body = await resp.text()
                    rp.parse(body.splitlines())
                # any non-200 -> leave parser empty (allows everything)
        except Exception:
            pass  # unreachable robots.txt -> allow everything
        self._robots_cache[domain] = rp
        return rp

    async def _allowed(self, session: aiohttp.ClientSession, url: str) -> bool:
        rp = await self._robots_for(session, url)
        return rp.can_fetch(self.user_agent, url)

    # -- fetching -------------------------------------------------------

    async def _fetch(self, session: aiohttp.ClientSession, url: str) -> tuple[str | None, float]:
        """Fetch a URL with retries + backoff. Returns (html_or_None, latency_s)."""
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=self.timeout_s)
                t0 = time.monotonic()
                async with session.get(
                    url, timeout=timeout, headers={"User-Agent": self.user_agent}
                ) as resp:
                    if resp.status != 200:
                        return None, 0.0
                    ctype = resp.headers.get("Content-Type", "")
                    if "html" not in ctype and "text" not in ctype:
                        return None, 0.0
                    html = await resp.text()
                latency = time.monotonic() - t0
                self.stats.total_latency_s += latency
                return html, latency
            except Exception as exc:  # timeouts, connection errors: retry
                last_exc = exc
                await asyncio.sleep(0.5 * (2 ** attempt))
        if last_exc is not None:
            self.stats.urls_failed += 1
        return None, 0.0

    # -- crawl loop -----------------------------------------------------

    async def _worker(
        self, session: aiohttp.ClientSession, queue: asyncio.Queue, seed_domains: set[str]
    ) -> None:
        while True:
            try:
                url, depth = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                await self._process(session, queue, url, depth, seed_domains)
            finally:
                queue.task_done()

    async def _process(
        self,
        session: aiohttp.ClientSession,
        queue: asyncio.Queue,
        url: str,
        depth: int,
        seed_domains: set[str],
    ) -> None:
        if self.stats.pages_fetched >= self.max_pages:
            return
        domain = urllib.parse.urlsplit(url).netloc.lower()

        if not await self._allowed(session, url):
            self.stats.urls_skipped_robots += 1
            return

        await self.limiter.acquire(domain)
        html, latency = await self._fetch(session, url)
        if html is None:
            return

        self.stats.pages_fetched += 1
        self.stats.domains.add(domain)
        title, text = extract_text(html)
        if self.index.add_page(url, title, text, latency_s=latency):
            self.stats.pages_indexed += 1

        if depth < self.max_depth:
            for link in extract_links(html, url):
                link_domain = urllib.parse.urlsplit(link).netloc.lower()
                if self.same_domain and link_domain not in seed_domains:
                    continue
                if link not in self._seen and self.stats.pages_fetched + queue.qsize() < self.max_pages:
                    self._seen.add(link)
                    queue.put_nowait((link, depth + 1))

    async def crawl(self, seed_urls: list[str]) -> CrawlStats:
        """Crawl from seed URLs. Returns crawl statistics."""
        seeds = [normalize_url(u) for u in seed_urls]
        seed_domains = {urllib.parse.urlsplit(u).netloc.lower() for u in seeds}
        queue: asyncio.Queue = asyncio.Queue()
        for url in seeds:
            if url not in self._seen:
                self._seen.add(url)
                queue.put_nowait((url, 0))

        connector = aiohttp.TCPConnector(limit_per_host=self.concurrency)
        async with aiohttp.ClientSession(connector=connector) as session:
            workers = [
                asyncio.create_task(self._worker(session, queue, seed_domains))
                for _ in range(self.concurrency)
            ]
            await queue.join()
            for w in workers:
                w.cancel()
        return self.stats
