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
import functools
import inspect
import os
import time
import warnings
from typing import Any

# Holder kept for backwards compatibility with older imports/tests.
_active_mcp_thread = None

# Addresses that keep the (unauthenticated) /mcp route on this machine.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def effective_bind_host(run_kwargs: dict | None) -> str:
    """The address the server will actually bind to.

    Mirrors Dash's own default (``HOST`` env var, else loopback), so callers
    see the same host the dev server will use.
    """
    host = (run_kwargs or {}).get("host")
    return host or os.getenv("HOST") or "127.0.0.1"


def warn_if_exposed(run_kwargs: dict | None, *, stacklevel: int = 3) -> None:
    """Warn when MCP is enabled on a socket reachable from off-box.

    The MCP route is mounted on the Dash app itself, so what decides who can
    reach it is the *server's* bind address -- ``run_kwargs["host"]`` (or the
    ``HOST`` env var). The legacy ``mcp_host`` kwarg has not bound anything
    since MCP moved onto the shared port, so warning on it gave a false
    all-clear to ``mcp_server=True, run_kwargs={"host": "0.0.0.0"}`` -- the one
    configuration that actually exposes an unauthenticated tool endpoint (#149).
    """
    host = effective_bind_host(run_kwargs)
    if host in LOOPBACK_HOSTS:
        return
    warnings.warn(
        f"mcp_server=True with host={host!r} serves the /mcp endpoint on a "
        "non-loopback address. That endpoint has no authentication: anyone who "
        "can reach this port can read your app's state and invoke your callback. "
        "Bind to 127.0.0.1 unless you have put an authenticating proxy in front.",
        stacklevel=stacklevel,
    )


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
        # The form currently on screen (DynamicDash). Unlike pending_specs
        # (popped by the browser drain), this persists so describe_app can report
        # the form's contract — even after a browser renders it or a different
        # agent reconnects. Always write it through set_current_specs.
        self.current_specs: list[dict] | None = None
        # Every field ever declared a PasswordInput on this app. Accumulates and
        # never shrinks: a credential that was in the mirror must stay masked
        # even after the form that declared it is replaced.
        self.secret_ids: set = set()

    def set_current_specs(self, specs, keep=()) -> None:
        """Point the contract at the form that is now on screen.

        *Every* path that builds or replaces a DynamicDash form must call this —
        ``initial_specs``, a ``parent_control`` cascade, and an agent's
        ``set_form`` alike. The contract, the validators and the secret list are
        all derived from it, so a form the agent didn't build itself would
        otherwise have no contract at all: no ids to check, no options to
        enforce, no secrets to mask.

        Values belonging to fields the new form doesn't have are dropped, or
        describe_app would go on reporting them (in the clear, if one of them was
        a password) and ``invoke`` would go on passing them to the callback.
        """
        self.current_specs = [s for s in (specs or []) if isinstance(s, dict)]
        live = {s.get("name") for s in self.current_specs}
        live.update(keep)
        self.secret_ids.update(
            s["name"] for s in self.current_specs
            if s.get("type") == "PasswordInput" and s.get("name")
        )
        for key in [k for k in self.inputs if k not in live]:
            del self.inputs[key]
            self.pending_inputs.pop(key, None)

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
                # A scalar default IS the value. A list/dict/range default is the
                # component's *options* (dropdown / multi-select / slider
                # bounds), not its value — the browser renders None there, so
                # seed None (not the options) so describe_app's current_value is
                # type-consistent and invoke() matches a UI Run (issue #110).
                state.inputs[name] = (
                    p.default
                    if isinstance(p.default, (str, bool, int, float))
                    else None
                )
    except (TypeError, ValueError):
        pass


def _json_type_name(annotation) -> str:
    """Best-effort JSON-schema type name for a Python annotation.

    Unwraps ``Optional[T]`` / ``Union[T, None]`` (and PEP 604 ``T | None``) to
    the single non-``None`` member first, so an optional parameter reports the
    type it actually accepts instead of collapsing to ``"string"`` (issue #132).
    """
    try:
        import types as _types
        import typing

        origin = typing.get_origin(annotation)
        is_union = origin is typing.Union or (
            hasattr(_types, "UnionType") and origin is _types.UnionType
        )
        if is_union:
            members = [a for a in typing.get_args(annotation) if a is not type(None)]
            if len(members) == 1:
                annotation = members[0]
    except Exception:
        pass
    return {
        int: "integer", float: "number", str: "string",
        bool: "boolean", list: "array", dict: "object",
    }.get(annotation, "string")


