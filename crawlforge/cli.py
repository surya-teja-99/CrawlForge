"""CrawlForge CLI.

Usage:
    python -m crawlforge.cli crawl --seed https://example.com --max-pages 50 --max-depth 2
    python -m crawlforge.cli search "async web crawling"
    python -m crawlforge.cli stats
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from .crawler import AsyncCrawler, DEFAULT_USER_AGENT
from .index import SearchIndex


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crawlforge", description="Polite async web crawler + full-text search"
    )
    parser.add_argument(
        "--db", default="crawlforge.db", help="path to the SQLite index file"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="crawl from seed URL(s) into the index")
    crawl.add_argument("--seed", action="append", required=True,
                       help="seed URL (repeatable)")
    crawl.add_argument("--max-pages", type=int, default=100)
    crawl.add_argument("--max-depth", type=int, default=2)
    crawl.add_argument("--rate", type=float, default=1.0,
                       help="max requests/second per domain")
    crawl.add_argument("--no-same-domain", action="store_true",
                       help="allow following links off the seed domain(s)")
    crawl.add_argument("--timeout", type=float, default=10.0)
    crawl.add_argument("--user-agent", default=DEFAULT_USER_AGENT)

    search = sub.add_parser("search", help="search the index")
    search.add_argument("query", help="FTS5 query, e.g. 'crawler NEAR polite'")
    search.add_argument("--limit", type=int, default=10)

    sub.add_parser("stats", help="show index statistics")
    return parser


def cmd_crawl(args: argparse.Namespace) -> int:
    index = SearchIndex(args.db)
    crawler = AsyncCrawler(
        index,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        same_domain=not args.no_same_domain,
        rate_per_domain=args.rate,
        timeout_s=args.timeout,
        user_agent=args.user_agent,
    )
    stats = asyncio.run(crawler.crawl(args.seed))
    print(f"Crawled {stats.pages_fetched} pages "
          f"({stats.pages_indexed} new) across {len(stats.domains)} domain(s)")
    print(f"Skipped by robots.txt: {stats.urls_skipped_robots} | "
          f"failed: {stats.urls_failed} | "
          f"avg latency: {stats.avg_latency_s:.2f}s")
    index.close()
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    index = SearchIndex(args.db)
    results = index.search(args.query, limit=args.limit)
    if not results:
        print("No results.")
    for i, r in enumerate(results, 1):
        print(f"{i}. {r['title'] or '(no title)'}")
        print(f"   {r['url']}")
        print(f"   {r['snippet']}")
    index.close()
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    index = SearchIndex(args.db)
    s = index.stats()
    print(f"Pages indexed : {s['pages_indexed']}")
    print(f"Domains       : {s['domains']}")
    print(f"Avg latency   : {s['avg_latency_s']:.2f}s")
    index.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "crawl":
        return cmd_crawl(args)
    if args.command == "search":
        return cmd_search(args)
    if args.command == "stats":
        return cmd_stats(args)
    return 2  # unreachable with required=True


if __name__ == "__main__":
    sys.exit(main())
