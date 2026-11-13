"""fastdash doctor --stream URL: a real-wire streaming check (#352)."""

import json
import sys
import threading
import time

import pytest
from werkzeug.serving import make_server

from fast_dash import FastDash, cli
from fast_dash.stream_check import _payload, _split_outputs


def slow_count(n: int = 3) -> str:
    """Count."""
    text = ""
    for i in range(1, n + 1):
        text += f"tick {i}\n"
        yield text
        time.sleep(0.3)


def all_at_once(n: int = 3) -> str:
    """Returns without yielding: nothing to push while it runs."""
    time.sleep(0.3)
    return "done"


def plain(n: int = 3) -> str:
    """Not streaming."""
    return "x"


@pytest.fixture
def serve():
    servers = []

    def _serve(app, threaded=True):
        srv = make_server("127.0.0.1", 0, app.server, threaded=threaded)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_port}/"

    yield _serve
    for srv in servers:
        srv.shutdown()


def _doctor(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["fastdash", "doctor", *args])
    code = cli.main()
    return code, capsys.readouterr().out


def test_streaming_app_passes_over_socketio(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=slow_count, stream=True))
    code, out = _doctor(monkeypatch, capsys, "--stream", url, "--timeout", "30")
    assert code == 0, out
    assert "socket.io (Flask backend)" in out
    assert "3 updates arrived while the Run was in flight" in out
    assert out.rstrip().endswith("Streaming wire healthy.")
    assert out.isascii()


def test_json_report_carries_the_frames(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=slow_count, stream=True))
    code, out = _doctor(monkeypatch, capsys, "--stream", url, "--json", "--timeout", "30")
    report = json.loads(out)
    assert code == 0 and report["ok"] is True and report["transport"] == "socket.io"
    assert [f["value"] for f in report["frames"]] == [
        "tick 1\n", "tick 1\ntick 2\n", "tick 1\ntick 2\ntick 3\n"]
    times = [f["t"] for f in report["frames"]]
    assert times == sorted(times) and times[-1] - times[0] > 0.4   # spread out, not batched


def test_no_update_while_running_fails_and_names_the_fix(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=all_at_once, stream=True))
    code, out = _doctor(monkeypatch, capsys, "--stream", url, "--timeout", "30")
    assert code == 1
    assert "Problem: the Run finished but no update arrived while it ran" in out
    assert "backend='fastapi'" in out


def test_app_without_stream_names_the_cause(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=plain))
    code, out = _doctor(monkeypatch, capsys, "--stream", url, "--timeout", "10")
    assert code == 1 and "Build it with stream=True" in out


def test_unreachable_server_fails_fast(monkeypatch, capsys):
    code, out = _doctor(monkeypatch, capsys, "--stream", "http://127.0.0.1:9/", "--timeout", "10")
    assert code == 1 and "could not reach" in out


def test_mcp_and_stream_together_is_an_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["fastdash", "doctor", "--mcp", "u", "--stream", "u"])
    with pytest.raises(SystemExit):
        cli.main()


def test_streaming_app_passes_over_native_websocket(monkeypatch, capsys):
    uvicorn = pytest.importorskip("uvicorn")
    pytest.importorskip("fastapi")
    pytest.importorskip("websockets")
    import socket

    app = FastDash(callback_fn=slow_count, stream=True, backend="fastapi")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app.server, host="127.0.0.1", port=port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.1)
        code, out = _doctor(monkeypatch, capsys, "--stream", f"http://127.0.0.1:{port}/",
                            "--timeout", "30")
        assert code == 0, out
        assert "native WebSocket (FastAPI backend)" in out
        assert "3 updates arrived while the Run was in flight" in out
    finally:
        server.should_exit = True


def test_payload_presses_run_with_the_layout_values():
    cb = {"output": "..out.children...note.sendNotifications..",
          "inputs": [{"id": "n", "property": "value"},
                     {"id": "submit_inputs", "property": "n_clicks"}],
          "state": [{"id": "socketio", "property": "socketId"}]}
    p = _payload(cb, {"n": {"value": 7}}, socket_id="abc")
    assert [i["value"] for i in p["inputs"]] == [7, 1]
    assert p["state"][0]["value"] == "abc"
    assert p["changedPropIds"] == ["submit_inputs.n_clicks"]
    assert _split_outputs(cb["output"]) == [
        {"id": "out", "property": "children"},
        {"id": "note", "property": "sendNotifications"}]