# JSON type each DynamicDash spec component emits. Lets describe_app report a
# uniform JSON ``type`` for both static and dynamic apps — a static app derived
# it from the callback annotation, a DynamicDash form has no annotations, so it
# derives it from the spec's component name here. The component name itself
# always stays in the ``tag`` field. (issue #131)
_SPEC_JSON_TYPE = {
    "Text": "string", "TextArea": "string", "Select": "string",
    "DateInput": "string", "ColorInput": "string", "PasswordInput": "string",
    "Markdown": "string", "Upload": "string", "UploadImage": "string",
    "NumberInput": "number", "Slider": "number",
    "Switch": "boolean",
    "MultiSelect": "array", "DateRange": "array",
}


def _spec_json_type(spec_type) -> str:
    """JSON type for a DynamicDash spec component name, defaulting to string."""
    return _SPEC_JSON_TYPE.get(spec_type, "string")


def _annotation_options(annotation):
    """Allowed values for a Literal[...] or Enum annotation, else None."""
    try:
        import enum
        import typing
        if typing.get_origin(annotation) is typing.Literal:
            return list(typing.get_args(annotation))
        if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
            # Match the UI Select, which is built with str(e.value) options — so
            # an IntEnum's options are ["1", "2"], not [1, 2] (issue #126).
            return [str(e.value) for e in annotation]
    except Exception:
        pass
    return None


def _resolve_depends_on_options(fd, dep, snapshot):
    """Options for a ``depends_on`` dependent dropdown given the current parent.

    Mirrors the browser cascade exactly: runs the resolver against the parent
    input's current value via ``FastDash._apply_dependency_resolver`` and
    returns the resulting ``data`` (the dropdown options) as a list, or ``None``
    when the parent is unset or the resolver yields no options. Reusing the same
    helper the live callback uses keeps the agent contract and the UI in sync.
    """
    try:
        from fast_dash.fast_dash import FastDash
    except Exception:
        return None
    parent_val = snapshot.get(dep.parent)
    try:
        data, _value = FastDash._apply_dependency_resolver(dep.resolver, parent_val)
    except Exception:
        return None
    return list(data) if isinstance(data, list) else None


def _component_bounds(comp):
    """Numeric ``{min, max, step}`` carried by a Slider/number component, else {}.

    A Slider built from ``Annotated[int, range(...)]`` / an ``int = range(...)``
    default stores hard ``min`` / ``max`` / ``step`` props; a plain number box
    sets none. Surfacing them lets a headless agent discover (and stay within) a
    slider's range, the same way DynamicDash forms already expose their props
    (issue #120).
    """
    if comp is None:
        return {}
    props = {}
    for k in ("min", "max", "step"):
        v = getattr(comp, k, None)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            props[k] = v
    return props


# What an agent sees instead of a secret's value. Not a valid value for any
# widget, so a round-trip of describe_app -> set_input can't silently re-send it.
REDACTED = "********"


def _is_password_component(comp) -> bool:
    return type(getattr(comp, "component", comp)).__name__ == "PasswordInput"


def _secret_ids(fd, state=None) -> set:
    """Ids whose value must never be echoed back over MCP.

    A PasswordInput is the one widget whose value the browser deliberately
    masks. Echoing it in ``describe_app`` / ``get_invocation`` would turn the
    unauthenticated /mcp route into a plaintext read-out of a credential the UI
    hides (#151), so the value goes in but never comes back out.

    Static apps declare their inputs up front. A DynamicDash's fields come and
    go, so its secrets are read from ``state.secret_ids``, which accumulates
    every field ever declared a PasswordInput — including one whose form has
    since been replaced, whose value would otherwise fall out of the contract's
    mask and into describe_app's plain-mirror tail.
    """
    ids = set()
    for c in (getattr(fd, "inputs_with_ids", None) or []):
        if _is_password_component(c) or getattr(c, "tag", None) == "PasswordInput":
            ids.add(_stringify_id(c.id))
    parent = getattr(fd, "parent_control", None)
    if isinstance(parent, dict) and parent.get("type") == "PasswordInput" and parent.get("name"):
        ids.add(parent["name"])
    if state is not None:
        ids.update(getattr(state, "secret_ids", None) or set())
    return ids


def _redact(entry, value):
    """The value ``entry`` may reveal: itself, or a mask for a secret input."""
    if not entry.get("secret"):
        return value
    return REDACTED if value not in (None, "") else value


