"""Tests for the native-Dash MCP app surface (v0.4+).

fast_dash mounts Dash's native MCP server (``dash.mcp.enable_mcp_server``) on
the same Flask app and registers its stateful "drive the app" tools via
``dash.mcp.mcp_enabled``. These tests drive the mounted ``/mcp`` endpoint with
Flask's test client.

Note: Dash's ``mcp_enabled`` registry is process-global and keyed by tool name,
so fast_dash supports one MCP-enabled app per process. The ``clear_mcp_registry``
fixture enforces that here by resetting the registry before each test.
"""

from __future__ import annotations

import importlib.util
import json

import pandas as pd  # noqa: F401  (module-level for any -> pd.DataFrame hints)
import plotly.graph_objects as go
import pytest

from fast_dash import DynamicDash, FastDash, Graph, Markdown
from fast_dash.mcp import MCPState, enable_mcp

_HAS_DASH_MCP = importlib.util.find_spec("dash.mcp") is not None
requires_dash_mcp = pytest.mark.skipif(
    not _HAS_DASH_MCP, reason="Dash native MCP (dash>=4.3) not installed"
)
_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None
requires_fastapi = pytest.mark.skipif(
    not _HAS_FASTAPI, reason="fastapi backend extra not installed"
)


def _layout_ids(comp, out=None):
    out = set() if out is None else out
    cid = getattr(comp, "id", None)
    if isinstance(cid, str):
        out.add(cid)
    ch = getattr(comp, "children", None)
    if ch is not None:
        for c in (ch if isinstance(ch, (list, tuple)) else [ch]):
            if c is not None:
                _layout_ids(c, out)
    return out


@pytest.fixture(autouse=True)
def clear_mcp_registry():
    """Reset Dash's global MCP tool registry before each test (one app/process)."""
    try:
        from dash.mcp import _decorator
        _decorator.MCP_DECORATED_FUNCTIONS.clear()
    except Exception:
        pass
    yield


# --- helpers --------------------------------------------------------------- #

def _client_for(app):
    """enable_mcp on a fast_dash app and return (flask_test_client, call helpers)."""
    enable_mcp(app)
    client = app.app.server.test_client()
    _rpc(client, "initialize")
    return client


def _rpc(client, method, params=None, _id=1):
    r = client.post(
        "/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": _id,
                         "method": method, "params": params or {}}),
        headers={"Content-Type": "application/json"},
    )
    return r.get_json()


def _tools(client):
    res = _rpc(client, "tools/list")
    return [t["name"] for t in res.get("result", {}).get("tools", [])]


def _resources(client):
    res = _rpc(client, "resources/list")
    return [r["uri"] for r in res.get("result", {}).get("resources", [])]


def _call(client, name, args=None):
    res = _rpc(client, "tools/call", {"name": name, "arguments": args or {}})
    r = res.get("result", res)
    if isinstance(r, dict) and "structuredContent" in r:
        return r["structuredContent"].get("result", r["structuredContent"])
    return r


def _plain_app():
    def plot_bars(n: int = 6, color: str = "#1c7ed6") -> go.Figure:
        """Bar chart with n bars."""
        return go.Figure(go.Bar(x=list(range(n)), y=list(range(n))))
    return FastDash(callback_fn=plot_bars, mcp_server=True)


def _dynamic_app():
    def score(**fields):
        """Radar of submitted fields."""
        return go.Figure(), "ok"
    return DynamicDash(callback_fn=score, output_components=[Graph, Markdown],
                       placeholder="hi", mcp_server=True)


# --- MCPState -------------------------------------------------------------- #

class TestBackendOptIn:
    """Opt-in ASGI backend: real-time WebSocket push instead of the Interval."""

    def _fig_app(self, **kw):
        def fig(n: int = 3) -> go.Figure:
            return go.Figure(go.Bar(x=list(range(n)), y=list(range(n))))
        return FastDash(callback_fn=fig, mcp_server=True, **kw)

    def test_flask_default_uses_polling_interval(self):
        app = self._fig_app()
        assert app._backend is None
        assert type(app.server).__name__ == "Flask"
        assert "_mcp_poll" in _layout_ids(app.app.layout)

    @requires_fastapi
    def test_fastapi_backend_drops_interval_for_websocket(self):
        app = self._fig_app(backend="fastapi")
        assert app._backend == "fastapi"
        assert type(app.server).__name__ == "FastAPI"
        # No client-side Interval: push is via the persistent WebSocket drain.
        assert "_mcp_poll" not in _layout_ids(app.app.layout)
        assert "_mcp_mirror_store" in _layout_ids(app.app.layout)

    @requires_fastapi
    @requires_dash_mcp
    def test_fastapi_mcp_installs_request_context_middleware(self):
        # #99: the native /mcp route needs the request context set on the ASGI
        # backend (DashMiddleware skips non-/_dash- routes). enable_mcp installs
        # a middleware to do that, or /mcp 500s.
        from fast_dash.mcp import enable_mcp

        app = self._fig_app(backend="fastapi")
        enable_mcp(app)
        names = [getattr(m.cls, "__name__", "") for m in app.app.server.user_middleware]
        assert any("MCPRequestContext" in n for n in names)

    def test_run_routes_to_asgi_on_backend(self, monkeypatch):
        # #99: run() must serve the ASGI app via uvicorn, not Dash's
        # frame-walking main-thread path.
        app = self._fig_app(backend="fastapi") if _HAS_FASTAPI else None
        if app is None:
            import pytest as _pytest
            _pytest.skip("fastapi not installed")
        called = {}
        monkeypatch.setattr(app, "_run_asgi", lambda: called.setdefault("asgi", True))
        monkeypatch.setattr(app, "_start_mcp_server", lambda: None)
        app.run()
        assert called.get("asgi") is True

    @requires_fastapi
    def test_stream_with_backend_uses_native_websocket(self):
        def fig(n: int = 3) -> go.Figure:
            return go.Figure()
        # stream + ASGI backend now builds the native-WebSocket streaming path
        # (set_props) instead of raising; legacy flask-socketio stays on Flask.
        app = FastDash(callback_fn=fig, stream=True, backend="fastapi")
        assert app._native_stream is True
        assert type(app.server).__name__ == "FastAPI"
        assert hasattr(app, "stream_handler_native")

    def test_stream_on_flask_stays_legacy(self):
        def fig(n: int = 3) -> go.Figure:
            return go.Figure()
        app = FastDash(callback_fn=fig, stream=True)
        assert app._native_stream is False
        assert type(app.server).__name__ == "Flask"


