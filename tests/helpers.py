"""Shared test helpers: a tiny local HTTP server (no external network)."""

from __future__ import annotations

import contextlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def run_test_server(routes: dict[str, tuple[str, str]]):
    """Serve ``routes`` ({path: (content_type, body)}) on 127.0.0.1.

    Returns a context manager yielding the base URL, e.g.
    ``http://127.0.0.1:12345``. Unknown paths get a 404.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            route = routes.get(self.path)
            if route is None:
                self.send_response(404)
                self.end_headers()
                return
            ctype, body = route
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # silence test output
            pass

    @contextlib.contextmanager
    def _serve():
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            yield f"http://{host}:{port}"
        finally:
            server.shutdown()
            thread.join()

    return _serve()
