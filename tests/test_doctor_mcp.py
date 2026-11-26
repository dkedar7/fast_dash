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


# --config: paste-ready client config after a healthy check (#383)

def test_config_claude_prints_the_paste_ready_block(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=plot_bars, mcp_server=True, title="Plot Bars"))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--config", "claude",
                        "--timeout", "60")
    assert code == 0, out
    assert "Client config for Claude Code (.mcp.json):" in out
    block = json.dumps({"mcpServers": {"plot-bars": {"type": "http", "url": url}}})
    assert f"  {block}" in out
    assert f"claude mcp add --transport http plot-bars {url}" in out
    assert "Cursor" not in out and "VS Code" not in out
    assert out.isascii()


def test_config_all_uses_each_clients_shape(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=plot_bars, mcp_server=True, title="Plot Bars"))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--config", "all",
                        "--json", "--timeout", "60")
    report = json.loads(out)
    assert code == 0 and report["ok"] is True
    assert report["config"] == {
        "claude": {"mcpServers": {"plot-bars": {"type": "http", "url": url}}},
        "cursor": {"mcpServers": {"plot-bars": {"url": url}}},
        "vscode": {"servers": {"plot-bars": {"type": "http", "url": url}}},
    }


def test_config_is_not_printed_for_a_broken_surface(serve, monkeypatch, capsys):
    url = serve(FastDash(callback_fn=plot_bars))          # no mcp_server=True
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--config", "all",
                        "--timeout", "20")
    assert code == 1
    assert "Problem:" in out and "Client config" not in out


def test_config_without_mcp_is_an_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["fastdash", "doctor", "--config", "claude"])
    with pytest.raises(SystemExit):
        cli.main()


@pytest.mark.parametrize("title,name", [
    ("Plot Bars", "plot-bars"),
    ("  My App: v2!! ", "my-app-v2"),
    ("", "fast-dash-app"),
    (None, "fast-dash-app"),
    ("***", "fast-dash-app"),
])
def test_server_name_slugs_the_title(title, name):
    from fast_dash.mcp_check import server_name
    assert server_name(title) == name


# --write: merge the entry into the client's config file (#389)

from fast_dash.mcp_check import ConfigWriteError, write_client_config  # noqa: E402

URL = "http://127.0.0.1:8080/mcp"


def _read(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def test_write_creates_missing_file_and_folder(tmp_path):
    p = str(tmp_path / ".vscode" / "mcp.json")
    w = write_client_config(p, "vscode", URL, "plot-bars")
    assert w == {"path": p, "name": "plot-bars", "added": True, "updated": False, "kept": 0}
    assert _read(p) == {"servers": {"plot-bars": {"type": "http", "url": URL}}}


def test_write_keeps_other_servers_and_keys(tmp_path):
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps({
        "mcpServers": {"github": {"command": "gh-mcp"}, "db": {"url": "http://x/mcp"}},
        "other": 1,
    }), encoding="utf-8")
    w = write_client_config(str(p), "cursor", URL, "plot-bars")
    assert w["added"] and w["kept"] == 2
    data = _read(p)
    assert data["other"] == 1
    assert data["mcpServers"] == {"github": {"command": "gh-mcp"},
                                  "db": {"url": "http://x/mcp"},
                                  "plot-bars": {"url": URL}}


def test_write_is_idempotent(tmp_path):
    p = str(tmp_path / ".mcp.json")
    write_client_config(p, "claude", URL, "plot-bars")
    before = open(p, encoding="utf-8").read()
    w = write_client_config(p, "claude", URL, "plot-bars")
    assert w["added"] is False and w["updated"] is False
    assert open(p, encoding="utf-8").read() == before


def test_write_refuses_a_different_entry_without_force(tmp_path):
    p = tmp_path / ".mcp.json"
    original = {"mcpServers": {"plot-bars": {"type": "http", "url": "http://old/mcp"}}}
    p.write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ConfigWriteError, match="--force"):
        write_client_config(str(p), "claude", URL, "plot-bars")
    assert _read(p) == original
    w = write_client_config(str(p), "claude", URL, "plot-bars", force=True)
    assert w["updated"] is True and w["added"] is False
    assert _read(p)["mcpServers"]["plot-bars"]["url"] == URL


