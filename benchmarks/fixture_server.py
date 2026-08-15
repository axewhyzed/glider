"""Deterministic local HTTP fixtures used by examples, tests, and benchmarks."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import urlsplit


class _FixtureHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, *, page_count: int, catalog_count: int):
        super().__init__(address, handler)
        self.page_count = page_count
        self.catalog_count = catalog_count
        self.request_count = 0
        self._request_count_lock = threading.Lock()

    def record_request(self) -> None:
        with self._request_count_lock:
            self.request_count += 1


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _send(self, status: int, body: str, content_type: str = "text/html") -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        server = cast(_FixtureHTTPServer, self.server)
        server.record_request()
        path = urlsplit(self.path).path
        if path.startswith("/item/"):
            item_id = path.rsplit("/", 1)[-1]
            self._send(
                200,
                "<html><body><article class='product'>"
                f"<h1>Fixture item {item_id}</h1>"
                f"<span class='price'>{item_id}.50</span>"
                "</article></body></html>",
            )
            return

        if path == "/catalog":
            links = "".join(
                f"<a class='product-link' href='/item/{index}'>item {index}</a>"
                for index in range(1, server.catalog_count + 1)
            )
            self._send(
                200,
                f"<html><body>{links}</body></html>",
            )
            return

        if path.startswith("/page/"):
            try:
                page = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self._send(404, "not found")
                return
            if not 1 <= page <= server.page_count:
                self._send(404, "not found")
                return
            next_link = (
                f"<a class='next' href='/page/{page + 1}'>next</a>"
                if page < server.page_count
                else ""
            )
            self._send(
                200,
                "<html><body>"
                f"<article class='product'><h1>Page {page}</h1></article>"
                f"{next_link}</body></html>",
            )
            return

        if path.startswith("/api/item/"):
            item_id = path.rsplit("/", 1)[-1]
            self._send(
                200,
                json.dumps({"id": item_id, "title": f"Fixture API item {item_id}"}),
                "application/json",
            )
            return

        self._send(404, "not found")


class FixtureServer:
    """Small local server with stable HTML and JSON responses.

    The fixture intentionally binds to loopback. Callers must opt out of the
    normal private-network policy in their test configuration explicitly.
    """

    def __init__(self, page_count: int = 3, catalog_count: int = 2) -> None:
        if page_count < 1:
            raise ValueError("page_count must be positive")
        if catalog_count < 1:
            raise ValueError("catalog_count must be positive")
        self._server = _FixtureHTTPServer(
            ("127.0.0.1", 0),
            _FixtureHandler,
            page_count=page_count,
            catalog_count=catalog_count,
        )
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def request_count(self) -> int:
        return self._server.request_count

    def start(self) -> "FixtureServer":
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="glider-fixture-server",
                daemon=True,
            )
            self._thread.start()
        return self

    def close(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> "FixtureServer":
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.close()