def _redact_props(entry, props):
    """Props minus anything that carries the widget's value.

    ``default`` and ``current_value`` are masked for a secret input, but a spec
    is free to carry its value in ``props`` (``_describe_dynamic_inputs`` reads
    ``props["value"]`` as a fallback default) — and props were echoed verbatim,
    so the credential rode out in a sibling field of the very entry stamped
    ``"secret": true``.
    """
    if not entry.get("secret") or not isinstance(props, dict):
        return props
    return {k: v for k, v in props.items() if k not in ("value", "defaultValue")}


def _normalize_options(options):
    """Flatten dropdown options to the plain values a widget can emit.

    A DynamicDash ``Select``/``MultiSelect`` may declare its ``data`` as
    ``[{"label": ..., "value": ...}, ...]``; only the ``value`` half is ever
    emitted, so that is what membership must be checked against.
    """
    if not isinstance(options, (list, tuple)):
        return None
    out = []
    for o in options:
        out.append(o["value"] if isinstance(o, dict) and "value" in o else o)
    return out


def _type_error(entry, value):
    """Reject a value whose JSON type the widget could never emit, else None.

    The bounds check below only fires for numbers, so before #150 a *string*
    sailed past a Slider's ``min``/``max`` untouched (``"9999"`` is not an
    ``int``, so nothing compared it to the maximum) and reached the callback as
    a string — a value no drag of the slider could produce. Types with more than
    one legal wire shape (dates, uploads, and anything with ``options``, which
    is membership-checked instead) stay permissive.
    """
    jtype = entry.get("type")
    if jtype in ("integer", "number"):
        # bool is an int subclass in Python; a Switch value is not a number.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            article = "an" if jtype == "integer" else "a"
            return f"expected {article} {jtype}, got {type(value).__name__} ({value!r})"
        if jtype == "integer" and isinstance(value, float) and not value.is_integer():
            return f"expected an integer, got {value!r}"
    elif jtype == "boolean" and not isinstance(value, bool):
        return f"expected a boolean, got {type(value).__name__} ({value!r})"
    return None


def _describe_dynamic_inputs(fd, snapshot, specs, state=None):
    """Per-input contract for a DynamicDash form, whoever built it.

    Same shape as the static contract, derived from the live specs instead of a
    callback signature — so the options and bounds the form declares are the ones
    ``set_input`` / ``invoke`` then enforce against it (#144), whether those
    specs came from ``initial_specs``, a ``parent_control`` cascade, or an
    agent's ``set_form``. The parent control is part of the contract too: the UI
    passes it to the callback like any other field, so an agent must be able to
    discover and drive it.
    """
    from fast_dash.utils import _jsonify_for_mcp

    secrets = _secret_ids(fd, state)
    parent = getattr(fd, "parent_control", None)
    all_specs = list(specs)
    if isinstance(parent, dict) and parent.get("name"):
        all_specs = [parent] + all_specs

    contract = []
    for spec in all_specs:
        name = spec.get("name")
        if not name:
            continue
        props = spec.get("props") or {}
        default = spec.get("value", props.get("value"))
        cur = snapshot.get(name, default)
        entry = {
            "id": name,
            # tag = the DynamicDash component name (e.g. "Slider"); type = its
            # JSON type, so ``type`` means the same thing here as on a static
            # app's contract (issue #131).
            "tag": spec.get("type"),
            "type": _spec_json_type(spec.get("type")),
            "label": spec.get("label"),
            "options": _jsonify_for_mcp(_normalize_options(props.get("data"))),
            "secret": name in secrets,
        }
        entry["props"] = _jsonify_for_mcp(_redact_props(entry, props))
        entry["default"] = _jsonify_for_mcp(_redact(entry, default))
        entry["current_value"] = _jsonify_for_mcp(_redact(entry, cur))
        contract.append(entry)
    return contract


def _input_contract(fd, snapshot, state=None):
    """The app's input contract, static or dynamic — one source of truth.

    ``describe_app`` reports it and the validators enforce it, so an agent can
    never set a value the app doesn't advertise, whichever kind of app it is.
    """
    if _enumerate_inputs(fd):
        return _describe_static_inputs(fd, snapshot)
    state = state if state is not None else getattr(fd, "_mcp_state", None)
    specs = getattr(state, "current_specs", None) if state is not None else None
    if specs or (specs is not None and getattr(fd, "parent_control", None)):
        return _describe_dynamic_inputs(fd, snapshot, specs or [], state)
    return []


