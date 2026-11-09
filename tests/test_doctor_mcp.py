"""fastdash doctor --mcp URL: a live MCP smoke test (#341)."""

import json
import sys
import threading
import warnings

import pytest
from werkzeug.serving import make_server

from fast_dash import FastDash, cli

pytest.importorskip("mcp")


def plot_bars(n: int = 5, color: str = "#ff0000") -> int:
    """Bars."""
    return n


@pytest.fixture
def serve():
    servers = []

    def _serve(app):
        srv = make_server("127.0.0.1", 0, app.server, threaded=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{srv.server_port}/mcp"

    yield _serve
    for srv in servers:
        srv.shutdown()


def _doctor(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["fastdash", "doctor", *args])
    code = cli.main()
    return code, capsys.readouterr().out


def test_healthy_app_passes(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=plot_bars, mcp_server=True, title="Plot Bars"))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--timeout", "60")
    assert code == 0, out
    for step in ("initialize", "list_tools", "list_resources", "describe_app"):
        assert f"  {step}" in out
    assert "describe_app" in out and "invoke" in out
    assert "Plot Bars: 2 inputs (n:integer, color:string), 1 output (output_n:Text)" in out
    assert out.rstrip().endswith("MCP surface healthy.")
    assert out.isascii()


def test_json_report_carries_the_contract(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=plot_bars, mcp_server=True))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--json", "--timeout", "60")
    report = json.loads(out)
    assert code == 0 and report["ok"] is True
    assert [i["id"] for i in report["contract"]["inputs"]] == ["n", "color"]
    assert "describe_app" in report["tools"]


def test_app_without_mcp_names_the_cause(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=plot_bars))          # no mcp_server=True
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--timeout", "20")
    assert code == 1
    assert "Problem:" in out and "mcp_server=True" in out


def test_unreachable_server_fails_fast(monkeypatch, capsys):
    code, out = _doctor(monkeypatch, capsys, "--mcp", "http://127.0.0.1:9/mcp",
                        "--timeout", "20")
    assert code == 1
    assert "Problem:" in out and "could not reach" in out


def test_json_without_mcp_is_an_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["fastdash", "doctor", "--json"])
    with pytest.raises(SystemExit):
        cli.main()


def test_missing_mcp_package_says_how_to_install(monkeypatch):
    from fast_dash import mcp_check

    def no_mcp():
        raise mcp_check.CheckFailed(
            "the 'mcp' package is needed to connect as an MCP client: pip install mcp")
    monkeypatch.setattr(mcp_check, "_client", no_mcp)
    ok, report = mcp_check.check_mcp("http://127.0.0.1:9/mcp", timeout=5)
    assert not ok and "pip install mcp" in report["error"]
