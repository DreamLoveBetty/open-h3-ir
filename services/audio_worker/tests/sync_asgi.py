"""A sync bridge over an ASGI app, for the protocol tests.

httpx's own ASGITransport is async-only while the compiler's AudioWorkerClient is
deliberately synchronous. This adapter is test-only glue: the APP under test is the real
FastAPI/Starlette stack (real multipart parsing, real status codes), and the CLIENT is the
compiler's real one. The adapter adds no behaviour beyond bridging sync to async -- if the
two sides disagree about the wire, this file cannot hide it.
"""
from __future__ import annotations

import asyncio

import httpx


class SyncASGITransport(httpx.BaseTransport):
    def __init__(self, app):
        self.app = app

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return asyncio.run(self._run(request))

    async def _run(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "scheme": request.url.scheme or "http",
            "path": request.url.path,
            "raw_path": request.url.raw_path,
            "query_string": request.url.query,
            "root_path": "",
            "headers": [(k.lower().encode("latin-1"), v.encode("latin-1"))
                        for k, v in request.headers.items()],
        }
        sent = {"status": 500, "headers": [], "body": b""}
        inbox = [{"type": "http.request", "body": body, "more_body": False}]

        async def receive():
            return inbox.pop(0) if inbox else {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                sent["status"] = message["status"]
                sent["headers"] = message["headers"]
            elif message["type"] == "http.response.body":
                sent["body"] += message.get("body", b"")

        await self.app(scope, receive, send)
        return httpx.Response(
            sent["status"],
            headers=[(k.decode("latin-1"), v.decode("latin-1"))
                     for k, v in sent["headers"]],
            content=sent["body"])
