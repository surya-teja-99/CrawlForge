"""CrawlForge demo: crawl a local 4-page test site, search it, show stats.

No internet needed — everything runs against a local HTTP server.
Target: well under 2 minutes.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from crawlforge.cli import cmd_search, cmd_stats  # noqa: E402
from crawlforge.crawler import AsyncCrawler  # noqa: E402
from crawlforge.index import SearchIndex  # noqa: E402
from helpers import run_test_server  # noqa: E402
import argparse  # noqa: E402


def page(title: str, body: str, links: str = "") -> tuple[str, str]:
    return ("text/html",
            f"<html><head><title>{title}</title></head><body>"
            f"<h1>{title}</h1><p>{body}</p>{links}</body></html>")


ROUTES = {
    "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /hidden\n"),
    "/": page("Demo Hub", "welcome to the crawlforge demo site",
              '<a href="/python">python</a> '
              '<a href="/crawling">crawling</a> '
              '<a href="/search">search</a> '
              '<a href="/hidden/secret">do not follow</a>'),
    "/python": page("Python asyncio",
                    "asyncio lets python programs juggle many network "
                    "connections with a single thread"),
    "/crawling": page("Polite crawling",
                      "a polite crawler respects robots.txt, limits its "
                      "request rate per domain, and identifies itself"),
    "/search": page("Full-text search",
                    "sqlite fts5 builds an inverted index for fast "
                    "ranked full-text search with snippets"),
    "/hidden/secret": page("Secret", "robots.txt says you cannot come here"),
}


def main() -> None:
    t0 = time.time()
    print("=== CrawlForge demo ===\n")
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "demo.db")
        with run_test_server(ROUTES) as base:
            index = SearchIndex(db)
            crawler = AsyncCrawler(
                index, max_pages=10, max_depth=2, same_domain=True,
                rate_per_domain=10.0, timeout_s=5.0,
            )
            stats = asyncio.run(crawler.crawl([base + "/"]))
            print(f"Crawled {stats.pages_fetched} pages "
                  f"({stats.pages_indexed} new), "
                  f"skipped by robots.txt: {stats.urls_skipped_robots}\n")

            ns = argparse.Namespace(db=db, query="polite crawler", limit=5)
            print('--- search: "polite crawler" ---')
            cmd_search(ns)
            print()
            print("--- stats ---")
            cmd_stats(argparse.Namespace(db=db))
            index.close()
    print(f"\nDemo finished in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
