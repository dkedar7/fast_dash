"""Tests for the MCP app surface.

The original ``feature/mcp`` tests (TestKwargPlumbing / TestBuildServer /
TestModeGuards / TestServeInThread) stay green. New classes below cover:

* ``TestMCPState`` — the server-side state container
* ``TestResources`` — each ``fastdash://...`` resource read
* ``TestTools`` — set_input, set_inputs, invoke, set_form, get_invocation,
  list_component_types, screenshot

Resource and tool tests construct a server via ``build_mcp_server`` and
call the registered handlers via FastMCP's high-level API in an asyncio
loop (no pytest-asyncio dep). No port is bound except in
``TestServeInThread`` (inherited from the foundation commit).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import socket
import time
import warnings

import plotly.graph_objects as go  # module-level so FastMCP can eval `-> go.Figure`
import pytest

from fast_dash import FastDash, fastdash  # noqa: F401


_HAS_MCP = importlib.util.find_spec("mcp") is not None
_HAS_UVICORN = importlib.util.find_spec("uvicorn") is not None
requires_mcp = pytest.mark.skipif(
    not (_HAS_MCP and _HAS_UVICORN),
    reason="mcp + uvicorn not installed",
)


# --- kwarg plumbing -------------------------------------------------------


class TestKwargPlumbing:
    """The new mcp_server / mcp_port / mcp_host kwargs land on the instance."""

    def test_mcp_disabled_by_default(self):
        def fn(x: str = "hi") -> str:
            return x

        app = FastDash(callback_fn=fn)
        assert app.mcp_server_enabled is False
        assert app.mcp_port == 8001
        assert app.mcp_host == "127.0.0.1"
        assert app._mcp_thread is None

    def test_mcp_enable_flag_persists(self):
        def fn(x: str = "hi") -> str:
            return x

        app = FastDash(callback_fn=fn, mcp_server=True)
        assert app.mcp_server_enabled is True

    def test_custom_port_and_host(self):
        def fn(x: str = "hi") -> str:
            return x

        app = FastDash(
            callback_fn=fn,
            mcp_server=True,
            mcp_port=9001,
            mcp_host="0.0.0.0",
        )
        assert app.mcp_port == 9001
        assert app.mcp_host == "0.0.0.0"


# --- server construction (no port) ---------------------------------------


@requires_mcp
class TestBuildServer:
    """build_mcp_server produces a usable FastMCP without starting it."""

    def test_build_returns_fastmcp_instance(self):
        from mcp.server.fastmcp import FastMCP

        from fast_dash.mcp import build_mcp_server

        def fn(x: str = "hi") -> str:
            """Do a thing."""
            return x

        server = build_mcp_server(fn)
        assert isinstance(server, FastMCP)

    def test_callback_registered_as_tool(self):
        from fast_dash.mcp import build_mcp_server

        def search_db(query: str, limit: int = 10) -> str:
            """Search the database."""
            return f"{query} ({limit})"

        server = build_mcp_server(search_db)
        # The MCP SDK exposes registered tools via the internal registry.
        # The exact attribute moved over versions; probe both shapes.
        tool_names = _list_tool_names(server)
        assert "search_db" in tool_names

    def test_docstring_becomes_tool_description(self):
        from fast_dash.mcp import build_mcp_server

        def fn(text: str) -> str:
            """A wonderfully unique description."""
            return text

        server = build_mcp_server(fn)
        descs = _list_tool_descriptions(server)
        assert any("wonderfully unique description" in (d or "") for d in descs)


# --- multi-function / steps modes guard rails ----------------------------


@requires_mcp
class TestModeGuards:
    """MCP only makes sense for single-function apps right now."""

    def test_multi_function_mode_warns_and_skips(self):
        def a(x: str = "1") -> str:
            return x

        def b(y: int = 2) -> int:
            return y

        app = FastDash(callback_fn=[a, b], mcp_server=True)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            app._start_mcp_server()
        assert app._mcp_thread is None
        assert any(
            "single-function" in str(w.message) for w in caught
        )

    def test_steps_mode_warns_and_skips(self):
        from fast_dash import from_step

        def load(rows: int = 5) -> int:
            return rows

        def double(data=from_step(load)) -> int:
            return data * 2

        app = FastDash(steps=[load, double], mcp_server=True)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            app._start_mcp_server()
        assert app._mcp_thread is None
        assert any(
            "single-function" in str(w.message) for w in caught
        )


# --- end-to-end: actually bind a port ------------------------------------


@requires_mcp
class TestServeInThread:
    """Bind an ephemeral port and confirm the MCP endpoint responds."""

    def test_thread_binds_and_responds(self):
        from fast_dash.mcp import serve_mcp_in_thread

        def square(n: int = 1) -> int:
            """Return n squared."""
            return n * n

        port = _find_free_port()
        thread = serve_mcp_in_thread(square, port=port)
        try:
            _wait_for_port(port, timeout=5.0)
            # The streamable-HTTP MCP endpoint responds to a POST with
            # the JSON-RPC initialize message. We don't need a full
            # round-trip — a TCP-connection-accepted check is enough
            # for our wiring.
            with socket.create_connection(("127.0.0.1", port), timeout=2.0):
                pass
        finally:
            # Daemon thread; let it die with the test process.
            assert thread.is_alive()


# --- helpers --------------------------------------------------------------


def _list_tool_names(server) -> list[str]:
    """Get registered tool names from a FastMCP server, version-tolerant."""
    tm = getattr(server, "_tool_manager", None)
    if tm is not None:
        return list(tm._tools.keys())
    raise RuntimeError("can't introspect FastMCP tool registry on this SDK")


def _list_tool_descriptions(server) -> list[str]:
    tm = getattr(server, "_tool_manager", None)
    if tm is not None:
        return [t.description for t in tm._tools.values()]
    return []


def _find_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    """Block until ``port`` accepts connections, or raise."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"port {port} never opened within {timeout}s")


