"""Model Context Protocol (MCP) server for Fast Dash apps.

Lets a Fast Dash app simultaneously serve as a web app *and* an MCP
endpoint that AI agents (Claude Code, Cursor, Cline, CopilotKit) can
inspect and drive. The same type hints that drive the UI also drive the
MCP schemas.

Usage::

    from fast_dash import fastdash

    @fastdash(mcp_server=True)
    def search_db(query: str, limit: int = 10) -> list[str]:
        '''Search the user database.'''
        ...

``mcp_server=True`` is the one obvious way to expose an app: it works the
same on ``FastDash``, ``@fastdash``, and ``DynamicDash``, and their
``run()`` starts the MCP server for you. The lower-level
``serve_mcp_in_thread`` is only needed to attach MCP to a *bare callable*
(no app instance) or to manage the server thread yourself.

The web app runs on the usual port (8080 by default). The MCP server
runs on a separate port (8001 by default) at the path ``/mcp``. Agents
connect via streamable-HTTP::

    {"servers": {"my-app": {"url": "http://localhost:8001/mcp"}}}

What an agent sees
-------------------

* **Tool** named after ``callback_fn`` — schema derived from type hints
  + docstring. Calling it executes the function directly (no UI).
* **Tools** for state manipulation:
    - ``set_input(component_id, value)``
    - ``set_inputs({...})``
    - ``invoke()`` — runs callback with current input mirror
    - ``set_form(specs)`` — DynamicDash only
    - ``get_invocation(index)`` — full kwargs+result from history
    - ``screenshot()`` — server-side render of current outputs
    - ``list_component_types()``
* **Resources** (read-only state, polled):
    - ``fastdash://app`` — title, callback signature, mode
    - ``fastdash://app/inputs`` — current input panel state
    - ``fastdash://app/outputs`` — current output state
    - ``fastdash://app/layout`` — full component tree
    - ``fastdash://app/history`` — last 20 invocation summaries

Implementation notes
--------------------

* Uses the official ``mcp`` SDK (``mcp.server.fastmcp.FastMCP``).
* The MCP server is mounted as a Starlette ASGI app served by uvicorn
  in a daemon thread alongside Flask (Dash). Two ports keep WSGI/ASGI
  cleanly separated.
* ``mcp`` and ``uvicorn`` are optional deps (``[mcp]`` extra). Importing
  this module succeeds without them; the helpful error fires only when
  the server is actually constructed.

Server → browser push (v0.2)
----------------------------

Agent mutations (``set_input`` / ``set_inputs`` / ``set_form``) write
into per-state pending queues. A ``dcc.Interval(500ms)``-driven drain
callback in the Dash app pops them atomically and applies them live —
no reload needed. Browser update latency is bounded by the Interval
period (~500ms).

v0.2 limitations
----------------

* **Per-field ``set_input`` on a DynamicDash form is server-only.**
  Pattern-matching outputs from a static callback can't address
  runtime-created inputs by name. ``set_form`` (which re-renders the
  whole form) is the supported live mutation for DynamicDash. Full
  per-field push is a v0.3 piece, likely on top of Dash 4.2 WebSocket
  callbacks + relaxed ``MATCH`` semantics.
* Race with human typing: if a human is editing the same input the
  agent writes to, the drain will overwrite their keystrokes within
  500ms. ``mcp_host`` defaults to ``127.0.0.1`` so this only matters
  when a local agent and local user collide.
* Multi-function and steps modes skip MCP entirely (inherited from the
  initial ``feature/mcp`` design).
* No auth on the MCP port; bind ``127.0.0.1`` only. A warning is logged
  if ``mcp_host`` is overridden.
"""

from __future__ import annotations

import base64
import collections
import datetime
import functools
import inspect
import io
import json
import threading
import time
from typing import Any, Callable

# Holder for an active MCP thread so tests can introspect / shut down.
_active_mcp_thread: threading.Thread | None = None


