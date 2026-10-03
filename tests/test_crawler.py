"""Crawler tests against a local HTTP server (no external network)."""

import asyncio

from crawlforge.crawler import (
    AsyncCrawler,
    extract_links,
    extract_text,
    normalize_url,
)
from crawlforge.index import SearchIndex
from .helpers import run_test_server

ROUTES = {
    "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private\n"),
    "/": ("text/html",
           "<html><head><title>Home</title></head><body>"
           "<h1>Welcome</h1><p>hub page</p>"
           '<a href="/page1">one</a> <a href="/private/secret">nope</a>'
           "</body></html>"),
    "/page1": ("text/html",
               "<html><head><title>Page One</title></head><body>"
               "<p>distinctive zebra content here</p>"
               '<a href="/">back</a>'
               "</body></html>"),
    "/private/secret": ("text/html",
                        "<html><head><title>Secret</title></head><body>"
                        "<p>you should never see this</p>"
                        "</body></html>"),
}


def test_normalize_url():
    assert normalize_url("HTTP://Example.COM/a?b=1#frag") == "http://example.com/a?b=1"
    assert normalize_url("http://example.com") == "http://example.com/"


def test_extract_links_and_text():
    html = ('<html><head><title>T</title></head><body>'
            '<script>var x = 1;</script>'
            '<p>Hello <a href="/p">world</a></p>'
            '<a href="https://other.test/q">ext</a>'
            "</body></html>")
    assert extract_links(html, "http://base.test/") == [
        "http://base.test/p", "https://other.test/q",
    ]
    title, text = extract_text(html)
    assert title == "T"
    assert "Hello world" in text
    assert "var x" not in text  # script stripped


def test_crawl_respects_robots_and_indexes(tmp_path):
    async def _run(base):
        index = SearchIndex(tmp_path / "c.db")
        crawler = AsyncCrawler(
            index, max_pages=10, max_depth=2, same_domain=True,
            rate_per_domain=20.0, timeout_s=5.0,
        )
        stats = await crawler.crawl([base + "/"])
        return stats, index

    with run_test_server(ROUTES) as base:
        stats, index = asyncio.run(_run(base))

    try:
        assert stats.urls_skipped_robots >= 1
        assert index.has_url(base + "/")
        assert index.has_url(base + "/page1")
        assert not index.has_url(base + "/private/secret")
        results = index.search("zebra")
        assert len(results) == 1
        assert results[0]["url"] == base + "/page1"
    finally:
        index.close()


def test_crawl_max_pages_and_depth(tmp_path):
    async def _run(base):
        index = SearchIndex(tmp_path / "c.db")
        crawler = AsyncCrawler(
            index, max_pages=1, max_depth=0, same_domain=True,
            rate_per_domain=20.0, timeout_s=5.0,
        )
        return await crawler.crawl([base + "/"]), index

    with run_test_server(ROUTES) as base:
        stats, index = asyncio.run(_run(base))

    try:
        assert stats.pages_fetched == 1
        assert not index.has_url(base + "/page1")  # depth 0: no link following
    finally:
        index.close()
