"""Model Context Protocol (MCP) server for Fast Dash apps.

As of v0.4, fast_dash mounts **Dash's native MCP server** (Dash >= 4.3) on the
same Flask app instead of running a separate FastMCP server on a second port.

What an agent sees
-------------------

* **Native Dash resources** (read-only, delegated to Dash): ``dash://layout``,
  ``dash://components``, and the ``get_dash_component`` tool — Dash's
  introspection of the live component tree.
* **fast_dash tools** (registered via ``dash.mcp.mcp_enabled``) that *drive the
  live app* — the stateful counterpart to Dash's stateless "ask the app"
  callback tools:
    - ``set_input(component_id, value)`` / ``set_inputs({...})``
    - ``invoke(inputs=None)`` — run the callback with the current input mirror
    - ``set_form(specs)`` — DynamicDash only
    - ``get_invocation(index)`` — full kwargs+result from history
    - ``list_component_types()``

Usage::

    from fast_dash import fastdash

    @fastdash(mcp_server=True)
    def search_db(query: str, limit: int = 10) -> list[str]:
        '''Search the user database.'''
        ...

The web app and the MCP server now share one port. Agents connect at
``http://<host>:<port>/mcp`` (e.g. ``http://localhost:8080/mcp``) over
streamable-HTTP::

    {"servers": {"my-app": {"url": "http://localhost:8080/mcp"}}}

Why native
----------

Dash 4.3 ships the resource/transport/result-formatting layer fast_dash used
to hand-build on FastMCP. Delegating it drops a separate port, the ``mcp``/
``uvicorn`` server plumbing, and our bespoke result serialization (Dash formats
Plotly figures, DataFrames, etc.). fast_dash keeps only what Dash's *stateless*
MCP doesn't do: tools that mutate the running app and reflect into the live
browser (via the v0.2 ``dcc.Interval`` drain; WebSocket ``set_props`` push is a
later stage).

Limitations
-----------

* **Single app per process.** Tool registration uses Dash's global
  ``mcp_enabled`` registry keyed by tool name, so two MCP-enabled fast_dash
  apps in one process would collide.
* **No auth on the MCP route.** It shares the web app's host/port; bind to
  loopback in development.
* Multi-function and steps modes skip the MCP surface.
"""

from __future__ import annotations

import collections
import datetime
import inspect
import time
from typing import Any

# Holder kept for backwards compatibility with older imports/tests.
_active_mcp_thread = None


class MCPState:
    """Server-side mirror of a fast_dash app's input/output state.

    Shared between the Dash request thread (mirror + drain callbacks) and the
    MCP tool handlers (reads/writes). CPython's GIL makes single-key writes
    safe; ``deque(maxlen=N)`` is thread-safe for ``append``.

    MCP tools also write to ``pending_inputs`` / ``pending_specs`` /
    ``pending_outputs``; a Dash ``dcc.Interval`` drain pops these and applies
    them to the live UI (v0.2 server -> browser push).
    """

    def __init__(self, history_size: int = 20):
        self.inputs: dict[str, Any] = {}
        self.outputs: dict[str, Any] = {}
        self.history: collections.deque = collections.deque(maxlen=history_size)
        self.full_history: collections.OrderedDict = collections.OrderedDict()
        self._history_size = history_size
        self.pending_inputs: dict[str, Any] = {}
        self.pending_specs: list[dict] | None = None
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
        out, self.pending_inputs = self.pending_inputs, {}
        return out

    def pop_pending_specs(self) -> list[dict] | None:
        out, self.pending_specs = self.pending_specs, None
        return out

    def pop_pending_outputs(self) -> dict[str, Any]:
        out, self.pending_outputs = self.pending_outputs, {}
        return out


# --------------------------------------------------------------------------- #
# Introspection helpers (shared by the tools)
# --------------------------------------------------------------------------- #

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
    import json
    return json.dumps(cid, sort_keys=True)


def _enumerate_inputs(fd) -> list[dict]:
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
    if component_id.startswith("input_"):
        return component_id[len("input_"):]
    return component_id


def _seed_input_mirror(fd) -> None:
    """Pre-populate the input mirror from component / signature defaults.

    The browser mirror callback only fires once a client renders the page; a
    headless agent would otherwise see ``null`` inputs and ``invoke()`` would
    silently fall back to defaults. DynamicDash has no static inputs, so this
    is a no-op there.
    """
    state: MCPState = fd._mcp_state
    components = getattr(fd, "inputs_with_ids", None) or []

    for c in components:
        cid = _stringify_id(c.id)
        if cid in state.inputs:
            continue
        prop = getattr(c, "component_property", "value")
        val = getattr(c, prop, None)
        if val is not None:
            state.inputs[cid] = val

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


def _json_type_name(annotation) -> str:
    """Best-effort JSON-schema type name for a Python annotation."""
    return {
        int: "integer", float: "number", str: "string",
        bool: "boolean", list: "array", dict: "object",
    }.get(annotation, "string")


