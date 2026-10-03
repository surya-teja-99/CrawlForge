"""SearchIndex tests: FTS5 round-trip, dedupe, stats."""

import pytest

from crawlforge.index import SearchIndex


@pytest.fixture()
def index(tmp_path):
    idx = SearchIndex(tmp_path / "test.db")
    yield idx
    idx.close()


def test_add_and_search_round_trip(index):
    assert index.add_page("http://x.test/a", "Async crawling",
                          "polite web crawlers respect robots.txt") is True
    assert index.add_page("http://x.test/b", "Cooking",
                          "recipes for sourdough bread") is True
    results = index.search("crawlers")
    assert len(results) == 1
    assert results[0]["url"] == "http://x.test/a"
    assert "<b>" in results[0]["snippet"]  # highlighted match


def test_search_ranking_prefers_title_match(index):
    index.add_page("http://x.test/a", "Python asyncio guide",
                   "some generic body text here")
    index.add_page("http://x.test/b", "Unrelated title",
                   "python asyncio appears only in this body text")
    results = index.search("python asyncio")
    assert len(results) == 2
    # BM25 ranks the title match first
    assert results[0]["url"] == "http://x.test/a"


def test_url_dedupe(index):
    assert index.add_page("http://x.test/a", "T", "body one") is True
    assert index.add_page("http://x.test/a", "T", "body two") is False
    assert index.stats()["pages_indexed"] == 1
    assert index.has_url("http://x.test/a")
    assert not index.has_url("http://x.test/missing")


def test_search_no_results(index):
    index.add_page("http://x.test/a", "T", "hello world")
    assert index.search("zyxqwv") == []


def test_stats(index):
    index.add_page("http://a.test/1", "T", "x", latency_s=0.5)
    index.add_page("http://a.test/2", "T", "y", latency_s=1.5)
    index.add_page("http://b.test/1", "T", "z", latency_s=1.0)
    s = index.stats()
    assert s["pages_indexed"] == 3
    assert s["domains"] == 2
    assert s["avg_latency_s"] == pytest.approx(1.0)