def test_write_never_rewrites_a_file_with_comments(tmp_path):
    p = tmp_path / "mcp.json"
    text = '{\n  // my servers\n  "servers": {}\n}\n'
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigWriteError, match="isn't plain JSON") as e:
        write_client_config(str(p), "vscode", URL, "plot-bars")
    assert '"plot-bars"' in str(e.value)                 # the entry to add by hand
    assert p.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("content", ["[]", '{"servers": []}'])
def test_write_refuses_unexpected_shapes(tmp_path, content):
    p = tmp_path / "mcp.json"
    p.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigWriteError):
        write_client_config(str(p), "vscode", URL, "plot-bars")
    assert p.read_text(encoding="utf-8") == content


def test_write_accepts_empty_file_and_bom(tmp_path):
    p = tmp_path / "a.json"
    p.write_text("", encoding="utf-8")
    assert write_client_config(str(p), "vscode", URL, "x")["added"]
    q = tmp_path / "b.json"
    q.write_bytes(b"\xef\xbb\xbf" + json.dumps({"servers": {"y": {"url": "u"}}}).encode())
    assert write_client_config(str(q), "vscode", URL, "x")["kept"] == 1


def test_cli_write_merges_into_the_default_path(serve, monkeypatch, capsys, tmp_path):
    import os
    monkeypatch.chdir(tmp_path)
    os.makedirs(".cursor")
    with open(os.path.join(".cursor", "mcp.json"), "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {"github": {"command": "gh-mcp"}}}, f)
    url = serve(FastDash(callback_fn=plot_bars, mcp_server=True, title="Plot Bars"))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--config", "cursor",
                        "--write", "--timeout", "60")
    assert code == 0, out
    path = os.path.join(".cursor", "mcp.json")
    assert f'Wrote server "plot-bars" to {path} (added; 1 other server kept).' in out
    assert "Client config for" not in out
    assert _read(path)["mcpServers"] == {"github": {"command": "gh-mcp"},
                                         "plot-bars": {"url": url}}
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--config", "cursor",
                        "--write", "--timeout", "60")
    assert code == 0 and "nothing to change" in out


def test_cli_write_conflict_exits_1_and_reports_json(serve, monkeypatch, capsys, tmp_path):
    p = tmp_path / "custom.json"
    p.write_text(json.dumps({"servers": {"plot-bars": {"url": "http://old/mcp"}}}),
                 encoding="utf-8")
    url = serve(FastDash(callback_fn=plot_bars, mcp_server=True, title="Plot Bars"))
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--config", "vscode", "--write",
                        "--config-path", str(p), "--json", "--timeout", "60")
    report = json.loads(out)
    assert code == 1 and report["ok"] is True and "--force" in report["write_error"]
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--config", "vscode", "--write",
                        "--config-path", str(p), "--force", "--json", "--timeout", "60")
    report = json.loads(out)
    assert code == 0 and report["wrote"]["updated"] is True


def test_cli_write_is_not_attempted_after_a_failed_check(serve, monkeypatch, capsys, tmp_path):
    p = tmp_path / "never.json"
    url = serve(FastDash(callback_fn=plot_bars))          # no mcp_server=True
    code, out = _doctor(monkeypatch, capsys, "--mcp", url, "--config", "vscode", "--write",
                        "--config-path", str(p), "--timeout", "20")
    assert code == 1 and not p.exists()


@pytest.mark.parametrize("args", [
    ["--mcp", "http://x/mcp", "--write"],
    ["--mcp", "http://x/mcp", "--config", "all", "--write"],
    ["--mcp", "http://x/mcp", "--config", "claude", "--force"],
    ["--mcp", "http://x/mcp", "--config", "claude", "--config-path", "a.json"],
])
def test_write_flag_usage_errors(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["fastdash", "doctor", *args])
    with pytest.raises(SystemExit):
        cli.main()
