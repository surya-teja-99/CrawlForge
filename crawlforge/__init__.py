"""CrawlForge — a polite async web crawler with a full-text search index."""

__version__ = "0.1.0"

from .crawler import AsyncCrawler, CrawlStats, RateLimiter
from .index import SearchIndex

__all__ = ["AsyncCrawler", "CrawlStats", "RateLimiter", "SearchIndex", "__version__"]