def _describe_static_inputs(fd, snapshot):
    """Per-input contract for a static FastDash app.

    Single source of truth for ``describe_app`` and the value validators, so a
    headless agent's contract matches what ``set_input`` / ``invoke`` enforce
    (human<->agent parity). Each entry is ``{id, tag, type, default, options,
    current_value}`` plus a ``props`` block when the widget carries numeric
    bounds. Resolves ``depends_on`` / list / dict / ``Literal`` / ``Enum``
    defaults into clean JSON and **never** leaks an object ``repr`` into a
    contract field (issue #116).
    """
    import enum

    from fast_dash.utils import _jsonify_for_mcp, depends_on

    descriptors = _enumerate_inputs(fd)
    components = {
        _stringify_id(c.id): c
        for c in (getattr(fd, "inputs_with_ids", None) or [])
    }
    try:
        sig_params = dict(inspect.signature(fd.callback_fn).parameters)
    except (TypeError, ValueError):
        sig_params = {}
    # Resolve string annotations (``from __future__ import annotations``) to real
    # types; fall back to the raw annotation.
    try:
        import typing
        hints = typing.get_type_hints(fd.callback_fn)
    except Exception:
        hints = {}

    secrets = _secret_ids(fd)
    contract = []
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
                dflt = p.default
                if isinstance(dflt, depends_on):
                    # Dependent dropdown: starts empty (the browser renders an
                    # unselected Select); its options come from the current
                    # parent value, resolved exactly as the live cascade does.
                    if options is None:
                        options = _resolve_depends_on_options(fd, dflt, snapshot)
                elif isinstance(dflt, enum.Enum):
                    # An Enum member's contract value is str(member.value) — the
                    # exact value the UI Select emits (Components builds it with
                    # value=str(e.value)). Handle it before the scalar branch
                    # below, since str-mixin / IntEnum members ARE str/int (which
                    # would otherwise surface the raw int for an IntEnum, out of
                    # sync with options and current_value). (issue #126)
                    default = str(dflt.value)
                elif isinstance(dflt, list):
                    if options is None:
                        options = list(dflt)          # list default = dropdown options
                elif isinstance(dflt, dict):
                    if options is None:
                        options = list(dflt.keys())   # dict default = MultiSelect keys
                elif isinstance(dflt, (datetime.date, datetime.datetime)):
                    # A DateInput/date-range default is a date/datetime object, not
                    # a scalar — surface its ISO string (the exact value the browser
                    # DatePicker emits) instead of dropping it to null. isoformat()
                    # keeps the time component for a datetime. (issue #134)
                    default = dflt.isoformat()
                elif isinstance(dflt, (str, bool, int, float)):
                    default = dflt                    # a scalar default IS the value
                # else (range / arbitrary objects): leave default None so the
                # contract never carries a non-JSON repr (issue #116).
        cur = snapshot.get(cid, snapshot.get(param))
        # The widget actually rendered, named as list_component_types() --
        # not the hint name static inference stamps on `tag` (#147/#158).
        tag = _input_widget_tag(components.get(cid), d["tag"])
        # A MultiSelect's value is an *array* of selected option keys, whatever
        # the annotation implied. A ``dict`` default renders a MultiSelect over
        # its keys, so the annotation-derived "object" would advertise a value
        # the UI can never produce and the validators reject. Reconcile the
        # declared type with the widget actually rendered -- the same answer
        # _SPEC_JSON_TYPE already gives on the DynamicDash path. (issue #162)
        if tag == "MultiSelect":
            jtype = "array"
        entry = {
            "id": cid,
            "tag": tag,
            "type": jtype,
            "options": _jsonify_for_mcp(options),
            "secret": cid in secrets,          # PasswordInput: value never echoed (#151)
        }
        entry["default"] = _jsonify_for_mcp(_redact(entry, default))
        entry["current_value"] = _jsonify_for_mcp(_redact(entry, cur))
        bounds = _component_bounds(components.get(cid))
        if bounds:
            entry["props"] = bounds                   # Slider min/max/step (issue #120)
        contract.append(entry)
    return contract


# (tag, JSON type) per rendered output component. An output's Python annotation
# is often a rich object (``go.Figure``, ``pd.DataFrame``, ``PIL.Image``) with no
# JSON scalar equivalent, so the component it was rendered into is the honest
# description of what an agent gets back from ``invoke``.
_OUTPUT_KIND = {
    "Graph": ("Graph", "object"),
    "DataTable": ("Table", "array"),
    "Markdown": ("Markdown", "string"),
    "Textarea": ("Text", "string"),
    "TextInput": ("Text", "string"),
    "H1": ("Text", "string"),
    "Div": ("Text", "string"),
    "Img": ("Image", "string"),
    "Download": ("Download", "string"),
}


