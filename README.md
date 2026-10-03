# CrawlForge

A **polite async web crawler** with a **full-text search index**. Point it at a
seed URL and it will crawl (respecting robots.txt and per-domain rate limits),
extract clean page text, and build a ranked SQLite FTS5 index you can search
from the command line.

## Architecture

```
                        ┌──────────────┐
                        │  seed URLs   │
                        └──────┬───────┘
                               ▼
                    ┌─────────────────────┐
                    │  AsyncCrawler       │
                    │  (asyncio+aiohttp,  │
                    │   N workers)        │
                    └──────┬──────────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │ robots.txt │ │ rate limit │ │ URL dedupe │
     │ per-domain │ │ token      │ │ seen-set + │
     │ (cached)   │ │ bucket     │ │ normalized │
     └────────────┘ └────────────┘ └────────────┘
                           │
                           ▼ fetch (timeout, retries+backoff)
                    ┌──────────────┐
                    │ parse HTML   │
                    │ title+text   │
                    └──────┬───────┘
                           ▼
              ┌────────────────────────┐
              │ SearchIndex (SQLite)   │
              │ pages + FTS5 index,    │
              │ bm25 ranking, snippets│
              └────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
        search "query"               stats
```

## Quickstart

```bash
make setup   # install dependencies
make test    # run the test suite
make demo    # crawl a local 4-page test site, search it, show stats (<2 min, no internet)

# Real usage:
python -m crawlforge.cli crawl --seed https://example.com --max-pages 50 --max-depth 2
python -m crawlforge.cli search "async crawling"
python -m crawlforge.cli stats
```

Options: `--rate` (requests/sec per domain, default 1.0), `--no-same-domain`
to follow off-domain links, `--timeout`, `--user-agent`, `--db` to choose the
index file. The search command accepts FTS5 query syntax, e.g.
`"web crawler" NEAR polite`.

## How politeness works

- **robots.txt**: fetched once per domain and parsed with
  `urllib.robotparser`; disallowed URLs are never requested. An unreachable
  robots.txt is treated as "allow everything" (no invented restrictions).
- **Rate limiting**: per-domain token-bucket, default 1 request/second.
- **Identity**: a descriptive `User-Agent` on every request.
- **Bounds**: configurable max pages, max depth, and same-domain restriction.

## Limitations (honest)

- **Single machine.** No distributed crawling, no frontier persistence across
  runs (the seen-set is in memory; the index itself is persistent SQLite).
- **No JavaScript rendering.** Only static HTML is parsed; JS-heavy sites will
  yield little text.
- **Best-effort politeness.** Rate limits are per crawler process; running two
  instances doubles the load on a domain.
- **Small-scale FTS5.** Great for thousands of pages; not a replacement for
  Elasticsearch at web scale.
- The demo and tests use a local HTTP server — no external network needed.

## Project layout

```
crawlforge/
├── __init__.py     # package exports
├── crawler.py      # AsyncCrawler, RateLimiter, URL/text/link extraction
├── index.py        # SearchIndex: SQLite + FTS5, dedupe, search, stats
└── cli.py          # argparse CLI: crawl / search / stats
scripts/
└── demo.py         # local 4-page demo site: crawl → search → stats
tests/              # pytest: rate limiter, index, crawler, CLI (all hermetic)
```
