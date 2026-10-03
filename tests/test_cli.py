"""CLI smoke tests: crawl / search / stats through main()."""

from crawlforge import cli
from .helpers import run_test_server

ROUTES = {
    "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private\n"),
    "/": ("text/html",
           "<html><head><title>CLI Home</title></head><body>"
           "<p>smoke test hub</p>"
           '<a href="/docs">docs</a>'
           "</body></html>"),
    "/docs": ("text/html",
              "<html><head><title>Docs</title></head><body>"
              "<p>quokka deployment notes</p>"
              "</body></html>"),
}


def _run_cli(argv):
    return cli.main(argv)


def test_cli_crawl_search_stats(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    with run_test_server(ROUTES) as base:
        rc = _run_cli(["--db", db, "crawl", "--seed", base + "/",
                       "--max-pages", "10", "--max-depth", "2",
                       "--rate", "20"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Crawled" in out

        rc = _run_cli(["--db", db, "search", "quokka"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "/docs" in out

        rc = _run_cli(["--db", db, "search", "nosuchtermxyz"])
        assert rc == 0
        assert "No results." in capsys.readouterr().out

        rc = _run_cli(["--db", db, "stats"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Pages indexed" in out
        assert "2" in out  # both pages indexed