def _annotation_options(annotation):
    """Allowed values for a Literal[...] or Enum annotation, else None."""
    try:
        import enum
        import typing
        if typing.get_origin(annotation) is typing.Literal:
            return list(typing.get_args(annotation))
        if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
            return [e.value for e in annotation]
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------- #
# Native MCP mount + fast_dash tool registration
# --------------------------------------------------------------------------- #

def _ensure_dash_mcp():
    """Import Dash's native MCP API, with a clear error if too old."""
    try:
        from dash.mcp import (  # type: ignore[import-not-found]
            configure_mcp_server,
            enable_mcp_server,
            mcp_enabled,
        )
    except ImportError as e:
        raise ImportError(
            "fast_dash's MCP server now requires Dash's native MCP support "
            "(Dash >= 4.3). Upgrade with:\n    pip install 'dash>=4.3'"
        ) from e
    return enable_mcp_server, configure_mcp_server, mcp_enabled


def enable_mcp(fd, *, mcp_path: str = "mcp") -> None:
    """Mount Dash's native MCP server on ``fd.app`` and register fast_dash tools.

    Idempotent per app. Delegates the read-only base surface (layout,
    components, ``get_dash_component``) to Dash and registers fast_dash's
    stateful "drive the app" tools on top via ``mcp_enabled``.
    """
    enable_mcp_server, configure_mcp_server, mcp_enabled = _ensure_dash_mcp()

    from fast_dash.utils import _jsonify_for_mcp, _summarize_for_history

    if not hasattr(fd, "_mcp_state") or fd._mcp_state is None:
        fd._mcp_state = MCPState()
    state: MCPState = fd._mcp_state
    _seed_input_mirror(fd)

    if getattr(fd, "_mcp_mounted", False):
        return
    fd._mcp_mounted = True

    # Delegate the introspection surface to Dash; hide the noisy internal Dash
    # callbacks (process_input, toggle_sidebar, ...). fast_dash's `invoke` tool
    # is the clean way to run the user's callback.
    configure_mcp_server(
        include_layout=True,
        include_callbacks=False,
        include_clientside_callbacks=False,
        include_pages=False,
    )

    # ----- fast_dash value-add tools (stateful: drive the live app) --------- #

    @mcp_enabled(name="set_input", expose_docstring=True)
    def set_input(component_id: str, value: Any) -> dict:
        """Update one input's value, server-side and live in the browser.

        Browser update lands within ~500ms (Dash ``Interval`` drain).
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

    @mcp_enabled(name="set_inputs", expose_docstring=True)
    def set_inputs(inputs: dict) -> dict:
        """Bulk-update multiple input values (keyed by parameter name).

        The argument is named ``inputs`` to match ``invoke(inputs=...)``.
        """
        ids = {d["id"] for d in _enumerate_inputs(fd)}
        applied, errors = {}, {}
        for k, v in (inputs or {}).items():
            if ids and k not in ids:
                errors[k] = "unknown id"
                continue
            state.inputs[k] = v
            state.pending_inputs[k] = v
            applied[k] = _jsonify_for_mcp(v)
        return {"ok": not errors, "applied": applied, "errors": errors}

    @mcp_enabled(name="invoke", expose_docstring=True)
    def invoke(inputs: dict = None) -> dict:
        """Run the app's callback with the current input mirror.

        Pass ``inputs`` to set values and run in a single call (atomic
        validation: a bad key rejects without mutating the mirror).
        """
        if getattr(fd, "is_multi", False) or getattr(fd, "is_steps", False):
            return {
                "ok": False,
                "error": "invoke not supported in multi-function/steps mode",
            }

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

        result_list = list(result) if isinstance(result, (list, tuple)) else [result]
        out_summary = {}
        for d, val in zip(_enumerate_outputs(fd), result_list):
            state.outputs[d["id"]] = val
            state.pending_outputs[d["id"]] = val
            out_summary[d["id"]] = _summarize_for_history(val)

        entry_summary = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "duration_ms": dt_ms,
            "kwargs": {k: _summarize_for_history(v) for k, v in kwargs.items()},
            "outputs": out_summary,
        }
        entry_full = {**entry_summary, "_full_kwargs": kwargs, "_full_result": result}
        idx = state.append_history(entry_summary, entry_full)
        return {
            "ok": True,
            "duration_ms": dt_ms,
            "outputs": out_summary,
            "history_index": idx,
        }

    @mcp_enabled(name="set_form", expose_docstring=True)
    def set_form(specs: list) -> dict:
        """Replace the form on a DynamicDash app with a new spec list.

        The DynamicDash drain re-renders the form live within ~500ms. Plain
        FastDash apps reject this tool.
        """
        from fast_dash.dynamic import _spec_to_component

        if not _is_dynamic(fd):
            return {"ok": False, "error": "set_form requires a DynamicDash app"}
        if not isinstance(specs, list):
            return {"ok": False, "error": "specs must be a list of dicts"}
        for spec in specs:
            try:
                _spec_to_component(spec)
            except (TypeError, ValueError) as e:
                return {"ok": False, "error": f"invalid spec: {e}", "spec": spec}
        state.pending_specs = specs
        return {"ok": True, "count": len(specs)}

    @mcp_enabled(name="get_invocation", expose_docstring=True)
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

    @mcp_enabled(name="list_component_types", expose_docstring=True)
    def list_component_types() -> dict:
        """List the legal ``type`` values for a DynamicDash UI spec."""
        return {"types": _component_types()}

    @mcp_enabled(name="describe_app", expose_docstring=True)
    def describe_app() -> dict:
        """Describe the app's inputs: id, type, default, options, and CURRENT value.

        This is the reliable way for a headless agent (no browser) to read the
        app's input contract *and* its live state before calling ``invoke``:
        each input reports its parameter ``id``, JSON ``type``, ``default``,
        any allowed ``options`` (for dropdowns / ``Literal`` / ``Enum``), and
        its ``current_value`` — including values you set via ``set_input`` /
        ``set_inputs``. (The native ``dash://components`` resource lists ids and
        Dash *widget* types only, and ``get_dash_component`` reflects the
        browser, not the agent's mirror, so neither shows agent-set values
        headlessly.)
        """
        snapshot = dict(state.inputs)
        descriptors = _enumerate_inputs(fd)
        try:
            sig_params = dict(inspect.signature(fd.callback_fn).parameters)
        except (TypeError, ValueError):
            sig_params = {}
        # Resolve string annotations (modules using ``from __future__ import
        # annotations``) to real types; fall back to the raw annotation.
        try:
            import typing
            hints = typing.get_type_hints(fd.callback_fn)
        except Exception:
            hints = {}

        inputs = []
        if descriptors:
            for d in descriptors:
                cid = d["id"]
                param = _param_name_from_id(cid)
                p = sig_params.get(param) or sig_params.get(cid)
                jtype, default, options = "string", None, None
                if p is not None:
                    ann = hints.get(param, hints.get(cid, p.annotation))
                    jtype = _json_type_name(ann)
                    options = _annotation_options(ann)
                    if p.default is not inspect.Parameter.empty:
                        if isinstance(p.default, list) and options is None:
                            options = list(p.default)
                        else:
                            default = p.default
                cur = snapshot.get(cid, snapshot.get(param))
                inputs.append({
                    "id": cid,
                    "tag": d["tag"],
                    "type": jtype,
                    "default": _jsonify_for_mcp(default),
                    "options": _jsonify_for_mcp(options),
                    "current_value": _jsonify_for_mcp(cur),
                })
        else:
            # DynamicDash / **kwargs callback: no static inputs — reflect the
            # current mirror (whatever set_form/set_inputs populated).
            for k, v in snapshot.items():
                inputs.append({"id": k, "current_value": _jsonify_for_mcp(v)})

        return {
            "title": getattr(fd, "title", None) or "",
            "doc": (getattr(fd.callback_fn, "__doc__", "") or "").strip(),
            "inputs": inputs,
        }

    # Mount the MCP routes on the Dash app (same port).
    enable_mcp_server(fd.app, mcp_path)

    # On an ASGI backend, work around an upstream Dash 4.3 bug that breaks the
    # /mcp route (see _install_asgi_mcp_request_context).
    if getattr(fd, "_backend", None):
        _install_asgi_mcp_request_context(fd.app.server, mcp_path)


def _install_asgi_mcp_request_context(server, mcp_path: str) -> None:
    """Make Dash's native ``/mcp`` route work on the FastAPI/Quart backend.

    Dash 4.3's ``DashMiddleware`` only sets the per-request context (and the
    pre-parsed ``request.state.json_body``) for ``/_dash-*`` routes — it passes
    every other path straight through "to avoid consuming the body stream". But
    Dash's own native ``/mcp`` route (added via ``add_url_rule``) is *not* a
    ``/_dash-`` route, so its sync POST handler raises
    ``RuntimeError: No active request in context`` (and then ``json_body``
    missing) on the ASGI backend. Until that's fixed upstream, we add a tiny
    ASGI middleware that sets the request context + parsed body for the ``/mcp``
    path so the handler works. No-op if Starlette / the FastAPI backend isn't
    present (e.g. the default Flask backend).
    """
    try:
        from dash.backends._fastapi import (  # type: ignore[import-not-found]
            reset_current_request,
            set_current_request,
        )
        from starlette.requests import Request  # type: ignore[import-not-found]
    except Exception:
        return

    suffix = "/" + mcp_path.strip("/")

    class _MCPRequestContext:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http" and scope.get(
                "path", ""
            ).rstrip("/").endswith(suffix):
                request = Request(scope, receive=receive)
                try:
                    ct = request.headers.get("content-type", "")
                    request.state.json_body = (
                        await request.json()
                        if ct.startswith("application/json")
                        else None
                    )
                except Exception:
                    request.state.json_body = None
                token = set_current_request(request)
                try:
                    await self.app(scope, receive, send)
                finally:
                    reset_current_request(token)
            else:
                await self.app(scope, receive, send)

    server.add_middleware(_MCPRequestContext)
