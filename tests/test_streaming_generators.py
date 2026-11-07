"""Regression tests for streaming (0.7.0 batch 3).

#212 a ``yield`` callback no longer 500s a UI Run: each value streams, the last
     one is the result (and it just drains when ``stream=False``).
#207 MCP ``invoke`` returns the drained value, not a generator repr.
#233 ``update()`` takes the bare name or the ``output_``-prefixed id, and a bad
     name gets an error listing the valid ones.
"""
import json
import warnings
from types import SimpleNamespace

import pytest

import fast_dash.fast_dash as fdm
from fast_dash import FastDash, update
from fast_dash.utils import _drain_generator, _find_stream_output

warnings.filterwarnings("ignore")


def _ui_run(app, sock="SID1"):
    """POST a genuine Run click; return (status, response, socket.io pushes)."""
    emitted = []
    orig = fdm.emit
    fdm.emit = lambda cid, payload, **kw: emitted.append((cid, payload["value"]))
    try:
        first = app.outputs_with_ids[0].id
        key = next(k for k, v in app.app.callback_map.items()
                   if "callback" in v and f"{first}." in k
                   and any(i["id"] == "submit_inputs" for i in v["inputs"]))
        cb = app.app.callback_map[key]
        vals = {c.id: getattr(c, c.component_property, None) for c in app.inputs_with_ids}

        def spec(d, value):
            return {"id": d["id"], "property": d["property"], "value": value}
        inputs = [spec(d, 1 if d["id"] == "submit_inputs" else vals.get(d["id"]))
                  for d in cb["inputs"]]
        state = [spec(d, sock if d["property"] == "socketId" else None)
                 for d in cb.get("state", [])]
        outs = [{"id": o.split(".")[0], "property": o.split(".")[1].split("@")[0]}
                for o in key.strip(".").split("...")]
        client = app.app.server.test_client()
        client.get("/")
        r = client.post("/_dash-update-component", json={
            "output": key, "outputs": outs, "inputs": inputs, "state": state,
            "changedPropIds": ["submit_inputs.n_clicks"]})
        return r.status_code, json.dumps(r.get_json()), [v for _, v in emitted]
    finally:
        fdm.emit = orig


def slow_count(n: int = 3) -> str:
    out = ""
    for i in range(1, n + 1):
        out += f"tick {i}\n"
        yield out


FINAL = "tick 1\ntick 2\ntick 3\n"


# --- #212 ------------------------------------------------------------------ #

def test_generator_streams_each_value_and_ends_on_the_last():
    code, resp, pushes = _ui_run(FastDash(callback_fn=slow_count, stream=True))
    assert code == 200
    assert pushes == ["tick 1\n", "tick 1\ntick 2\n", FINAL]
    assert json.dumps(FINAL)[1:-1] in resp
    assert "went wrong" not in resp


def test_generator_without_stream_just_drains():
    code, resp, pushes = _ui_run(FastDash(callback_fn=slow_count))
    assert code == 200 and pushes == []
    assert json.dumps(FINAL)[1:-1] in resp


def test_yielded_tuple_streams_to_each_output():
    def two(n: int = 2):
        for i in range(n):
            yield f"a{i}", f"b{i}"
    fd = FastDash(callback_fn=two, outputs=["Text", "Text"], stream=True)
    code, resp, pushes = _ui_run(fd)
    assert code == 200
    assert pushes == ["a0", "b0", "a1", "b1"]


def test_drain_generator_passthrough_for_plain_values():
    assert _drain_generator(5) == 5
    assert _drain_generator(x for x in []) is None


# --- #207 ------------------------------------------------------------------ #

def test_mcp_invoke_drains_generator():
    pytest.importorskip("dash.mcp")
    app = FastDash(callback_fn=slow_count, stream=True, mcp_server=True)
    client = app.app.server.test_client()

    def rpc(method, params=None):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        return client.post("/mcp", data=json.dumps(body),
                           headers={"Content-Type": "application/json"}).get_json()
    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}})
    res = rpc("tools/call", {"name": "invoke", "arguments": {"inputs": {"n": 3}}})
    assert res["result"]["structuredContent"]["result"]["outputs"] == {
        "output_output_1": FINAL}


# --- #233 ------------------------------------------------------------------ #

@pytest.mark.parametrize("uid", ["output", "output_output"])
def test_update_accepts_bare_name_and_advertised_id(uid):
    def stream_text(input_text: str = "hi") -> str:
        output = ""
        for ch in "abc":
            output += ch
            update(uid, output)
        return output
    code, resp, pushes = _ui_run(FastDash(callback_fn=stream_text, stream=True))
    assert code == 200 and "went wrong" not in resp
    assert pushes == ["a", "ab", "abc"]


