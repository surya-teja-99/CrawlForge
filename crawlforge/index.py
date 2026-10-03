"""SQLite + FTS5 full-text search index for crawled pages.

Schema:
  pages(url TEXT PRIMARY KEY, title TEXT, text TEXT,
        crawled_at TEXT, latency_s REAL)
  pages_fts — FTS5 virtual table over (title, text), kept in sync with
  ``pages`` via triggers (external-content table).

Dedupe is by URL: re-adding an existing URL is a no-op returning False.
"""

from __future__ import annotations

import datetime
import sqlite3
import urllib.parse
from pathlib import Path


class SearchIndex:
    def __init__(self, db_path: str | Path = "crawlforge.db") -> None:
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pages(
                url TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                crawled_at TEXT NOT NULL,
                latency_s REAL NOT NULL DEFAULT 0
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
                title, text,
                content='pages', content_rowid='rowid'
            );
            CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
                INSERT INTO pages_fts(rowid, title, text)
                VALUES (new.rowid, new.title, new.text);
            END;
            CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
                INSERT INTO pages_fts(pages_fts, rowid, title, text)
                VALUES ('delete', old.rowid, old.title, old.text);
            END;
            """
        )
        self.conn.commit()

    def add_page(
        self, url: str, title: str, text: str, latency_s: float = 0.0
    ) -> bool:
        """Insert a page. Returns True if inserted, False if URL already indexed."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO pages(url, title, text, crawled_at, latency_s)"
            " VALUES (?, ?, ?, ?, ?)",
            (url, title, text, now, latency_s),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def has_url(self, url: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM pages WHERE url = ?", (url,)
        ).fetchone()
        return row is not None

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search ranked by BM25, with highlighted snippets."""
        rows = self.conn.execute(
            """
            SELECT p.url, p.title, p.crawled_at,
                   snippet(pages_fts, 1, '<b>', '</b>', ' ... ', 24) AS snippet,
                   bm25(pages_fts) AS rank
            FROM pages_fts
            JOIN pages p ON p.rowid = pages_fts.rowid
            WHERE pages_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """Aggregate stats: page count, domains, average fetch latency."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS n, AVG(latency_s) AS avg_lat FROM pages"
        ).fetchone()
        urls = [
            r[0] for r in self.conn.execute("SELECT url FROM pages").fetchall()
        ]
        domains = {
            urllib.parse.urlsplit(u).netloc.lower() for u in urls if u
        }
        return {
            "pages_indexed": row["n"],
            "domains": len(domains),
            "avg_latency_s": row["avg_lat"] or 0.0,
        }

    def close(self) -> None:
        self.conn.close()