class TestMCPState:
    def test_history_roundtrip_and_index(self):
        s = MCPState(history_size=2)
        i0 = s.append_history({"a": 1}, {"a": 1, "full": True})
        i1 = s.append_history({"a": 2}, {"a": 2})
        assert (i0, i1) == (0, 1)
        assert s.full_history[0]["full"] is True

    def test_history_evicts_oldest(self):
        s = MCPState(history_size=2)
        for k in range(3):
            s.append_history({"k": k}, {"k": k})
        assert len(s.history) == 2 and len(s.full_history) == 2
        assert 0 not in s.full_history  # evicted

    def test_pop_pending_inputs_atomic_swap(self):
        s = MCPState()
        s.pending_inputs["x"] = 1
        out = s.pop_pending_inputs()
        assert out == {"x": 1} and s.pending_inputs == {}

    def test_pop_pending_specs_and_outputs(self):
        s = MCPState()
        s.pending_specs = [{"name": "x", "type": "Text"}]
        s.pending_outputs["o"] = 5
        assert s.pop_pending_specs() == [{"name": "x", "type": "Text"}]
        assert s.pending_specs is None
        assert s.pop_pending_outputs() == {"o": 5}


# --- seeding --------------------------------------------------------------- #

class TestSeed:
    def test_input_mirror_seeded_from_defaults(self):
        from fast_dash.mcp import _seed_input_mirror

        def greet(name: str = "world", count: int = 3) -> str:
            return name * count
        app = FastDash(callback_fn=greet, mcp_server=True)
        _seed_input_mirror(app)
        assert app._mcp_state.inputs.get("name") == "world"
        assert app._mcp_state.inputs.get("count") == 3

    def test_dropdown_default_seeds_none_not_options(self):
        # #110: a str dropdown (list default) is options-as-default; its browser
        # value is None, so the mirror must seed None, not the options list.
        from fast_dash.mcp import _seed_input_mirror

        def pick(fruit: str = ["a", "b", "c"], tags: list = ["x"], n: int = 6) -> str:
            return str(fruit)
        app = FastDash(callback_fn=pick, mcp_server=True)
        _seed_input_mirror(app)
        assert app._mcp_state.inputs["fruit"] is None    # not ["a","b","c"]
        assert app._mcp_state.inputs["tags"] is None      # multiselect too
        assert app._mcp_state.inputs["n"] == 6            # scalar still seeded


# --- native mount + delegation --------------------------------------------- #

@requires_dash_mcp
class TestNativeMount:
    def test_mounts_and_lists_our_tools_plus_native(self):
        c = _client_for(_plain_app())
        tools = _tools(c)
        for t in ["set_input", "set_inputs", "invoke",
                  "get_invocation", "list_component_types"]:
            assert t in tools
        assert "get_dash_component" in tools  # native tool

    def test_internal_dash_callbacks_are_hidden(self):
        c = _client_for(_plain_app())
        tools = _tools(c)
        assert "process_input" not in tools
        assert "process_ack_outputs" not in tools

    def test_native_resources_present(self):
        c = _client_for(_plain_app())
        uris = _resources(c)
        assert "dash://layout" in uris
        assert "dash://components" in uris


# --- tools ----------------------------------------------------------------- #