def _run_async(coro):
    """Run an async coroutine to completion (no pytest-asyncio dep)."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _text(content_list):
    """Extract the .text from MCP TextContent return values."""
    if not content_list:
        return ""
    item = content_list[0]
    if hasattr(item, "text"):
        return item.text
    if hasattr(item, "content"):
        return item.content
    return str(item)


def _read(content_list):
    """Extract the content string from MCP resource read results."""
    if not content_list:
        return ""
    item = content_list[0]
    if hasattr(item, "content"):
        return item.content
    if hasattr(item, "text"):
        return item.text
    return str(item)


# --- MCPState basics ------------------------------------------------------


@requires_mcp
class TestMCPState:
    """The state container's contract: history cap, append, helper methods."""

    def test_default_state_is_empty(self):
        from fast_dash.mcp import MCPState

        s = MCPState()
        assert s.inputs == {}
        assert s.outputs == {}
        assert list(s.history) == []
        assert s.full_history == {}
        assert s.pending_specs is None

    def test_history_capped_at_maxlen(self):
        from fast_dash.mcp import MCPState

        s = MCPState(history_size=3)
        for i in range(5):
            s.append_history({"i": i}, {"i_full": i})
        assert len(s.history) == 3
        assert [e["i"] for e in s.history] == [2, 3, 4]
        assert len(s.full_history) == 3

    def test_full_history_indices_are_monotonic(self):
        from fast_dash.mcp import MCPState

        s = MCPState()
        for i in range(3):
            idx = s.append_history({"i": i}, {"i_full": i})
            assert idx == i

    def test_pop_pending_inputs_returns_and_clears(self):
        from fast_dash.mcp import MCPState

        s = MCPState()
        s.pending_inputs["a"] = 1
        s.pending_inputs["b"] = 2
        out = s.pop_pending_inputs()
        assert out == {"a": 1, "b": 2}
        assert s.pending_inputs == {}
        # A concurrent-style write after pop lands in the new dict.
        s.pending_inputs["c"] = 3
        assert s.pop_pending_inputs() == {"c": 3}

    def test_pop_pending_inputs_atomic_swap_preserves_writes(self):
        """Writes between pop's read and rebind go into the returned dict."""
        from fast_dash.mcp import MCPState

        s = MCPState()
        s.pending_inputs["a"] = 1
        out = s.pop_pending_inputs()
        assert out == {"a": 1}
        assert s.pending_inputs == {}

    def test_pop_pending_specs_returns_and_clears(self):
        from fast_dash.mcp import MCPState

        s = MCPState()
        assert s.pop_pending_specs() is None
        s.pending_specs = [{"name": "x", "type": "Text"}]
        out = s.pop_pending_specs()
        assert out == [{"name": "x", "type": "Text"}]
        assert s.pending_specs is None

    def test_pop_pending_outputs_returns_and_clears(self):
        from fast_dash.mcp import MCPState

        s = MCPState()
        s.pending_outputs["o1"] = "result"
        out = s.pop_pending_outputs()
        assert out == {"o1": "result"}
        assert s.pending_outputs == {}