def _output_kind(comp):
    """(tag, JSON type) for one output component.

    ``FastComponent.tag`` is unusable here: an inferred ``-> str`` output carries
    the raw annotation *object* (``<class 'str'>``) and an explicit ``Table``
    carries ``None``. Nothing serialized it before #152, so nobody noticed. The
    rendered component is always present and always honest.
    """
    name = type(getattr(comp, "component", comp)).__name__
    return _OUTPUT_KIND.get(name, (name, "object"))


# Live widget class -> the canonical widget name from list_component_types()
# (the DynamicDash COMPONENT_REGISTRY keys). What static inference *actually*
# builds, empirically -- e.g. a hex-default str becomes a dmc.ColorInput, a
# list-default str becomes a dmc.Select, a bool becomes a dmc.Checkbox (whose
# spec-level equivalent is "Switch").
_INPUT_WIDGET_TAG = {
    "TextInput": "Text",
    "Textarea": "TextArea",
    "ColorInput": "ColorInput",
    "PasswordInput": "PasswordInput",
    "NumberInput": "NumberInput",
    "Slider": "Slider",
    "RangeSlider": "Slider",
    "Select": "Select",
    "MultiSelect": "MultiSelect",
    "Checkbox": "Switch",
    "Switch": "Switch",
    "DatePickerSingle": "DateInput",
    "DateInput": "DateInput",
    "DatePickerRange": "DateRange",
    "DatePickerInput": "DateRange",
    "Markdown": "Markdown",
}


def _input_widget_tag(component, raw_tag):
    """The widget a static input actually became, named as list_component_types().

    ``describe_app`` reports whatever ``tag`` the component was built with, but
    static inference stamps the *hint* name there, not the widget's: a
    list-default ``str`` renders a Select yet carries tag ``"Text"`` (identical
    to a plain text box), and int/bool/date/Literal carry internal names
    (``"Numeric"``/``"Boolean"``/``"Date"``/``"Literal"``) that aren't in
    ``list_component_types()`` at all (#147 fixed only the ColorInput/TextArea
    branches; #158 is the rest). The raw tag can't be trusted -- that Select
    literally says ``"Text"`` -- so read the live widget class, which is honest.
    Fall back to the raw tag for a user-supplied component we don't recognize.
    """
    # The image-upload widget is a bare dcc.Upload; only its construction tag
    # distinguishes it from a file upload.
    if raw_tag == "Image":
        return "UploadImage"
    name = type(getattr(component, "component", component)).__name__
    if name == "Upload":
        return "UploadImage" if raw_tag == "Image" else "Upload"
    return _INPUT_WIDGET_TAG.get(name, raw_tag)


def _describe_outputs(fd, state=None):
    """Per-output contract: what ``invoke`` will produce, without running it.

    ``describe_app`` used to report inputs only, so the sole way for a headless
    agent to learn what an app returns was to *call* it — discovery by side
    effect (#152). Each entry is ``{id, tag, type, label}``, plus a summary of
    the value currently on screen once something has run.
    """
    from fast_dash.Components import expand_return_annotation
    from fast_dash.utils import _summarize_for_history

    # DynamicDash stores its prepared outputs under the private name, same as
    # _enumerate_outputs already reaches for — without this fallback the output
    # contract was empty for every DynamicDash app, pushing an agent right back
    # into discovering outputs by running the app (#160).
    components = list(
        getattr(fd, "outputs_with_ids", None)
        or getattr(fd, "_outputs_with_ids", None)
        or []
    )
    anns = []
    # Only consult the annotation when the outputs were built *from* it. An
    # explicit `outputs=[Graph]` wins over a `-> str` hint, and the contract has
    # to describe the figure that is really rendered.
    if getattr(fd, "_outputs_inferred", True):
        try:
            import typing
            ret = typing.get_type_hints(fd.callback_fn).get("return")
        except Exception:
            ret = inspect.signature(fd.callback_fn).return_annotation
        if ret is not None and ret is not inspect.Signature.empty:
            anns = expand_return_annotation(ret)

    outputs = []
    for i, comp in enumerate(components):
        tag, jtype = _output_kind(comp)
        # A scalar annotation is more specific than the component (an int and a
        # string both render as text) — prefer it when it maps to a JSON type.
        if i < len(anns) and anns[i] in (str, int, float, bool, list, dict):
            jtype = _json_type_name(anns[i])
        cid = _stringify_id(comp.id)
        entry = {"id": cid, "tag": tag, "type": jtype}
        # label_ is the label the UI actually renders: _infer_output_components
        # normalizes a wrong-length output_labels list to OUTPUT_1/OUTPUT_2 and
        # stamps it on the component, while fd.output_labels keeps the original.
        label = getattr(comp, "label_", None)
        if label:
            entry["label"] = label
        if state is not None and cid in state.outputs:
            entry["current_value"] = _summarize_for_history(state.outputs[cid])
        outputs.append(entry)
    return outputs


