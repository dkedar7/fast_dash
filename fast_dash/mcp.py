"""Model Context Protocol (MCP) server output for Fast Dash apps.

Lets a Fast Dash app simultaneously serve as a web app *and* an MCP
tool callable by AI agents (Claude, Cursor, Cline, etc.). The same
type hints that drive the UI also drive the MCP tool's input schema.

Usage::

    from fast_dash import fastdash

    @fastdash(mcp_server=True)
    def search_db(query: str, limit: int = 10) -> list[str]:
        '''Search the user database.'''
        ...

The web app runs on the usual port (8080 by default). The MCP server
runs on a separate port (8001 by default) at the path ``/mcp``. An
agent can connect with the streamable-http transport::

    {"command": "mcp", "args": ["--http", "http://localhost:8001/mcp"]}

Implementation notes:

- We use the official ``mcp`` SDK (``mcp.server.fastmcp.FastMCP``).
  Schema is derived automatically from type hints + docstring via
  pydantic, so a well-typed Fast Dash function needs no extra work.
- The MCP server is mounted as a Starlette ASGI app served by uvicorn
  in a daemon thread. Flask (Dash) and Starlette use different
  protocols (WSGI vs ASGI), so a single port would require an extra
  bridging dependency. Two ports keeps the surface clean.
- ``mcp`` is an optional dependency. ``import fast_dash.mcp`` succeeds
  on plain installs; the helpful import error fires only when a user
  passes ``mcp_server=True`` without the package installed.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

# Holder for an active MCP thread so tests can introspect / shut down.
_active_mcp_thread: threading.Thread | None = None


def _ensure_mcp_deps() -> tuple[Any, Any]:
    """Import mcp and uvicorn lazily; raise a clear error if missing."""
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]
    except ImportError as e:
        raise ImportError(
            "MCP support requires the 'mcp' package. Install it with:\n"
            "    pip install 'mcp>=1.0'"
        ) from e
    try:
        import uvicorn  # type: ignore[import-not-found]
    except ImportError as e:
        raise ImportError(
            "MCP HTTP transport requires 'uvicorn'. Install it with:\n"
            "    pip install uvicorn"
        ) from e
    return FastMCP, uvicorn


def build_mcp_server(
    callback_fn: Callable[..., Any],
    *,
    title: str | None = None,
):
    """Build a FastMCP server that exposes ``callback_fn`` as a tool.

    The function's signature, type hints, and docstring drive the tool
    schema directly — no extra annotations required. Returns the
    ``FastMCP`` instance configured for streamable-HTTP transport.
    """
    FastMCP, _ = _ensure_mcp_deps()
    server = FastMCP(
        title or callback_fn.__name__,
        stateless_http=True,
        json_response=True,
    )
    # ``@server.tool()`` reads the signature on registration; passing
    # the function object directly preserves annotations and __doc__.
    server.tool()(callback_fn)
    return server


def serve_mcp_in_thread(
    callback_fn: Callable[..., Any],
    *,
    host: str = "127.0.0.1",
    port: int = 8001,
    title: str | None = None,
) -> threading.Thread:
    """Start the MCP server on a background daemon thread.

    Returns the thread object. The Dash/Flask main loop continues on
    the parent thread; the MCP server lives only for the lifetime of
    the parent process.
    """
    server = build_mcp_server(callback_fn, title=title)
    _, uvicorn = _ensure_mcp_deps()

    asgi_app = server.streamable_http_app()
    config = uvicorn.Config(
        asgi_app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    uv_server = uvicorn.Server(config)

    def _run():
        # uvicorn.Server.run() spins up its own asyncio loop on the
        # current thread, which is what we want for a side-thread server.
        uv_server.run()

    thread = threading.Thread(target=_run, daemon=True, name="fastdash-mcp")
    thread.start()

    global _active_mcp_thread
    _active_mcp_thread = thread
    return thread