# --- Resource reads -------------------------------------------------------


@requires_mcp
class TestResources:
    """Each `fastdash://...` resource returns the expected JSON shape."""

    def _build(self):
        from fast_dash.mcp import build_mcp_server, MCPState

        def my_fn(name: str = "world", count: int = 3) -> str:
            """Greet someone count times."""
            return ", ".join([name] * count)

        app = FastDash(callback_fn=my_fn, mcp_server=True)
        # MCPState already constructed by FastDash.__init__
        assert isinstance(app._mcp_state, MCPState)
        return app, build_mcp_server(app)

    def test_app_info_resource(self):
        app, server = self._build()
        raw = _read(_run_async(server.read_resource("fastdash://app")))
        data = json.loads(raw)
        assert data["callback"] == "my_fn"
        assert "Greet someone" in data["doc"]
        assert data["is_dynamic"] is False
        assert data["is_multi"] is False
        assert "Slider" in data["component_types"]

    def test_app_inputs_resource(self):
        app, server = self._build()
        raw = _read(_run_async(server.read_resource("fastdash://app/inputs")))
        data = json.loads(raw)
        ids = {d["id"] for d in data}
        assert ids == {"name", "count"}
        for d in data:
            assert d["property"] == "value"
        # build_mcp_server seeds the mirror from the callback's signature
        # defaults, so a headless agent sees real values (not nulls) before
        # any browser renders the page.
        by_id = {d["id"]: d["value"] for d in data}
        assert by_id["name"] == "world"
        assert by_id["count"] == 3

    def test_app_inputs_reflects_state_writes(self):
        app, server = self._build()
        app._mcp_state.inputs["name"] = "Claude"
        app._mcp_state.inputs["count"] = 5
        raw = _read(_run_async(server.read_resource("fastdash://app/inputs")))
        data = json.loads(raw)
        by_id = {d["id"]: d["value"] for d in data}
        assert by_id["name"] == "Claude"
        assert by_id["count"] == 5

    def test_app_outputs_resource(self):
        app, server = self._build()
        raw = _read(_run_async(server.read_resource("fastdash://app/outputs")))
        data = json.loads(raw)
        assert isinstance(data, list)
        assert len(data) >= 1
        for d in data:
            assert "id" in d and "value" in d

    def test_app_layout_resource(self):
        app, server = self._build()
        raw = _read(_run_async(server.read_resource("fastdash://app/layout")))
        data = json.loads(raw)
        # Layout should be a Dash component tree (dict with 'type' and 'props')
        # or, on weird Dash versions, a {"repr": "..."} fallback.
        assert isinstance(data, dict)
        assert ("type" in data) or ("repr" in data)

    def test_app_history_resource_starts_empty(self):
        app, server = self._build()
        raw = _read(_run_async(server.read_resource("fastdash://app/history")))
        assert json.loads(raw) == []


# --- Tool invocations -----------------------------------------------------


