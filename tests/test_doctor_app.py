"""fastdash doctor --app TARGET: boot the app, check /mcp, stop it (#395)."""

import json
import os
import sys
import textwrap
import time

import pytest

from fast_dash import cli
from fast_dash.doctor_app import AppProcess, parse_target

pytest.importorskip("mcp")

APP = textwrap.dedent('''
    from fast_dash import FastDash

    def plot_bars(n: int = 5) -> int:
        """Bars."""
        return n * 2

    app = FastDash(callback_fn=plot_bars, mcp_server=True, title="Plot Bars", port=8001)

    if __name__ == "__main__":
        app.run(port=9999, debug=True)       # doctor swaps in its own port, no reloader
''')


def _doctor(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["fastdash", "doctor", *args])
    code = cli.main()
    return code, capsys.readouterr().out


@pytest.fixture
def app_py(tmp_path):
    p = tmp_path / "app.py"
    p.write_text(APP, encoding="utf-8")
    return p


def test_script_is_booted_checked_and_stopped(app_py, monkeypatch, capsys):
    code, out = _doctor(monkeypatch, capsys, "--app", str(app_py), "--invoke", "--json",
                        "--wait", "120")
    report = json.loads(out)
    assert code == 0, report
    assert report["ok"] is True and report["contract"]["title"] == "Plot Bars"
    assert report["app"]["port"] not in (8001, 9999)
    assert report["url"] == f"http://127.0.0.1:{report['app']['port']}/mcp"
    assert report["app"]["running"] is True          # up for the check, stopped after
    assert any(s["step"] == "invoke" and "=10" in s["detail"] for s in report["steps"])


def test_module_attr_form_and_text_output(app_py, monkeypatch, capsys):
    monkeypatch.chdir(app_py.parent)
    code, out = _doctor(monkeypatch, capsys, "--app", "app:app", "--wait", "120")
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0].startswith("Starting app:app on port ")
    assert lines[1].startswith("Waiting for http://127.0.0.1:")
    assert "MCP surface healthy." in out and out.isascii()


def test_the_app_is_always_stopped(app_py):
    with AppProcess(str(app_py)) as proc:
        assert proc.proc.poll() is None
    assert proc.proc.poll() is not None


def test_a_crash_at_boot_fails_at_once_with_its_output(tmp_path, monkeypatch, capsys):
    p = tmp_path / "crash.py"
    p.write_text('raise RuntimeError("boom at boot \\u00e9")\n', encoding="utf-8")
    t = time.monotonic()
    code, out = _doctor(monkeypatch, capsys, "--app", str(p), "--wait", "300")
    assert code == 1 and time.monotonic() - t < 200        # well inside the window
    assert "Problem: the app exited with code 1 before /mcp answered" in out
    assert "RuntimeError: boom at boot" in out and out.isascii()
    assert "doctor_app.py" not in out and "runpy" not in out   # only the app's frames


def test_a_script_that_never_runs_gets_a_hint(tmp_path, monkeypatch, capsys):
    p = tmp_path / "noop.py"
    p.write_text("x = 1\n", encoding="utf-8")
    code, out = _doctor(monkeypatch, capsys, "--app", str(p), "--wait", "300")
    assert code == 1
    assert "exited with code 0" in out and f"--app {p}:app" in out
    code, out = _doctor(monkeypatch, capsys, "--app", f"{p}:x", "--wait", "120")
    assert code == 1 and "x is a int, not an app with .run()" in out


def test_check_mcp_give_up_ends_the_wait(monkeypatch):
    from fast_dash import mcp_check
    calls = []

    def fake(url, timeout, invoke, invoke_inputs):
        calls.append(1)
        return False, {"url": url, "steps": [], "ok": False, "error": "refused"}, True

    monkeypatch.setattr(mcp_check, "_attempt", fake)
    monkeypatch.setattr(mcp_check.time, "sleep", lambda s: None)
    answers = iter([None, "the app exited with code 3"])
    ok, report = mcp_check.check_mcp("u", wait=300, give_up=lambda: next(answers))
    assert not ok and len(calls) == 2
    assert report["error"] == "the app exited with code 3"


def test_parse_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    full = str(tmp_path / "app.py")
    assert parse_target("app.py") == ("file", "app.py", None)
    assert parse_target("app.py:app") == ("file", "app.py", "app")
    assert parse_target(full) == ("file", full, None)                  # C:\... on Windows
    assert parse_target(full + ":app") == ("file", full, "app")
    assert parse_target("mypkg.server:app") == ("module", "mypkg.server", "app")
    assert parse_target("mypkg.server:ns.app") == ("module", "mypkg.server", "ns.app")
    for bad in ("nope.py", "nope.py:app", "mypkg.server", "app.py:", ":app", "a b:app"):
        with pytest.raises(ValueError):
            parse_target(bad)


@pytest.mark.parametrize("args", [
    ["--app", "app.py", "--mcp", "http://x/mcp"],
    ["--app", "missing_file.py"],
    ["--app", "not a target"],
    ["--app", os.path.abspath(__file__), "--config", "claude"],
    ["--app", os.path.abspath(__file__), "--config", "claude", "--write"],
])
def test_app_flag_usage_errors(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["fastdash", "doctor", *args])
    with pytest.raises(SystemExit):
        cli.main()


def test_check_flags_accept_app(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "doctor_app", lambda target, **kw: seen.update(kw, target=target) or 0)
    monkeypatch.setattr(sys, "argv", ["fastdash", "doctor", "--app", os.path.abspath(__file__),
                                      "--invoke-input", "n=3", "--json", "--timeout", "9"])
    assert cli.main() == 0
    assert seen["invoke"] is True and seen["invoke_inputs"] == {"n": 3}
    assert seen["as_json"] is True and seen["timeout"] == 9 and seen["wait"] is None
