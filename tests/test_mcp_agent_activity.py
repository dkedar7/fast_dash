"""#377: a human watching the page can tell an agent's change from their own."""

import json

import pytest

from fast_dash import DynamicDash, FastDash, PasswordInput

NOTICE = "notification-container.sendNotifications"


def multiply(n: int = 2, factor: int = 3) -> str:
    """Multiply."""
    return f"RESULT={n * factor}"


def _drain_key(fd):
    keys = [k for k, v in fd.app.callback_map.items()
            if NOTICE in k and any(i["id"] == "_mcp_poll" for i in v["inputs"])]
    return keys[0] if keys else None


def _poll(fd):
    """One Interval tick of the browser drain; the notices it sends, if any."""
    key = _drain_key(fd)
    outs = [{"id": o.split(".")[0], "property": o.split(".")[1].split("@")[0]}
            for o in key.strip(".").split("...")]
    if not key.startswith(".."):            # a single output is not a list
        outs = outs[0]
    client = fd.app.server.test_client()
    r = client.post("/_dash-update-component", json={
        "output": key, "outputs": outs,
        "inputs": [{"id": "_mcp_poll", "property": "n_intervals", "value": 1}],
        "changedPropIds": ["_mcp_poll.n_intervals"]})
    if r.status_code == 204:                 # every output was no_update
        return []
    assert r.status_code == 200, r.data
    sent = r.get_json()["response"].get("notification-container", {})
    return [n["message"] for n in sent.get("sendNotifications", [])]


def test_set_input_and_invoke_show_a_notice_in_the_browser():
    fd = FastDash(callback_fn=multiply, mcp_server=True)
    with fd.mcp_test_client() as app:
        app.set_input("n", 42)
        assert _poll(fd) == ["An agent set n = 42"]
        assert _poll(fd) == []                # each notice is shown once
        app.set_inputs({"n": 5, "factor": 7})
        app.invoke(inputs={"n": 6})
        assert _poll(fd) == ["An agent set n = 5, factor = 7",
                             "An agent is running the app with n = 6"]
        app.invoke()
        assert _poll(fd) == ["An agent is running the app"]


def test_a_rejected_call_shows_nothing():
    fd = FastDash(callback_fn=multiply, mcp_server=True)
    with fd.mcp_test_client() as app:
        assert app.set_input("nope", 1)["ok"] is False
        assert app.set_inputs({"n": 1, "nope": 2})["ok"] is False
        assert app.invoke(inputs={"nope": 1})["ok"] is False
        assert fd._mcp_state.pending_notices == []


def test_a_secret_never_reaches_a_notice():
    def login(key: PasswordInput = "", n: int = 1) -> str:
        """Fails with the key in the error on purpose."""
        raise ValueError(f"bad key {key}")

    fd = FastDash(callback_fn=login, mcp_server=True)
    with fd.mcp_test_client() as app:
        app.set_input("key", "hunter2-secret")
        app.set_inputs({"key": "hunter2-secret", "n": 2})
        app.invoke(inputs={"key": "hunter2-secret"})
        notes = _poll(fd)
    assert len(notes) == 4
    assert notes[-1] == "The agent's run failed (ValueError)"
    assert "hunter2-secret" not in json.dumps(notes)
    assert "********" in notes[0]


def test_a_long_value_is_shortened():
    def echo(text: str = "") -> str:
        """Echo."""
        return text

    fd = FastDash(callback_fn=echo, mcp_server=True)
    with fd.mcp_test_client() as app:
        app.set_input("text", "x" * 500)
        (note,) = _poll(fd)
    assert len(note) < 80 and note.endswith("...")


def test_an_app_without_inputs_still_gets_notices():
    def hello() -> str:
        """Hi."""
        return "hi"

    fd = FastDash(callback_fn=hello, mcp_server=True)
    with fd.mcp_test_client() as app:
        app.invoke()
        assert _poll(fd) == ["An agent is running the app"]


def test_off_keeps_the_silent_mirror():
    fd = FastDash(callback_fn=multiply, mcp_server=True, agent_activity=None)
    with fd.mcp_test_client() as app:
        app.set_input("n", 42)
        assert fd._mcp_state.pending_notices == []
    assert _drain_key(fd) is None
    assert fd._mcp_state.pending_inputs == {"n": 42}


def test_a_bad_mode_is_refused():
    with pytest.raises(ValueError, match="agent_activity must be 'notify'.*None"):
        FastDash(callback_fn=multiply, mcp_server=True, agent_activity="highlight")
    with pytest.raises(ValueError, match="agent_activity"):
        DynamicDash(callback_fn=lambda **kw: "x", agent_activity=True)


def test_set_form_on_dynamicdash_shows_a_notice():
    fd = DynamicDash(callback_fn=lambda **kw: str(kw), mcp_server=True)
    with fd.mcp_test_client() as app:
        assert app.set_form(specs=[{"name": "a", "type": "Text"},
                                   {"name": "b", "type": "NumberInput"},
                                   {"name": "_m", "type": "Markdown", "value": "hi"}])["ok"]
        assert _poll(fd) == ["An agent rebuilt the form (2 fields)"]


def test_fastapi_backend_queues_notices():
    pytest.importorskip("fastapi")
    fd = FastDash(callback_fn=multiply, mcp_server=True, backend="fastapi")
    with fd.mcp_test_client() as app:
        app.set_input("n", 3)
    # The WebSocket drain pops these and set_props them to the toast container.
    assert fd._mcp_state.pending_notices == ["An agent set n = 3"]


def test_unshown_notices_neither_pile_up_nor_go_stale(monkeypatch):
    import fast_dash.mcp as fdm
    fd = FastDash(callback_fn=multiply, mcp_server=True)
    clock = [1000.0]
    monkeypatch.setattr(fdm.time, "monotonic", lambda: clock[0])
    with fd.mcp_test_client() as app:
        for i in range(50):                  # nobody has the page open
            app.set_input("n", i)
        assert len(fd._mcp_state.pending_notices) == fdm.NOTICE_MAX_QUEUED
        clock[0] += fdm.NOTICE_MAX_AGE_S + 1
        app.set_input("n", 99)
        # A page loaded now sees only what is fresh.
        assert fd._mcp_state.pop_pending_notices() == ["An agent set n = 99"]