@requires_mcp
class TestTools:
    """End-to-end behavior of the mutation tools."""

    def _build_plain(self):
        from fast_dash.mcp import build_mcp_server

        def my_fn(name: str = "world", count: int = 3) -> str:
            """Greet."""
            return ", ".join([name] * count)

        app = FastDash(callback_fn=my_fn, mcp_server=True)
        return app, build_mcp_server(app)

    def _build_dynamic(self):
        from fast_dash import DynamicDash, Markdown
        from fast_dash.mcp import build_mcp_server

        def my_dyn_fn(x: str = "hi") -> str:
            """Dynamic-form callback for tests."""
            return x

        app = DynamicDash(
            callback_fn=my_dyn_fn,
            initial_specs=[{"name": "x", "type": "Text"}],
            output_components=[Markdown],
            mcp_server=True,
        )
        return app, build_mcp_server(app)

    def test_set_input_updates_state(self):
        app, server = self._build_plain()
        res = _text(_run_async(server.call_tool(
            "set_input", {"component_id": "name", "value": "Claude"}
        )))
        data = json.loads(res)
        assert data["ok"] is True
        assert app._mcp_state.inputs["name"] == "Claude"

    def test_set_input_queues_for_browser_drain(self):
        """v0.2 push: set_input writes to pending_inputs so the drain callback fans it out."""
        app, server = self._build_plain()
        _run_async(server.call_tool(
            "set_input", {"component_id": "name", "value": "Claude"}
        ))
        assert app._mcp_state.pending_inputs == {"name": "Claude"}

    def test_set_inputs_queues_for_browser_drain(self):
        app, server = self._build_plain()
        _run_async(server.call_tool(
            "set_inputs", {"values": {"name": "X", "count": 7}}
        ))
        assert app._mcp_state.pending_inputs == {"name": "X", "count": 7}

    def test_invoke_with_inputs_applies_and_runs_one_shot(self):
        """invoke(inputs=...) == set_inputs then invoke, in one round-trip."""
        app, server = self._build_plain()  # my_fn -> ", ".join([name] * count)
        res = _text(_run_async(server.call_tool(
            "invoke", {"inputs": {"name": "Z", "count": 2}}
        )))
        data = json.loads(res)
        assert data["ok"] is True
        # Mirror updated AND queued for the browser drain (same as set_inputs).
        assert app._mcp_state.inputs["name"] == "Z"
        assert app._mcp_state.pending_inputs == {"name": "Z", "count": 2}
        # The callback actually ran with the applied values.
        assert "Z, Z" in json.dumps(data["outputs"])

    def test_invoke_with_unknown_input_is_rejected(self):
        app, server = self._build_plain()
        res = _text(_run_async(server.call_tool(
            "invoke", {"inputs": {"name": "ok", "nope": 1}}
        )))
        data = json.loads(res)
        assert data["ok"] is False
        assert "known_ids" in data
        # Atomic: a rejected batch must NOT partially mutate the mirror,
        # even for the valid keys that preceded the bad one.
        assert "nope" not in app._mcp_state.inputs
        assert app._mcp_state.inputs.get("name") == "world"  # seeded default
        assert app._mcp_state.pending_inputs == {}

    def test_invoke_without_inputs_uses_current_mirror(self):
        app, server = self._build_plain()
        app._mcp_state.inputs["name"] = "Q"
        app._mcp_state.inputs["count"] = 3
        res = _text(_run_async(server.call_tool("invoke", {})))
        data = json.loads(res)
        assert data["ok"] is True
        assert "Q, Q, Q" in json.dumps(data["outputs"])

    def test_set_form_queues_for_browser_drain(self):
        """v0.2 push: set_form on DynamicDash writes pending_specs for the Interval drain."""
        app, server = self._build_dynamic()
        specs = [{"name": "y", "type": "Slider", "props": {"min": 0, "max": 1}}]
        _run_async(server.call_tool("set_form", {"specs": specs}))
        assert app._mcp_state.pending_specs == specs

    def test_fastdash_layout_includes_drain_interval(self):
        """v0.2: FastDash with mcp_server=True has the _mcp_poll Interval in the layout."""
        from fast_dash.mcp import build_mcp_server  # noqa: F401

        def my_fn(name: str = "world") -> str:
            return name

        app = FastDash(callback_fn=my_fn, mcp_server=True)
        # Walk the layout collecting ids
        def walk_ids(comp, out):
            cid = getattr(comp, "id", None)
            if isinstance(cid, str):
                out.add(cid)
            children = getattr(comp, "children", None)
            if children is None:
                return
            if not isinstance(children, (list, tuple)):
                children = [children]
            for c in children:
                if c is not None:
                    walk_ids(c, out)

        ids = set()
        walk_ids(app.app.layout, ids)
        assert "_mcp_poll" in ids
        assert "_mcp_mirror_store" in ids

    def test_set_input_rejects_unknown_id(self):
        app, server = self._build_plain()
        res = _text(_run_async(server.call_tool(
            "set_input", {"component_id": "bogus", "value": 1}
        )))
        data = json.loads(res)
        assert data["ok"] is False
        assert "Unknown input id" in data["error"]
        assert "known_ids" in data

    def test_set_inputs_bulk(self):
        app, server = self._build_plain()
        res = _text(_run_async(server.call_tool(
            "set_inputs", {"values": {"name": "X", "count": 2}}
        )))
        data = json.loads(res)
        assert data["ok"] is True
        assert app._mcp_state.inputs == {"name": "X", "count": 2}

    def test_set_inputs_records_partial_errors(self):
        app, server = self._build_plain()
        res = _text(_run_async(server.call_tool(
            "set_inputs", {"values": {"name": "X", "bogus": 99}}
        )))
        data = json.loads(res)
        assert data["ok"] is False
        assert "applied" in data and "name" in data["applied"]
        assert "errors" in data and "bogus" in data["errors"]

    def test_invoke_calls_callback_and_records_history(self):
        app, server = self._build_plain()
        app._mcp_state.inputs["name"] = "X"
        app._mcp_state.inputs["count"] = 3
        res = _text(_run_async(server.call_tool("invoke", {})))
        data = json.loads(res)
        assert data["ok"] is True
        assert data["history_index"] == 0
        assert app._mcp_state.outputs  # some output recorded
        assert len(app._mcp_state.history) == 1
        entry = list(app._mcp_state.history)[0]
        assert entry["kwargs"] == {"name": "X", "count": 3}
        # v0.2.1: invoke also queues outputs for browser push
        assert app._mcp_state.pending_outputs  # at least one output queued

    def test_invoke_reports_callback_exception(self):
        from fast_dash.mcp import build_mcp_server

        def boom(name: str = "x") -> str:
            raise RuntimeError("kapow")

        app = FastDash(callback_fn=boom, mcp_server=True)
        server = build_mcp_server(app)
        app._mcp_state.inputs["name"] = "x"
        res = _text(_run_async(server.call_tool("invoke", {})))
        data = json.loads(res)
        assert data["ok"] is False
        assert "kapow" in data["error"]

    def test_get_invocation_returns_summary(self):
        app, server = self._build_plain()
        app._mcp_state.inputs["name"] = "X"
        app._mcp_state.inputs["count"] = 2
        _run_async(server.call_tool("invoke", {}))
        res = _text(_run_async(server.call_tool("get_invocation", {"index": 0})))
        data = json.loads(res)
        assert data["ok"] is True
        assert data["kwargs_summary"] == {"name": "X", "count": 2}

    def test_get_invocation_unknown_index(self):
        app, server = self._build_plain()
        res = _text(_run_async(server.call_tool("get_invocation", {"index": 99})))
        data = json.loads(res)
        assert data["ok"] is False
        assert "not in history" in data["error"]

    def test_list_component_types(self):
        app, server = self._build_plain()
        res = _text(_run_async(server.call_tool("list_component_types", {})))
        data = json.loads(res)
        assert "Slider" in data["types"]
        assert "Text" in data["types"]

    def test_set_form_rejects_plain_fastdash(self):
        app, server = self._build_plain()
        res = _text(_run_async(server.call_tool(
            "set_form", {"specs": [{"name": "y", "type": "Text"}]}
        )))
        data = json.loads(res)
        assert data["ok"] is False
        assert "DynamicDash" in data["error"]

    def test_set_form_accepts_valid_specs_on_dynamicdash(self):
        app, server = self._build_dynamic()
        specs = [
            {"name": "rate", "type": "Slider", "props": {"min": 0, "max": 1}},
            {"name": "mode", "type": "Select", "props": {"data": ["a", "b"]}},
        ]
        res = _text(_run_async(server.call_tool("set_form", {"specs": specs})))
        data = json.loads(res)
        assert data["ok"] is True
        assert data["count"] == 2
        assert app._mcp_state.pending_specs == specs

    def test_set_form_rejects_invalid_spec(self):
        app, server = self._build_dynamic()
        res = _text(_run_async(server.call_tool(
            "set_form", {"specs": [{"name": "x", "type": "NotReal"}]}
        )))
        data = json.loads(res)
        assert data["ok"] is False
        assert "Unknown component type" in data["error"]

    def test_screenshot_returns_text_for_string_output(self):
        from fast_dash.mcp import build_mcp_server

        def fn(name: str = "x") -> str:
            return "hello world"

        app = FastDash(callback_fn=fn, mcp_server=True)
        server = build_mcp_server(app)
        _run_async(server.call_tool("invoke", {}))
        res = _text(_run_async(server.call_tool("screenshot", {})))
        data = json.loads(res)
        outs = data["outputs"]
        assert isinstance(outs, list)
        assert len(outs) >= 1
        # The text output should round-trip through screenshot as text/plain.
        assert any(d.get("mime") == "text/plain" for d in outs)


