"""#363: the no-auth /mcp warning reaches gunicorn/uvicorn deploys.

``gunicorn app:server`` and ``uvicorn app:server`` serve ``app.server`` without
calling ``run()``, so the bind-host warning in ``run()`` never fired there. The
route now warns, once, on the first request from a non-loopback client.
"""

import json
import warnings

import pytest

from fast_dash import FastDash

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "t", "version": "0"}}}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def _app(**kw):
    def echo(text: str = "hi") -> str:
        """Echo."""
        return text
    return FastDash(callback_fn=echo, mcp_server=True, **kw)


def _exposure(fn):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fn()
    return [str(w.message) for w in caught if "no authentication" in str(w.message)]


def _flask_post(app, addr, body=INIT):
    client = app.server.test_client()
    r = client.post("/mcp", data=json.dumps(body), content_type="application/json",
                    headers={"Accept": "application/json, text/event-stream"},
                    environ_base={"REMOTE_ADDR": addr})
    assert r.status_code == 200, r.data[:200]


def test_off_box_request_warns_once_without_run():
    app = _app()
    first = _exposure(lambda: _flask_post(app, "203.0.113.7"))
    assert len(first) == 1
    assert "203.0.113.7" in first[0] and "127.0.0.1" in first[0]
    # Once per app: a busy deploy must not log it on every request.
    again = _exposure(lambda: (_flask_post(app, "203.0.113.7", LIST),
                               _flask_post(app, "198.51.100.2")))
    assert again == []


@pytest.mark.parametrize("addr", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
def test_loopback_client_is_silent(addr):
    app = _app()
    assert _exposure(lambda: _flask_post(app, addr)) == []
    # ...and a loopback request doesn't use up the one warning.
    assert len(_exposure(lambda: _flask_post(app, "10.1.2.3"))) == 1


def test_run_warning_is_not_repeated_by_the_route(monkeypatch):
    app = _app(run_kwargs={"host": "0.0.0.0"})
    monkeypatch.setattr(app.app, "run", lambda **kw: None)
    assert len(_exposure(app.run)) == 1
    assert _exposure(lambda: _flask_post(app, "203.0.113.7")) == []


def _asgi_post(asgi_app, addr, body=INIT):
    """POST to /mcp straight through ASGI, so the client address is exact.

    starlette's TestClient now needs httpx2, which the test env doesn't have.
    """
    import asyncio

    payload = json.dumps(body).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": "/mcp", "raw_path": b"/mcp",
        "root_path": "", "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                    (b"accept", b"application/json, text/event-stream"),
                    (b"content-length", str(len(payload)).encode())],
        "client": (addr, 50000), "server": ("testserver", 80),
    }
    sent, status = False, []

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await asyncio.sleep(3600)

    async def send(message):
        if message["type"] == "http.response.start":
            status.append(message["status"])

    asyncio.run(asyncio.wait_for(asgi_app(scope, receive, send), 30))
    assert status == [200], status


def test_fastapi_backend_warns_on_off_box_request():
    pytest.importorskip("fastapi")
    app = _app(backend="fastapi")

    assert _exposure(lambda: _asgi_post(app.server, "127.0.0.1")) == []
    warned = _exposure(lambda: _asgi_post(app.server, "203.0.113.9"))
    assert len(warned) == 1 and "203.0.113.9" in warned[0]
