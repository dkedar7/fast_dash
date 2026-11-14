"""fast_dash.connect(url): the mcp_test_client() surface over real HTTP (#354)."""

import socket
import threading
import time

import pytest
from werkzeug.serving import make_server

import fast_dash
from fast_dash import DynamicDash, FastDash, Text, connect
from fast_dash.mcp import MCPClient, MCPError


def bars(n: int = 3, color: str = "#ff0000") -> int:
    """Double n."""
    return n * 2


@pytest.fixture
def serve():
    servers = []

    def _serve(app):
        srv = make_server("127.0.0.1", 0, app.app.server, threaded=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_port}"

    yield _serve
    for srv in servers:
        srv.shutdown()


def test_exported_from_the_package():
    assert fast_dash.connect is connect and fast_dash.MCPClient is MCPClient


def test_tools_are_methods_over_the_wire(serve):
    url = serve(FastDash(callback_fn=bars, mcp_server=True))
    with connect(url + "/mcp") as app:
        assert isinstance(app, MCPClient)
        assert {"describe_app", "invoke", "set_input", "get_invocation"} <= set(app.tools)
        assert app.server_info["name"]
        assert [i["id"] for i in app.describe_app()["inputs"]] == ["n", "color"]
        assert app.set_input("n", 5) == {"ok": True, "id": "n", "value": 5}   # positional
        assert app.invoke()["outputs"] == {"output_output_1": 10}
        run = app.invoke(inputs={"n": 12})
        assert run["outputs"] == {"output_output_1": 24}
        assert app.get_invocation(index=run["history_index"])["outputs"] == run["outputs"]
        assert "invoke" in dir(app)


def test_same_answers_as_the_in_process_client(serve):
    fd = FastDash(callback_fn=bars, mcp_server=True)
    local = fd.mcp_test_client()
    url = serve(fd)
    with connect(url) as remote:                  # bare root URL: /mcp is added
        assert remote.url == url + "/mcp"
        assert remote.describe_app() == local.describe_app()
        bad = remote.invoke(inputs={"n": "x"})
        assert bad["ok"] is False and bad["errors"]["n"].startswith("expected an integer")
        assert {k: v for k, v in bad.items() if k != "duration_ms"} == {
            k: v for k, v in local.invoke(inputs={"n": "x"}).items() if k != "duration_ms"}


def test_unknown_tool_and_too_many_arguments(serve):
    with connect(serve(FastDash(callback_fn=bars, mcp_server=True))) as app:
        with pytest.raises(AttributeError):
            app.not_a_tool
        with pytest.raises(MCPError, match="no tool named"):
            app.call("not_a_tool")
        with pytest.raises(TypeError):
            app.set_input("n", 5, "extra")


def test_set_form_from_another_process_is_seen(serve):
    def echo(**kw):
        return repr(kw)

    url = serve(DynamicDash(callback_fn=echo, output_components=[Text], mcp_server=True))
    with connect(url) as agent:
        assert agent.set_form(specs=[{"name": "x", "type": "NumberInput"}])["ok"]
    with connect(url) as later:                   # a second session sees the form
        assert [i["id"] for i in later.describe_app()["inputs"]] == ["x"]


def test_close_ends_the_session(serve):
    app = connect(serve(FastDash(callback_fn=bars, mcp_server=True)))
    assert app._session_id
    app.close()
    assert app._session_id is None
    app.close()                                   # twice is fine


def test_unreachable_server_says_so():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(MCPError, match="could not reach .* Is the app running"):
        connect(f"http://127.0.0.1:{port}/mcp", timeout=5)


def test_app_without_mcp_names_the_cause(serve):
    url = serve(FastDash(callback_fn=bars))
    with pytest.raises(MCPError, match="mcp_server=True"):
        connect(url, timeout=10)


def test_url_must_be_http():
    with pytest.raises(ValueError, match="http"):
        connect("127.0.0.1:8080/mcp")


def test_extra_headers_are_sent(serve):
    fd = FastDash(callback_fn=bars, mcp_server=True)
    seen = []

    @fd.app.server.before_request
    def _record():
        from flask import request
        seen.append(request.headers.get("X-Token"))

    with connect(serve(fd), headers={"X-Token": "abc"}) as app:
        app.describe_app()
    assert seen and set(seen) == {"abc"}


def test_fastapi_backend_over_the_wire():
    uvicorn = pytest.importorskip("uvicorn")
    pytest.importorskip("fastapi")
    fd = FastDash(callback_fn=bars, mcp_server=True, backend="fastapi")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(fd.app.server, host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.1)
        with connect(f"http://127.0.0.1:{port}/mcp") as app:
            assert app.invoke(inputs={"n": 4})["outputs"] == {"output_output_1": 8}
    finally:
        server.should_exit = True