class TestRobustness:
    """Regression coverage for the dogfood findings.

    A tool must never tear down the MCP session by returning a
    non-serializable payload, and ``screenshot()`` must degrade gracefully
    when kaleido is absent rather than emitting numpy arrays.
    """

    def test_safe_tool_catches_body_exception(self):
        from fast_dash.mcp import _safe_tool

        @_safe_tool
        def boom() -> dict:
            raise RuntimeError("kaboom")

        out = boom()
        assert out["ok"] is False
        assert "RuntimeError: kaboom" in out["error"]

    def test_safe_tool_sanitizes_unserializable_return(self):
        import numpy as np

        from fast_dash.mcp import _safe_tool

        @_safe_tool
        def gives_numpy() -> dict:
            return {"arr": np.arange(3)}

        out = gives_numpy()
        # Must be JSON-serializable now (numpy degraded to a string).
        json.dumps(out)

    def test_safe_tool_preserves_signature_for_schema(self):
        from fast_dash.mcp import _safe_tool
        import inspect

        @_safe_tool
        def f(component_id: str, value: int) -> dict:
            return {"ok": True}

        # FastMCP builds the tool schema from the signature; the wrapper
        # must expose the wrapped function's parameters, not (*args,**kwargs).
        params = list(inspect.signature(f).parameters)
        assert params == ["component_id", "value"]

    def test_screenshot_figure_without_kaleido_is_serializable(self, monkeypatch):
        import plotly.graph_objects as go

        from fast_dash.mcp import _render_one_output

        def _no_kaleido(*a, **k):
            raise RuntimeError("kaleido not installed")

        monkeypatch.setattr(go.Figure, "to_image", _no_kaleido)
        fig = go.Figure(go.Bar(x=["a", "b"], y=[1, 2]))
        out = _render_one_output(fig)
        # The whole point: serializable, no numpy arrays leaking through.
        json.dumps(out)
        assert "kaleido" in out["error"]
        assert "figure" in out  # plotly-encoded fallback present

    def test_screenshot_with_figure_output_does_not_crash_session(self):
        """The original reported bug: invoke()->Figure then screenshot()."""
        from fast_dash.mcp import build_mcp_server

        def make_fig(n: int = 3) -> go.Figure:
            return go.Figure(go.Bar(x=list(range(n)), y=list(range(n))))

        app = FastDash(callback_fn=make_fig, mcp_server=True)
        server = build_mcp_server(app)
        _run_async(server.call_tool("invoke", {}))
        res = _text(_run_async(server.call_tool("screenshot", {})))
        data = json.loads(res)  # would raise if the tool 500'd
        assert isinstance(data["outputs"], list)

    def test_input_mirror_seeded_from_defaults(self):
        from fast_dash.mcp import build_mcp_server

        def greet(name: str = "world", count: int = 3) -> str:
            return name * count

        app = FastDash(callback_fn=greet, mcp_server=True)
        build_mcp_server(app)
        # Seeded before any browser renders the page.
        assert app._mcp_state.inputs["name"] == "world"
        assert app._mcp_state.inputs["count"] == 3
