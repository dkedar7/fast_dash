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


# --- --invoke: run the app once over the wire (#357) ----------------------------

calls = []


def counted(n: int = 5, label: str = "hi") -> str:
    """Records each run."""
    calls.append(n)
    return f"{label} {n * 2}"


def broken(n: int = 5, label: str = "hi") -> str:
    """Looks fine in describe_app; raises on every run."""
    raise RuntimeError("backend dependency unavailable")


def needs_n(n: int, label: str = "hi") -> str:
    """n has no default."""
    return f"{label} {n * 2}"


def test_invoke_runs_the_app_once(serve, monkeypatch, capsys):
    calls.clear()
    url = serve(FastDash(callback_fn=counted, mcp_server=True))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--invoke", "--timeout", "60")
    assert code == 0, out
    assert "  invoke           OK   ran" in out and "output_output_1=hi 10" in out
    assert out.rstrip().endswith("MCP surface healthy.") and out.isascii()
    assert calls == [5]


def test_without_invoke_the_callback_never_runs(serve, monkeypatch, capsys):
    calls.clear()
    url = serve(FastDash(callback_fn=counted, mcp_server=True))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--timeout", "60")
    assert code == 0 and "  invoke  " not in out
    assert calls == []


def test_a_raising_callback_fails_only_with_invoke(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=broken, mcp_server=True))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--timeout", "60")
    assert code == 0, out                       # the contract alone looks healthy
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--invoke", "--timeout", "60")
    assert code == 1
    assert ("Problem: invoke ran and the callback failed: "
            "RuntimeError: backend dependency unavailable") in out
    assert "  describe_app     OK" in out


def test_a_required_input_needs_invoke_input(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=needs_n, mcp_server=True))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--invoke", "--timeout", "60")
    assert code == 1 and "n has no value. Pass one with --invoke-input NAME=VALUE." in out
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--invoke-input", "n=7",
                        "--invoke-input", "label=yo", "--timeout", "60")   # implies --invoke
    assert code == 0, out
    assert "output_output_1=yo 14" in out     # 7 parsed as JSON, "yo" kept as text


def test_a_rejected_or_unknown_input_is_named(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=counted, mcp_server=True))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--invoke-input", "n=\"x\"",
                        "--timeout", "60")
    assert code == 1 and "Problem: invoke rejected the inputs: n: expected an integer" in out
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--invoke-input", "m=1",
                        "--timeout", "60")
    assert code == 1 and "names no input of this app: m (its inputs: n, label)" in out


def test_json_report_carries_the_invoke_result(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=counted, mcp_server=True))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--invoke", "--json", "--timeout", "60")
    report = json.loads(out)
    assert code == 0 and report["ok"] is True
    assert report["invoke"]["ok"] is True
    assert report["invoke"]["outputs"] == {"output_output_1": "hi 10"}


@pytest.mark.parametrize("argv", [["--invoke"], ["--invoke-input", "n=1"],
                                  ["--mcp", "u", "--invoke-input", "n"]])
def test_invoke_flag_misuse_is_an_error(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["fastdash", "doctor", *argv])
    with pytest.raises(SystemExit):
        cli.main()
