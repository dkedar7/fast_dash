"""Tests for MCP server output (v0.2.17).

These tests exercise the wiring without actually binding a port — the
``build_mcp_server`` helper produces a FastMCP instance whose schema we
can introspect, and the integration test for ``serve_mcp_in_thread``
binds an ephemeral port only when ``mcp`` is installed.
"""

from __future__ import annotations

import importlib.util
import socket
import time
import warnings

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