def test_update_bad_name_lists_valid_names():
    def stream_text(input_text: str = "hi") -> str:
        output = "x"
        update("nope", output)
        return output
    code, resp, pushes = _ui_run(FastDash(callback_fn=stream_text, stream=True))
    assert "no output named 'nope'" in resp and "'output'" in resp


def test_find_stream_output_with_function_prefix():
    outs = [SimpleNamespace(id="add_output_total")]
    for name in ("total", "output_total", "add_output_total"):
        assert _find_stream_output(outs, name, prefix="add_").id == "add_output_total"
    with pytest.raises(ValueError, match="one of: 'total'"):
        _find_stream_output(outs, "nope", prefix="add_")


# --- #333 ------------------------------------------------------------------ #

def _ui_run_real_emit(app, sock):
    """Like _ui_run, but with flask-socketio's real emit (no patch)."""
    orig = fdm.emit
    try:
        fdm.emit = orig
        first = app.outputs_with_ids[0].id
        key = next(k for k, v in app.app.callback_map.items()
                   if "callback" in v and f"{first}." in k
                   and any(i["id"] == "submit_inputs" for i in v["inputs"]))
        cb = app.app.callback_map[key]
        vals = {c.id: getattr(c, c.component_property, None) for c in app.inputs_with_ids}

        def spec(d, value):
            return {"id": d["id"], "property": d["property"], "value": value}
        inputs = [spec(d, 1 if d["id"] == "submit_inputs" else vals.get(d["id"]))
                  for d in cb["inputs"]]
        state = [spec(d, sock if d["property"] == "socketId" else None)
                 for d in cb.get("state", [])]
        outs = [{"id": o.split(".")[0], "property": o.split(".")[1].split("@")[0]}
                for o in key.strip(".").split("...")]
        client = app.app.server.test_client()
        client.get("/")
        r = client.post("/_dash-update-component", json={
            "output": key, "outputs": outs, "inputs": inputs, "state": state,
            "changedPropIds": ["submit_inputs.n_clicks"]})
        return r.status_code, json.dumps(r.get_json())
    finally:
        fdm.emit = orig


def test_stream_without_a_socket_returns_the_final_output(monkeypatch):
    # A plain sync-worker `gunicorn app:server` never connects socket.io, so
    # the Run arrives with socketId None. Emitting then read flask.request.sid
    # and raised AttributeError, and the page showed nothing (#333).
    import fast_dash.utils as fdu
    monkeypatch.setattr(fdu, "_warned_no_socket", False)
    app = FastDash(callback_fn=slow_count, stream=True)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        status, body = _ui_run_real_emit(app, sock=None)
        _ui_run_real_emit(app, sock=None)                 # warns only once
    assert status == 200
    assert json.dumps(FINAL)[1:-1] in body
    found = [x for x in w if "no socket.io connection" in str(x.message)]
    assert len(found) == 1
    msg = str(found[0].message)
    assert "backend='fastapi'" in msg and "uvicorn app:server" in msg
    assert msg.isascii()


def test_stream_with_a_socket_still_pushes():
    app = FastDash(callback_fn=slow_count, stream=True)
    status, body, pushes = _ui_run(app, sock="SID1")
    assert status == 200 and pushes and pushes[-1] == FINAL


@pytest.mark.parametrize("sidecar", [False, True])
def test_chat_without_a_socket_says_why(sidecar):
    # Flask chat streams each turn over socket.io only; without a connection
    # the reply never lands, so the turn answers with the fix instead (#333).
    def agent(query, ctx=None):
        yield "hello"
    app = (FastDash(callback_fn=lambda a=1: str(a), chat=agent) if sidecar
           else FastDash(callback_fn=lambda query: "hi", chat=True))
    key, cb = next((k, v) for k, v in app.app.callback_map.items()
                   if "callback" in v and any(i["id"] == "chat-submit-store"
                                              for i in v["inputs"]))
    outs = [{"id": o.split(".")[0], "property": o.split(".")[1].split("@")[0]}
            for o in key.strip(".").split("...")]
    state = [{"id": d["id"], "property": d["property"], "value": None}
             for d in cb.get("state", [])]
    client = app.app.server.test_client()
    client.get("/")
    r = client.post("/_dash-update-component", json={
        "output": key, "outputs": outs,
        "inputs": [{"id": "chat-submit-store", "property": "data",
                    "value": {"q": "hi", "n": 1}}],
        "state": state, "changedPropIds": ["chat-submit-store.data"]})
    assert r.status_code == 200
    body = json.dumps(r.get_json())
    assert "no socket.io connection" in body and "backend='fastapi'" in body