@requires_dash_mcp
class TestTools:
    def test_set_input_updates_mirror_and_queue(self):
        app = _plain_app()
        c = _client_for(app)
        out = _call(c, "set_input", {"component_id": "n", "value": 9})
        assert out["ok"] is True
        assert app._mcp_state.inputs["n"] == 9
        assert app._mcp_state.pending_inputs == {"n": 9}

    def test_set_input_rejects_unknown_id(self):
        c = _client_for(_plain_app())
        out = _call(c, "set_input", {"component_id": "nope", "value": 1})
        assert out["ok"] is False
        assert "known_ids" in out

    def test_set_inputs_bulk(self):
        app = _plain_app()
        c = _client_for(app)
        out = _call(c, "set_inputs", {"inputs": {"n": 4, "color": "#fff"}})
        assert out["ok"] is True
        assert app._mcp_state.pending_inputs == {"n": 4, "color": "#fff"}

    def test_invoke_one_shot_runs_callback(self):
        app = _plain_app()
        c = _client_for(app)
        out = _call(c, "invoke", {"inputs": {"n": 4}})
        assert out["ok"] is True
        assert out["outputs"]  # produced an output summary
        assert app._mcp_state.inputs["n"] == 4

    def test_describe_app_typed_contract_and_readback(self):
        # #102: typed contract from the callback signature; #100: read back the
        # value an agent set (headless), which dash://components can't show.
        app = _plain_app()  # plot_bars(n: int = 6, color: str = "#1c7ed6")
        c = _client_for(app)
        _call(c, "set_input", {"component_id": "n", "value": 9})
        out = _call(c, "describe_app")
        by_id = {i["id"]: i for i in out["inputs"]}
        assert set(by_id) == {"n", "color"}            # contract names the params
        assert by_id["n"]["type"] == "integer"
        assert by_id["n"]["default"] == 6
        assert by_id["n"]["current_value"] == 9        # reflects set_input
        assert by_id["color"]["type"] == "string"
        assert by_id["color"]["current_value"] == "#1c7ed6"  # seeded default

    def test_dropdown_contract_consistent_and_invoke_parity(self):
        # #110: describe_app current_value is type-consistent (None, not a list),
        # and invoke() with defaults passes None (the browser's value), not the
        # options list — so a str param never silently receives a list.
        def pick(fruit: str = ["a", "b", "c"]) -> str:
            """Echo the type."""
            return type(fruit).__name__
        app = FastDash(callback_fn=pick, mcp_server=True)
        c = _client_for(app)
        fruit = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}["fruit"]
        assert fruit["type"] == "string"
        assert fruit["current_value"] is None           # not the options list
        assert fruit["options"] == ["a", "b", "c"]
        out = _call(c, "invoke")
        assert "NoneType" in json.dumps(out["outputs"])  # callback got None

    def test_describe_app_reflects_dynamic_form(self):
        # #106: after set_form, describe_app must report the agent-built form's
        # contract (id/type/props), not just the value mirror.
        app = _dynamic_app()
        c = _client_for(app)
        _call(c, "set_form", {"specs": [
            {"name": "communication", "type": "Slider", "props": {"min": 0, "max": 10}},
            {"name": "technical", "type": "Slider", "props": {"min": 0, "max": 10}},
        ]})
        by_id = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}
        assert set(by_id) == {"communication", "technical"}   # both discoverable
        assert by_id["communication"]["type"] == "Slider"
        assert by_id["communication"]["props"]["max"] == 10   # bounds exposed
        # set one field — both still listed; current_value updated for the set one.
        _call(c, "set_inputs", {"inputs": {"communication": 5}})
        by_id2 = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}
        assert set(by_id2) == {"communication", "technical"}
        assert by_id2["communication"]["current_value"] == 5

    def test_invoke_atomic_rejection(self):
        app = _plain_app()
        c = _client_for(app)
        out = _call(c, "invoke", {"inputs": {"n": 2, "bogus": 1}})
        assert out["ok"] is False
        assert "bogus" not in app._mcp_state.inputs
        assert app._mcp_state.pending_inputs == {}

    def test_get_invocation_roundtrip(self):
        app = _plain_app()
        c = _client_for(app)
        _call(c, "invoke", {"inputs": {"n": 5}})
        out = _call(c, "get_invocation", {"index": 0})
        assert out["ok"] is True
        assert "kwargs_summary" in out

    def test_list_component_types(self):
        c = _client_for(_plain_app())
        out = _call(c, "list_component_types")
        assert "Slider" in out["types"]

    def test_set_form_on_dynamic(self):
        app = _dynamic_app()
        c = _client_for(app)
        out = _call(c, "set_form",
                    {"specs": [{"name": "skill", "type": "Slider",
                                "props": {"min": 0, "max": 10}}]})
        assert out["ok"] is True and out["count"] == 1
        assert app._mcp_state.pending_specs is not None

    def test_set_form_rejected_on_plain_fastdash(self):
        # Single app in the process (registry cleared) -> set_form closes over
        # the plain FastDash and rejects.
        c = _client_for(_plain_app())
        out = _call(c, "set_form", {"specs": []})
        assert out["ok"] is False
        assert "DynamicDash" in out["error"]

    def test_set_form_validates_specs(self):
        c = _client_for(_dynamic_app())
        out = _call(c, "set_form", {"specs": [{"name": "x", "type": "NotReal"}]})
        assert out["ok"] is False
        assert "Unknown component type" in out["error"]