def _option_error(fd, component_id, value, snapshot, state=None):
    """Reject a value the UI could never produce, else None.

    Validates against the very contract ``describe_app`` reports (parity), so an
    agent can never set a value the UI widget couldn't: a value outside a
    dropdown's ``options`` (issue #116), of the wrong JSON ``type`` (issue
    #150), or outside a Slider's ``min``/``max`` bounds (issue #120). The
    contract comes from :func:`_input_contract`, so a DynamicDash form an agent
    built with ``set_form`` is validated against *its own* declared options and
    bounds rather than skipped (issue #144). Permissive by design: an input with
    no advertised options, type or bounds accepts any value, and ``None`` always
    clears a selection. For a MultiSelect (list value) every element must be a
    legal key.
    """
    for entry in _input_contract(fd, snapshot, state):
        if entry["id"] != component_id:
            continue
        if value is None:
            return None
        options = entry.get("options")
        if options:
            if isinstance(value, (list, tuple)):
                bad = [v for v in value if v not in options]
                if bad:
                    return f"value(s) {bad} not in allowed options {options}"
                return None
            if value not in options:
                return f"value {value!r} not in allowed options {options}"
            return None
        bad_type = _type_error(entry, value)
        if bad_type:
            return bad_type
        # Numeric Slider bounds (no options): reject out-of-range, like the UI.
        props = entry.get("props") or {}
        lo, hi = props.get("min"), props.get("max")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if lo is not None and value < lo:
                return f"value {value} is below the minimum {lo}"
            if hi is not None and value > hi:
                return f"value {value} is above the maximum {hi}"
        return None
    return None


# --------------------------------------------------------------------------- #
# Native MCP mount + fast_dash tool registration
# --------------------------------------------------------------------------- #

def _structured_errors(fn):
    """Keep a drive tool's error contract structured, even on a malformed call.

    A missing required argument raises ``TypeError`` *when Python calls the
    function* -- before its body runs -- so the tool's own ``try/except`` can
    never catch it, and the raw exception (which spells out the internal
    ``enable_mcp.<locals>.<tool>`` qualname) reaches the agent instead of the
    ``{"ok": false, "error": ...}`` shape every other error path on these tools
    returns. Bind the arguments here instead and report a missing or unexpected
    one in the contract's own shape.

    ``functools.wraps`` keeps the wrapped signature, so Dash still derives the
    same MCP input schema -- the arguments stay *required* in the schema; they
    just fail in the contract's shape rather than as a traceback. (issue #165)
    """
    sig = inspect.signature(fn)
    required = [
        p.name for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    ]

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            sig.bind(*args, **kwargs)
        except TypeError as e:
            return {
                "ok": False,
                "error": f"{fn.__name__}() {e}",
                "required_arguments": required,
            }
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - never leak a traceback over /mcp
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    return wrapper


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


# --------------------------------------------------------------------------- #
# Chat-mode MCP contract (RFC #133 Phase 3)
# --------------------------------------------------------------------------- #

# A dedicated, stable headless session id so an agent's turns share thread /
# history state across invoke() calls without colliding with a browser session.
_MCP_CHAT_SID = "__mcp_chat__"


def _describe_chat_settings(fd) -> list[dict]:
    """Sidebar-setting contract for a chat app (empty when there are none).

    Reuses the static-input describer, then adds the callback parameter ``name``
    an agent passes to ``invoke(settings=...)`` (the ``id`` is the component id,
    e.g. ``input_temperature``; the ``name`` is ``temperature``).
    """
    if not getattr(fd, "inputs_with_ids", None):
        return []
    settings = _describe_static_inputs(fd, dict(fd._mcp_state.inputs))
    for entry in settings:
        entry["name"] = _param_name_from_id(entry["id"])
    return settings