class MCPState:
    """Server-side mirror of a fast_dash app's input/output state.

    Shared between the Dash main thread (writes from mirror callbacks
    + drain callbacks) and the MCP server thread (reads from resource
    handlers, writes from mutation tools). CPython GIL handles single-
    key writes; ``deque(maxlen=N)`` is thread-safe for ``append``.
    Resource handlers snapshot dicts before iterating.

    For server→browser push (v0.2), MCP tools also write to
    ``pending_inputs`` / ``pending_specs``. A Dash ``dcc.Interval``-
    driven drain callback pops these atomically and applies them to
    the live UI.
    """

    def __init__(self, history_size: int = 20):
        self.inputs: dict[str, Any] = {}
        self.outputs: dict[str, Any] = {}
        self.history: collections.deque = collections.deque(maxlen=history_size)
        # Parallel to `history`, holds the unsummarized payload for
        # `get_invocation(index)` lookups.
        self.full_history: collections.OrderedDict = collections.OrderedDict()
        self._history_size = history_size
        # --- Push queues (drained by the Dash drain callback) ---------------
        # set_input / set_inputs write here; FastDash drain fans out to
        # each input component.
        self.pending_inputs: dict[str, Any] = {}
        # set_form writes here; DynamicDash drain re-renders the form.
        self.pending_specs: list[dict] | None = None
        # invoke() writes here; FastDash drain fans out to each output
        # component so the browser reflects the agent-triggered callback
        # without anyone touching the UI.
        self.pending_outputs: dict[str, Any] = {}

    def append_history(self, entry_summary: dict, entry_full: dict) -> int:
        self.history.append(entry_summary)
        idx = (
            next(reversed(self.full_history), -1) + 1
            if self.full_history
            else 0
        )
        self.full_history[idx] = entry_full
        while len(self.full_history) > self._history_size:
            self.full_history.popitem(last=False)
        return idx

    def pop_pending_inputs(self) -> dict[str, Any]:
        """Atomically swap and return the pending-inputs dict.

        Thread safety: rebinding ``self.pending_inputs`` to a fresh
        dict is atomic under CPython, so any concurrent
        ``state.pending_inputs[id] = v`` write either lands in the
        returned old dict (eventually delivered) or in the new empty
        dict (delivered on the next drain). No writes are dropped.
        """
        out, self.pending_inputs = self.pending_inputs, {}
        return out

    def pop_pending_specs(self) -> list[dict] | None:
        """Atomically swap and return the pending-specs list."""
        out, self.pending_specs = self.pending_specs, None
        return out

    def pop_pending_outputs(self) -> dict[str, Any]:
        """Atomically swap and return the pending-outputs dict."""
        out, self.pending_outputs = self.pending_outputs, {}
        return out


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


def _is_fastdash_instance(obj) -> bool:
    """Duck-type FastDash without importing it (avoids circular import)."""
    return hasattr(obj, "callback_fn") and hasattr(obj, "app") and (
        hasattr(obj, "inputs_with_ids") or hasattr(obj, "_outputs_with_ids")
    )


def _is_dynamic(fd) -> bool:
    try:
        from fast_dash.dynamic import DynamicDash
        return isinstance(fd, DynamicDash)
    except Exception:
        return False


def _component_types() -> list[str]:
    try:
        from fast_dash.dynamic import COMPONENT_REGISTRY
        return sorted(COMPONENT_REGISTRY.keys())
    except Exception:
        return []


def _stringify_id(cid) -> str:
    if isinstance(cid, str):
        return cid
    return json.dumps(cid, sort_keys=True)


def _enumerate_inputs(fd) -> list[dict]:
    """Return a normalized list of input descriptors for whichever app mode."""
    descriptors = []
    if hasattr(fd, "inputs_with_ids") and fd.inputs_with_ids:
        for c in fd.inputs_with_ids:
            descriptors.append(
                {
                    "id": _stringify_id(c.id),
                    "tag": getattr(c, "tag", None),
                    "label": getattr(c, "label_", None),
                    "property": c.component_property,
                }
            )
    return descriptors