def _register_chat_mcp_tools(fd, mcp_enabled) -> None:
    """Register the chat-app MCP tools: ``describe_app`` + headless ``invoke``."""
    from fast_dash.chat import run_turn, wire_safe
    from fast_dash.utils import _jsonify_for_mcp

    @mcp_enabled(name="describe_app", expose_docstring=True)
    @_structured_errors
    def describe_app() -> dict:
        """Describe this chat app's contract for a headless agent.

        Reports the composer (the required ``query`` string an agent sends) and
        any sidebar ``settings``. Drive the app with ``invoke(query=...)``.
        """
        return {
            "title": getattr(fd, "title", None) or "",
            "doc": (getattr(fd.callback_fn, "__doc__", "") or "").strip(),
            "mode": "chat",
            "composer": {"query": {"type": "string", "required": True}},
            "settings": _describe_chat_settings(fd),
        }

    @mcp_enabled(name="invoke", expose_docstring=True)
    @_structured_errors
    def invoke(query: str, settings: dict = None) -> dict:
        """Run one chat turn headlessly and return its frames (JSON-safe).

        ``query`` is the composer text. ``settings`` optionally sets sidebar
        values (keyed by parameter ``name`` from ``describe_app``).
        History and thread state advance across calls.
        """
        if not isinstance(query, str) or not query.strip():
            return {"ok": False, "error": "query must be a non-empty string"}

        settings = settings or {}
        known = set(getattr(fd, "_chat_setting_names", []) or [])
        unknown = sorted(k for k in settings if k not in known)
        if unknown:
            return {
                "ok": False,
                "error": f"unknown setting(s): {unknown}",
                "known_settings": sorted(known),
            }

        frames = []

        def _emit(f):
            frames.append(f)

        history = fd.chat_history.get(_MCP_CHAT_SID)
        try:
            result = run_turn(
                fd.callback_fn, query.strip(),
                history=history, settings=settings, emit=_emit,
                friendly_error=lambda m: m, thread_id=_MCP_CHAT_SID,
            )
        except Exception as e:                     # defensive: never crash /mcp
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        fd.chat_history.append_turn(_MCP_CHAT_SID, query.strip(), result["content"])
        safe_frames = [_jsonify_for_mcp(wire_safe(f)) for f in frames]
        return {"ok": True, "content": result["content"], "frames": safe_frames}


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

    # Chat apps speak a different contract: a composer (query) + a headless
    # invoke that drives one turn and returns its frames. Register those instead
    # of the input-mirror tools, then mount and return.
    if getattr(fd, "is_chat", False):
        _register_chat_mcp_tools(fd, mcp_enabled)
        enable_mcp_server(fd.app, mcp_path)
        if getattr(fd, "_backend", None):
            _install_asgi_mcp_request_context(fd.app.server, mcp_path)
        return

    # ----- fast_dash value-add tools (stateful: drive the live app) --------- #

    def _contract_index(snapshot):
        """{id: entry} for whichever contract this app has (static or set_form).

        Keying the guards off this instead of ``_enumerate_inputs`` is what lets
        a DynamicDash form -- which has no static inputs at all -- be validated
        against the specs the agent itself declared (#144).
        """
        return {e["id"]: e for e in _input_contract(fd, snapshot, state)}

    def _echo(entries, cid, value):
        """The value to report back: masked for a PasswordInput (#151)."""
        return _jsonify_for_mcp(_redact(entries.get(cid) or {}, value))

    @mcp_enabled(name="set_input", expose_docstring=True)
    @_structured_errors
    def set_input(component_id: str, value: Any) -> dict:
        """Update one input's value, server-side and live in the browser.

        Browser update lands within ~500ms (Dash ``Interval`` drain).
        """
        snapshot = dict(state.inputs)
        entries = _contract_index(snapshot)
        if entries and component_id not in entries:
            return {
                "ok": False,
                "error": f"Unknown input id {component_id!r}",
                "known_ids": sorted(entries),
            }
        bad = _option_error(fd, component_id, value, snapshot, state)
        if bad:
            return {"ok": False, "error": bad, "id": component_id}
        state.inputs[component_id] = value
        state.pending_inputs[component_id] = value
        return {"ok": True, "id": component_id, "value": _echo(entries, component_id, value)}

    @mcp_enabled(name="set_inputs", expose_docstring=True)
    @_structured_errors
    def set_inputs(inputs: dict) -> dict:
        """Bulk-update multiple input values (keyed by parameter name).

        The argument is named ``inputs`` to match ``invoke(inputs=...)``.
        """
        snapshot = dict(state.inputs)
        entries = _contract_index(snapshot)
        applied, errors = {}, {}
        for k, v in (inputs or {}).items():
            if entries and k not in entries:
                errors[k] = "unknown id"
                continue
            bad = _option_error(fd, k, v, snapshot, state)
            if bad:
                errors[k] = bad
                continue
            state.inputs[k] = v
            state.pending_inputs[k] = v
            snapshot[k] = v
            applied[k] = _echo(entries, k, v)
        return {"ok": not errors, "applied": applied, "errors": errors}

    @mcp_enabled(name="invoke", expose_docstring=True)
    @_structured_errors
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
            snapshot = dict(state.inputs)
            entries = _contract_index(snapshot)
            if entries:
                unknown = sorted(k for k in inputs if k not in entries)
                if unknown:
                    return {
                        "ok": False,
                        "error": f"unknown input id(s): {unknown}",
                        "known_ids": sorted(entries),
                    }
            # Validate against advertised options before mutating (atomic: a
            # bad value rejects the whole call without touching the mirror).
            option_errors = {}
            for k, v in inputs.items():
                bad = _option_error(fd, k, v, snapshot, state)
                if bad:
                    option_errors[k] = bad
                else:
                    snapshot[k] = v
            if option_errors:
                return {"ok": False, "error": "invalid value(s)", "errors": option_errors}
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

        # Secrets go into the callback but never come back out — not in the
        # error echo, and not in the history a later get_invocation reads (#151).
        entries = _contract_index(snapshot)

        def _kwargs_summary():
            out = {}
            for k, v in kwargs.items():
                entry = entries.get(k) or entries.get(f"input_{k}") or {}
                out[k] = (
                    REDACTED
                    if entry.get("secret") and v not in (None, "")
                    else _summarize_for_history(v)
                )
            return out

        t0 = time.time()
        try:
            result = fd.callback_fn(**kwargs)
        except Exception as e:
            return {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "kwargs_summary": _kwargs_summary(),
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
            "kwargs": _kwargs_summary(),
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
    @_structured_errors
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
        # Keep a persistent copy so describe_app can report the form contract
        # (pending_specs is popped by the browser drain), and drop mirror values
        # for fields this form no longer has — the parent control survives, it
        # isn't part of the form.
        parent = getattr(fd, "parent_control", None) or {}
        state.set_current_specs(specs, keep={parent.get("name")} - {None})
        return {"ok": True, "count": len(specs)}

    @mcp_enabled(name="get_invocation", expose_docstring=True)
    @_structured_errors
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
    @_structured_errors
    def list_component_types() -> dict:
        """List the legal ``type`` values for a DynamicDash UI spec."""
        return {"types": _component_types()}

    @mcp_enabled(name="describe_app", expose_docstring=True)
    @_structured_errors
    def describe_app() -> dict:
        """Describe the app's inputs and outputs, plus their CURRENT values.

        This is the reliable way for a headless agent (no browser) to read the
        app's contract *and* its live state before calling ``invoke``: each
        input reports its parameter ``id``, JSON ``type``, ``default``, any
        allowed ``options`` (for dropdowns / ``Literal`` / ``Enum``), and its
        ``current_value`` — including values you set via ``set_input`` /
        ``set_inputs``. Each output reports its ``id``, the component ``tag`` it
        renders into, its JSON ``type`` and ``label``, so you can see what a run
        will produce without having to run it. (The native ``dash://components``
        resource lists ids and Dash *widget* types only, and
        ``get_dash_component`` reflects the browser, not the agent's mirror, so
        neither shows agent-set values headlessly.)
        """
        snapshot = dict(state.inputs)
        # The same contract the validators enforce — static signature, or the
        # form an agent built with set_form (#144).
        inputs = _input_contract(fd, snapshot, state)
        seen = {e["id"] for e in inputs}
        # Any extra mirror keys not in the contract (defensive; also the only
        # thing to report on a DynamicDash app with no form built yet). These
        # have no contract entry to carry a "secret" flag, so consult the
        # persistent secret list directly — a value that fell out of the contract
        # must not fall out of the mask with it.
        secrets = _secret_ids(fd, state)
        for k, v in snapshot.items():
            if k not in seen:
                entry = {"id": k, "secret": k in secrets}
                entry["current_value"] = _jsonify_for_mcp(_redact(entry, v))
                inputs.append(entry)

        return {
            "title": getattr(fd, "title", None) or "",
            "doc": (getattr(fd.callback_fn, "__doc__", "") or "").strip(),
            "inputs": inputs,
            # What a run produces — discoverable without side-effectingly
            # calling invoke() to find out (#152).
            "outputs": _describe_outputs(fd, state),
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