def _enumerate_outputs(fd) -> list[dict]:
    descriptors = []
    candidates = (
        getattr(fd, "outputs_with_ids", None)
        or getattr(fd, "_outputs_with_ids", None)
        or []
    )
    for c in candidates:
        descriptors.append(
            {
                "id": _stringify_id(c.id),
                "tag": getattr(c, "tag", None),
                "property": c.component_property,
            }
        )
    return descriptors


def _param_name_from_id(component_id: str) -> str:
    """Strip the `input_` prefix FastDash adds, to convert id → kwarg name."""
    if component_id.startswith("input_"):
        return component_id[len("input_"):]
    return component_id


def _json_safe(obj):
    """Coerce a value into a JSON-serializable structure.

    Defends the MCP transport. A tool that returns numpy arrays, a Plotly
    figure, or any other exotic object would otherwise raise *during the
    SDK's response serialization* — after the tool body has returned, so
    an in-body ``try/except`` can't catch it — and that unhandled error
    tears down the whole client session. Round-tripping through ``json``
    with ``default=str`` degrades unknown objects to strings instead.
    """
    return json.loads(json.dumps(obj, default=str))


def _safe_tool(fn):
    """Wrap an MCP tool so it can never 500 the session.

    Catches exceptions in the tool body *and* sanitizes the return value
    so a non-serializable payload degrades gracefully instead of killing
    the transport. ``functools.wraps`` preserves the signature/annotations
    FastMCP introspects to build the tool schema.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            result = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — report, never propagate
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        try:
            return _json_safe(result)
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"unserializable tool result: {type(e).__name__}: {e}",
            }

    return wrapper


def _seed_input_mirror(fd) -> None:
    """Pre-populate the input mirror from component / signature defaults.

    The browser mirror callback only fires once a client renders the page.
    An agent that connects headless (the whole point of MCP) would
    otherwise see ``null`` input values via ``fastdash://app/inputs`` and
    ``invoke()`` would silently fall back to the callback's defaults with
    no visible record of what it ran. Seeding makes the mirror reflect the
    true starting values immediately.

    DynamicDash has no static inputs (the form is created at runtime by
    ``set_form``), so this is a no-op there.
    """
    state: MCPState = fd._mcp_state
    components = getattr(fd, "inputs_with_ids", None) or []

    # 1) Each input component's current prop value (covers UI defaults).
    for c in components:
        cid = _stringify_id(c.id)
        if cid in state.inputs:
            continue
        prop = getattr(c, "component_property", "value")
        val = getattr(c, prop, None)
        if val is not None:
            state.inputs[cid] = val

    # 2) Fall back to the callback signature defaults for anything still
    #    unseeded (FastDash uses the parameter name as the component id).
    try:
        ids = {_stringify_id(c.id) for c in components}
        sig = inspect.signature(fd.callback_fn)
        for name, p in sig.parameters.items():
            if p.default is inspect.Parameter.empty:
                continue
            if name in ids and name not in state.inputs:
                state.inputs[name] = p.default
    except (TypeError, ValueError):
        pass


def build_mcp_server(app_or_callable, *, title: str | None = None):
    """Build a FastMCP server for either a FastDash instance or a callable.

    * **FastDash instance**: registers callback as a tool *and* the full
      app surface (resources + manipulation tools), closing over
      ``fd._mcp_state``.
    * **Plain callable**: registers just the callable as a single tool
      (legacy behavior from the original ``feature/mcp`` commit).
    """
    FastMCP, _ = _ensure_mcp_deps()

    if _is_fastdash_instance(app_or_callable):
        fd = app_or_callable
        callback_fn = fd.callback_fn
        server_title = title or getattr(fd, "title", None) or callback_fn.__name__
    else:
        fd = None
        callback_fn = app_or_callable
        server_title = title or callback_fn.__name__

    server = FastMCP(
        server_title,
        stateless_http=True,
        json_response=True,
    )
    # Always register the callback itself — agents can call it directly
    # without going through the UI / mirror.
    if callback_fn is not None:
        server.tool()(callback_fn)

    if fd is None:
        return server

    # Lazy-init MCPState on the FastDash if it wasn't constructed by
    # FastDash.__init__ (defensive — keeps build_mcp_server callable
    # standalone in tests).
    if not hasattr(fd, "_mcp_state") or fd._mcp_state is None:
        fd._mcp_state = MCPState()

    _seed_input_mirror(fd)
    _register_resources(server, fd)
    _register_tools(server, fd)
    return server


def _register_resources(server, fd):
    """Register the read-only `fastdash://...` resources."""
    from fast_dash.utils import _jsonify_for_mcp

    state: MCPState = fd._mcp_state

    @server.resource("fastdash://app")
    def app_info() -> str:
        return json.dumps(
            {
                "title": getattr(fd, "title", None) or "",
                "callback": getattr(fd.callback_fn, "__name__", "callback"),
                "doc": (getattr(fd.callback_fn, "__doc__", "") or "").strip(),
                "is_dynamic": _is_dynamic(fd),
                "is_multi": bool(getattr(fd, "is_multi", False)),
                "is_steps": bool(getattr(fd, "is_steps", False)),
                "component_types": _component_types(),
            },
            indent=2,
            default=str,
        )

    @server.resource("fastdash://app/inputs")
    def app_inputs() -> str:
        descriptors = _enumerate_inputs(fd)
        snapshot = dict(state.inputs)
        for d in descriptors:
            d["value"] = _jsonify_for_mcp(snapshot.get(d["id"]))
        return json.dumps(descriptors, indent=2, default=str)

    @server.resource("fastdash://app/outputs")
    def app_outputs() -> str:
        descriptors = _enumerate_outputs(fd)
        snapshot = dict(state.outputs)
        for d in descriptors:
            d["value"] = _jsonify_for_mcp(snapshot.get(d["id"]))
        return json.dumps(descriptors, indent=2, default=str)

    @server.resource("fastdash://app/layout")
    def app_layout() -> str:
        try:
            layout = fd.app.layout
            if hasattr(layout, "to_plotly_json"):
                return json.dumps(layout.to_plotly_json(), indent=2, default=str)
            return json.dumps({"repr": str(layout)})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @server.resource("fastdash://app/history")
    def app_history() -> str:
        return json.dumps(list(state.history), indent=2, default=str)


def _register_tools(server, fd):
    """Register the mutation/action tools."""
    from fast_dash.utils import _jsonify_for_mcp, _summarize_for_history

    state: MCPState = fd._mcp_state

    @server.tool()
    @_safe_tool
    def set_input(component_id: str, value: Any) -> dict:
        """Update one input's value, server-side AND live in the browser.

        Browser update lands within ~500ms (Dash ``Interval``-driven
        drain). For DynamicDash apps the per-field push is not wired in
        v0.2; the value still updates the server mirror but the browser
        won't reflect it until the next ``set_form`` re-renders the form.
        """
        ids = {d["id"] for d in _enumerate_inputs(fd)}
        if ids and component_id not in ids:
            return {
                "ok": False,
                "error": f"Unknown input id {component_id!r}",
                "known_ids": sorted(ids),
            }
        state.inputs[component_id] = value
        state.pending_inputs[component_id] = value
        return {"ok": True, "id": component_id, "value": _jsonify_for_mcp(value)}

    @server.tool()
    @_safe_tool
    def set_inputs(values: dict) -> dict:
        """Bulk-update multiple input values. Same browser-push contract as set_input."""
        ids = {d["id"] for d in _enumerate_inputs(fd)}
        applied, errors = {}, {}
        for k, v in (values or {}).items():
            if ids and k not in ids:
                errors[k] = "unknown id"
                continue
            state.inputs[k] = v
            state.pending_inputs[k] = v
            applied[k] = _jsonify_for_mcp(v)
        return {"ok": not errors, "applied": applied, "errors": errors}

    @server.tool()
    @_safe_tool
    def invoke(inputs: dict | None = None) -> dict:
        """Run the app's callback with the current input mirror.

        Pass ``inputs`` to set values and run in a single call — equivalent
        to ``set_inputs(inputs)`` immediately followed by ``invoke()``, but
        one round-trip (and the browser reflects the values too). Omit it to
        run with whatever the mirror already holds. Returns a summary of the
        outputs and writes them into the server-side outputs mirror (visible
        via `fastdash://app/outputs`).
        """
        if getattr(fd, "is_multi", False) or getattr(fd, "is_steps", False):
            return {
                "ok": False,
                "error": "invoke not supported in multi-function/steps mode",
            }

        # Optional one-shot input application — same validate-and-push
        # contract as set_inputs, so the mirror AND the live browser update.
        # Validate ALL keys before applying ANY, so a bad key can't leave the
        # mirror partially mutated (which would taint a later invoke()).
        if inputs:
            ids = {d["id"] for d in _enumerate_inputs(fd)}
            if ids:
                unknown = sorted(k for k in inputs if k not in ids)
                if unknown:
                    return {
                        "ok": False,
                        "error": f"unknown input id(s): {unknown}",
                        "known_ids": sorted(ids),
                    }
            for k, v in inputs.items():
                state.inputs[k] = v
                state.pending_inputs[k] = v

        # Build kwargs: map component id (e.g. "input_x") → parameter name "x"
        kwargs = {}
        snapshot = dict(state.inputs)
        descriptors = _enumerate_inputs(fd)
        if descriptors:
            for d in descriptors:
                cid = d["id"]
                param = _param_name_from_id(cid)
                if cid in snapshot:
                    kwargs[param] = snapshot[cid]
                elif param in snapshot:
                    kwargs[param] = snapshot[param]
        else:
            # No static input descriptors (e.g. DynamicDash) — the mirror
            # already keys by parameter name, so use it directly.
            kwargs = dict(snapshot)

        t0 = time.time()
        try:
            result = fd.callback_fn(**kwargs)
        except Exception as e:
            return {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "kwargs_summary": {
                    k: _summarize_for_history(v) for k, v in kwargs.items()
                },
            }
        dt_ms = round((time.time() - t0) * 1000, 1)

        if not isinstance(result, (list, tuple)):
            result_list = [result]
        else:
            result_list = list(result)
        out_summary = {}
        outs = _enumerate_outputs(fd)
        for d, val in zip(outs, result_list):
            state.outputs[d["id"]] = val
            state.pending_outputs[d["id"]] = val
            out_summary[d["id"]] = _summarize_for_history(val)

        entry_summary = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "duration_ms": dt_ms,
            "kwargs": {k: _summarize_for_history(v) for k, v in kwargs.items()},
            "outputs": out_summary,
        }
        entry_full = {
            **entry_summary,
            "_full_kwargs": kwargs,
            "_full_result": result,
        }
        idx = state.append_history(entry_summary, entry_full)
        return {
            "ok": True,
            "duration_ms": dt_ms,
            "outputs": out_summary,
            "history_index": idx,
        }

    @server.tool()
    @_safe_tool
    def set_form(specs: list) -> dict:
        """Replace the form on a DynamicDash app with a new spec list.

        The DynamicDash drain callback picks up the specs within ~500ms
        and re-renders the form live in the browser. Plain FastDash apps
        reject this tool.
        """
        from fast_dash.dynamic import _spec_to_component

        if not _is_dynamic(fd):
            return {
                "ok": False,
                "error": "set_form requires a DynamicDash app",
            }
        if not isinstance(specs, list):
            return {"ok": False, "error": "specs must be a list of dicts"}
        for spec in specs:
            try:
                _spec_to_component(spec)
            except (TypeError, ValueError) as e:
                return {"ok": False, "error": f"invalid spec: {e}", "spec": spec}
        state.pending_specs = specs
        return {"ok": True, "count": len(specs)}

    @server.tool()
    @_safe_tool
    def get_invocation(index: int) -> dict:
        """Look up a past invocation by history index (returned by invoke)."""
        if index not in state.full_history:
            return {
                "ok": False,
                "error": f"index {index} not in history",
                "available": list(state.full_history.keys()),
            }
        entry = state.full_history[index]
        return {
            "ok": True,
            "ts": entry["ts"],
            "duration_ms": entry["duration_ms"],
            "kwargs_summary": entry["kwargs"],
            "outputs_summary": entry["outputs"],
        }

    @server.tool()
    @_safe_tool
    def list_component_types() -> dict:
        """List the legal `type` values for a UI spec.

        Returns ``{"types": [...]}`` — wrapped in a dict because raw lists
        get serialized as N separate content blocks by the MCP SDK.
        """
        return {"types": _component_types()}

    @server.tool()
    @_safe_tool
    def screenshot() -> dict:
        """Render current outputs to images/text server-side.

        Plotly Figure → PNG via lazy kaleido import. PIL Image → PNG.
        Pandas DataFrame → CSV (first 50 rows). Strings → text. Anything
        else → unsupported marker. Returns ``{"outputs": [...]}`` with
        one entry per output.
        """
        results = []
        outs_snapshot = dict(state.outputs)
        for d in _enumerate_outputs(fd):
            entry = {"id": d["id"], "tag": d["tag"]}
            val = outs_snapshot.get(d["id"])
            if val is None:
                entry["content"] = None
                results.append(entry)
                continue
            entry.update(_render_one_output(val))
            results.append(entry)
        return {"outputs": results}


def _render_one_output(val) -> dict:
    """Render a single output value for `screenshot()`."""
    try:
        import plotly.graph_objects as go
        if isinstance(val, go.Figure):
            try:
                png = val.to_image(format="png", width=900, height=600)
                return {
                    "mime": "image/png",
                    "content_b64": base64.b64encode(png).decode("ascii"),
                }
            except Exception as e:
                # kaleido is an ~80MB optional and is the common missing
                # piece. Fall back to the figure spec — but route it through
                # Plotly's own JSON encoder (``to_json`` handles numpy
                # arrays), since the raw ``to_plotly_json()`` dict is NOT
                # JSON-serializable and would otherwise crash the response.
                return {
                    "mime": None,
                    "error": (
                        f"Plotly-to-PNG failed; install 'kaleido' for "
                        f"server-side image render: {type(e).__name__}: {e}"
                    ),
                    "figure": json.loads(val.to_json()),
                }
    except ImportError:
        pass

    try:
        import PIL.Image
        if isinstance(val, PIL.Image.Image):
            buf = io.BytesIO()
            val.save(buf, format="PNG")
            return {
                "mime": "image/png",
                "content_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
            }
    except ImportError:
        pass

    try:
        import pandas as pd
        if isinstance(val, pd.DataFrame):
            return {
                "mime": "text/csv",
                "content": val.head(50).to_csv(index=False),
                "shape": list(val.shape),
            }
    except ImportError:
        pass

    if isinstance(val, str):
        if val.startswith("data:") and ";base64," in val:
            header = val.split(",", 1)[0]
            return {
                "mime": "text/plain",
                "content": f"<{header}, {len(val)} chars>",
            }
        return {"mime": "text/plain", "content": val}

    if isinstance(val, (bytes, bytearray)):
        return {
            "mime": "application/octet-stream",
            "content_b64": base64.b64encode(bytes(val)).decode("ascii"),
            "size": len(val),
        }

    return {
        "mime": None,
        "unsupported": True,
        "type": type(val).__name__,
        "repr": repr(val)[:200],
    }


def serve_mcp_in_thread(
    app_or_callable,
    *,
    host: str = "127.0.0.1",
    port: int = 8001,
    title: str | None = None,
) -> threading.Thread:
    """Start the MCP server on a background daemon thread.

    **Most apps don't call this directly.** Passing ``mcp_server=True`` to
    ``FastDash`` / ``@fastdash`` / ``DynamicDash`` makes ``run()`` start the
    server for you — that's the one obvious path. Reach for this helper only
    to attach MCP to a *bare callable* (no app instance) or to manage the
    server thread yourself.

    Accepts a FastDash/DynamicDash instance (full surface: resources +
    tools) or a plain callable (just the callback registered as one tool).
    Returns the thread.
    """
    server = build_mcp_server(app_or_callable, title=title)
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
        uv_server.run()

    thread = threading.Thread(target=_run, daemon=True, name="fastdash-mcp")
    thread.start()

    global _active_mcp_thread
    _active_mcp_thread = thread
    return thread
