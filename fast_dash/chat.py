"""Native chat mode for Fast Dash (RFC #133).

This module holds the *transport- and UI-independent* core of chat mode:

* the **frame grammar** (``_normalize_frame``) — the contract a chat callback
  speaks by ``yield``-ing ``str`` tokens or frame ``dict``s;
* a bounded, per-session, thread-safe **history store** (``ChatHistory``);
* the **turn runner** (``run_turn``) — drives a (sync or async) generator,
  normalizes and emits frames through a caller-supplied ``emit`` callable, and
  returns the assembled turn.

Everything here is plain Python with no Dash import, so it is unit-testable
without a browser. Wiring to ``DashSocketIO`` / ``set_props`` and the composer
UI lives in ``fast_dash.py`` / ``Components.py``.

Frame types:

    content    {"type": "content",   "content": str}
    reasoning  {"type": "reasoning", "content": str}
    tool_start {"type": "tool_start","name": str, "args": dict|str, "id"?: str}
    tool_end   {"type": "tool_end",  "name": str, "result": Any,   "id"?: str}
    artifact   {"type": "artifact",  "content": Figure|DataFrame|Image|str}
    extraction {"type": "extraction","tool_name": str, "extracted_type": str, "data": Any}
    interrupt  {"type": "interrupt", "action_requests": [...], "allowed_decisions": [...]}
    set_input  {"type": "set_input", "name": str, "value": Any}     (sidecar drive)
    run_app    {"type": "run_app"}                                   (sidecar drive)
    complete   {"type": "complete"}
    error      {"type": "error",     "message": str}

A bare ``str`` yield is sugar for a ``content`` frame. Unknown frame types are
warned-about and skipped (never crash). Error strings are ASCII (Windows
cp1252 consoles).
"""

import asyncio
import collections
import dataclasses
import inspect
import threading
import warnings
from typing import Any


@dataclasses.dataclass(frozen=True)
class ChatContext:
    """Per-turn context injected when a chat callback declares a ``ctx`` param.

    The 5-line chatbot never sees this: ``query`` (and ``history``) stay bare.
    Power features fold into one object instead of a growing list of magic
    parameter names:

    * ``thread_id`` -- the chat session id (a LangGraph checkpointer thread).
    * ``resume`` -- a decision answering a pending ``interrupt`` (HITL), else
      ``None``.
    * ``inputs`` -- the host app's live input values ``{name: value}`` when the
      agent runs as a **sidecar** on a normal Fast Dash app (empty otherwise);
      lets the assistant read what the user set on the dashboard.
    * ``input_specs`` -- the sidecar host app's input *contract* (a list of
      ``{id, type, options, props, ...}``), the same one an MCP agent sees. Pass
      it to :func:`app_tool_specs` for a typed ``set_input`` schema, or inline it
      in the system prompt.
    """

    thread_id: str = "default"
    resume: Any = None
    inputs: dict = dataclasses.field(default_factory=dict)
    input_specs: list = dataclasses.field(default_factory=list)

# Frame type constants -------------------------------------------------------
CONTENT = "content"
REASONING = "reasoning"
TOOL_START = "tool_start"
TOOL_END = "tool_end"
ARTIFACT = "artifact"
EXTRACTION = "extraction"  # langstage typed-object event (todos/reflection/...)
INTERRUPT = "interrupt"
CANVAS = "canvas"          # rebuild the output canvas from a UI-spec list
SET_PROPS = "set_props"    # patch one canvas component's props/value
SET_INPUT = "set_input"    # sidecar: set one host-app input value
RUN_APP = "run_app"        # sidecar: run the host app on its current inputs
SET_OUTPUT = "set_output"  # sidecar: render a value into one output slot
SET_LAYOUT = "set_layout"  # sidecar: re-mosaic the existing output slots
COMPLETE = "complete"
ERROR = "error"

# CANVAS / SET_PROPS were the 0.5.x chat-canvas frames. In 0.6.0 they are
# removed from the app grammar: an unrecognized frame type warns and is
# skipped (never crashes). The constants are kept so the LLM on-ramp helpers
# (canvas_tool_specs / apply_tool_call) still build these frame dicts for code
# that opts into the canvas explicitly.
_KNOWN_FRAME_TYPES = frozenset(
    {CONTENT, REASONING, TOOL_START, TOOL_END, ARTIFACT, EXTRACTION,
     INTERRUPT, SET_INPUT, RUN_APP, SET_OUTPUT, SET_LAYOUT, COMPLETE, ERROR}
)

# Frame types whose payload never crosses the socket raw (rendered server-side
# at turn completion, per RFC D2). The wire carries a lightweight placeholder.
_ARTIFACT_FRAME_TYPES = frozenset({ARTIFACT})


class ChatFrameError(ValueError):
    """A malformed chat frame (ASCII message, surfaced to the developer)."""


def _normalize_frame(frame):
    """Validate and normalize one yielded frame.

    Returns a JSON-*shaped* frame dict, or ``None`` if the frame should be
    skipped (unknown type / non-frame value). Raises :class:`ChatFrameError`
    for a malformed frame of a *known* type (a developer bug worth surfacing).

    Artifact payloads are NOT serialized here — the runner renders them at
    completion; on the wire an artifact frame is replaced by a placeholder.
    """
    # str is sugar for a content frame.
    if isinstance(frame, str):
        return {"type": CONTENT, "content": frame}

    if not isinstance(frame, dict):
        warnings.warn(
            "Chat callback yielded a %s; expected a str or a frame dict. "
            "Skipping." % type(frame).__name__,
            stacklevel=2,
        )
        return None

    ftype = frame.get("type")
    if ftype is None:
        raise ChatFrameError("A chat frame dict must have a 'type' key.")

    if ftype not in _KNOWN_FRAME_TYPES:
        warnings.warn("Unknown chat frame type %r; skipping." % (ftype,),
                      stacklevel=2)
        return None

    # Per-type required-key validation (friendly, ASCII).
    if ftype == CONTENT or ftype == REASONING:
        if "content" not in frame:
            raise ChatFrameError(
                "A %r frame must have a 'content' key." % ftype)
        frame = {"type": ftype, "content": _as_text(frame["content"])}
    elif ftype == TOOL_START:
        if "name" not in frame:
            raise ChatFrameError("A 'tool_start' frame must have a 'name' key.")
        frame = {
            "type": TOOL_START,
            "name": str(frame["name"]),
            "args": frame.get("args", {}),
            "id": str(frame.get("id", frame["name"])),
        }
    elif ftype == TOOL_END:
        if "name" not in frame:
            raise ChatFrameError("A 'tool_end' frame must have a 'name' key.")
        frame = {
            "type": TOOL_END,
            "name": str(frame["name"]),
            "result": frame.get("result"),
            "id": str(frame.get("id", frame["name"])),
        }
    elif ftype == ARTIFACT:
        if "content" not in frame:
            raise ChatFrameError("An 'artifact' frame must have a 'content' key.")
        # Keep the raw payload on the object for server-side rendering; it is
        # replaced by a placeholder before hitting the wire (see wire_safe).
        frame = {"type": ARTIFACT, "content": frame["content"]}
    elif ftype == EXTRACTION:
        # A langstage typed-object event: {tool_name, extracted_type, data}.
        # Both string keys are required; data is coerced JSON-safe so nothing a
        # custom extractor returns can crash the socket (RFC principle 7).
        if "extracted_type" not in frame:
            raise ChatFrameError(
                "An 'extraction' frame must have an 'extracted_type' key.")
        frame = {
            "type": EXTRACTION,
            "tool_name": str(frame.get("tool_name", "")),
            "extracted_type": str(frame["extracted_type"]),
            "data": _json_safe_data(frame.get("data")),
        }
    elif ftype == INTERRUPT:
        frame = {
            "type": INTERRUPT,
            "action_requests": frame.get("action_requests", []),
            "review_configs": frame.get("review_configs", []),
            "allowed_decisions": frame.get("allowed_decisions", []),
        }
    elif ftype == SET_INPUT:
        if "name" not in frame:
            raise ChatFrameError("A 'set_input' frame must have a 'name' key.")
        frame = {"type": SET_INPUT, "name": str(frame["name"]),
                 "value": frame.get("value")}
    elif ftype == RUN_APP:
        frame = {"type": RUN_APP}
    elif ftype == SET_OUTPUT:
        if "slot" not in frame:
            raise ChatFrameError("A 'set_output' frame must have a 'slot' key.")
        # The value may be a rich object (figure / DataFrame); it is transformed
        # server-side by the same pipeline the Run button uses, so keep it raw.
        frame = {"type": SET_OUTPUT, "slot": str(frame["slot"]),
                 "value": frame.get("value")}
    elif ftype == SET_LAYOUT:
        if "mosaic" not in frame:
            raise ChatFrameError("A 'set_layout' frame must have a 'mosaic' key.")
        frame = {"type": SET_LAYOUT, "mosaic": str(frame["mosaic"])}
    elif ftype == ERROR:
        frame = {"type": ERROR, "message": _as_text(frame.get("message", ""))}
    elif ftype == COMPLETE:
        frame = {"type": COMPLETE}

    return frame


def _as_text(value):
    """Coerce a content payload to text without leaking a non-ASCII repr."""
    return value if isinstance(value, str) else str(value)


def _json_safe_data(value):
    """Return a JSON-serializable form of an extraction payload.

    Extraction ``data`` crosses the socket raw (unlike an artifact, it is plain
    structured data, not a live figure). The built-in extractors already return
    JSON (lists / dicts / strings); this guards a *custom* extractor that returns
    something exotic so a typed event never crashes the transport.
    """
    import json as _json
    try:
        _json.dumps(value)
        return value
    except (TypeError, ValueError):
        return _json.loads(_json.dumps(value, default=str))


def wire_safe(frame):
    """Return a JSON-safe copy of a normalized frame for socket transport.

    Artifact frames carry rich Python objects (figures, dataframes) that are
    rendered server-side at completion; on the wire they become a placeholder
    so nothing non-serializable ever crosses the socket (RFC principle 7).
    """
    if frame.get("type") in _ARTIFACT_FRAME_TYPES:
        return {"type": ARTIFACT, "pending": True}
    return frame


# --------------------------------------------------------------------------- #
# LLM on-ramp for the canvas
# --------------------------------------------------------------------------- #

def canvas_tool_specs():
    """Provider-neutral JSON-Schema tool defs for driving the canvas with an LLM.

    Returns two tools -- ``build_canvas`` and ``set_canvas_props`` -- in the
    ``{name, description, input_schema}`` shape (the inner ``input_schema`` is
    standard JSON Schema, portable to any provider). Hand them to your LLM's
    ``tools=`` argument; pass each returned tool call to :func:`apply_tool_call`
    to get a frame to ``yield``. No LLM SDK is imported or required.
    """
    from .dynamic import CANVAS_COMPONENT_REGISTRY
    spec_item = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Unique component id."},
            "type": {"type": "string", "enum": sorted(CANVAS_COMPONENT_REGISTRY)},
            "value": {"description": "Initial value (type depends on component)."},
            "label": {"type": "string"},
            "props": {"type": "object", "description": "Extra component props."},
            "span": {"type": "integer", "minimum": 1, "maximum": 12,
                     "description": ("Grid width out of 12 for arrangement "
                                     "(default 12 = full-width row; 6 = half, "
                                     "so two span-6 items sit side by side).")},
        },
        "required": ["name", "type"],
    }
    return [
        {
            "name": "build_canvas",
            "description": ("Build or replace the output canvas from a list of "
                            "UI-spec components (inputs, charts, tables, text)."),
            "input_schema": {
                "type": "object",
                "properties": {"specs": {"type": "array", "items": spec_item}},
                "required": ["specs"],
            },
        },
        {
            "name": "set_canvas_props",
            "description": ("Patch one canvas component's properties in place "
                            "(e.g. widen a slider's range, change a value)."),
            "input_schema": {
                "type": "object",
                "properties": {
                    "target": {"type": "string",
                               "description": "The component name to patch."},
                    "props": {"type": "object"},
                },
                "required": ["target", "props"],
            },
        },
    ]


def app_tool_specs(inputs=None):
    """Provider-neutral tool defs for a chat **sidecar** to drive its host app.

    Two tools -- ``set_input`` (set one of the app's inputs) and ``run_app``
    (run the app on its current inputs and update its outputs) -- in the same
    ``{name, description, input_schema}`` shape as :func:`canvas_tool_specs`.

    ``inputs`` may be a list of input *names* (``ctx.inputs`` keys) or, better,
    the host app's input *contract* (``ctx.input_specs`` -- a list of
    ``{id, type, options, props}`` dicts). Given the contract, the ``set_input``
    schema enumerates the valid targets and describes each one's type, allowed
    options, and numeric bounds, so the model sends valid values on the first
    try. :func:`apply_tool_call` maps a returned call to a ``set_input`` /
    ``run_app`` frame. No LLM SDK is imported.
    """
    names, lines = [], []
    for it in (inputs or []):
        if isinstance(it, str):
            names.append(it)
            continue
        if not isinstance(it, dict):
            continue
        name = it.get("id") or it.get("name")
        if not name:
            continue
        names.append(name)
        desc = "%s: %s" % (name, it.get("type") or "value")
        options = it.get("options")
        if options:
            desc += " (one of: %s)" % ", ".join(str(o) for o in options)
        bounds = it.get("props") or {}
        if "min" in bounds or "max" in bounds:
            desc += " (range %s..%s)" % (bounds.get("min"), bounds.get("max"))
        lines.append(desc)

    name_schema = {"type": "string", "description": "The input name to set."}
    if lines:
        name_schema["description"] += " Inputs -> " + "; ".join(lines) + "."
    if names:
        name_schema["enum"] = names
    return [
        {
            "name": "set_input",
            "description": ("Set one of the app's inputs to a new value "
                            "(reflected in the live control)."),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": name_schema,
                    "value": {"description": "New value for the input."},
                },
                "required": ["name", "value"],
            },
        },
        {
            "name": "run_app",
            "description": ("Run the app on its current inputs and refresh its "
                            "outputs (like clicking Run)."),
            "input_schema": {"type": "object", "properties": {}},
        },
    ]


def _tool_call_parts(tool_call):
    """Extract ``(name, args_dict)`` from an LLM tool call (dict or SDK object)."""
    import json as _json

    def _coerce(a):
        if isinstance(a, str):
            try:
                return _json.loads(a)
            except (ValueError, TypeError):
                return {}
        return a or {}

    if isinstance(tool_call, dict):
        fn = tool_call.get("function") or {}
        name = tool_call.get("name") or fn.get("name")
        args = tool_call.get("input")
        if args is None:
            args = tool_call.get("arguments", fn.get("arguments"))
        return name, _coerce(args)
    # Object form (e.g. an Anthropic ToolUseBlock: .name / .input).
    return getattr(tool_call, "name", None), _coerce(getattr(tool_call, "input", None))


def apply_tool_call(tool_call):
    """Map an LLM tool call to a chat frame.

    Handles the canvas tools (``build_canvas`` / ``set_canvas_props``) and the
    sidecar app-drive tools (``set_input`` / ``run_app``). Accepts a provider
    tool-call dict (``{name, input}`` / ``{name, arguments}`` / OpenAI
    ``{function: {...}}``) or an SDK object with ``.name``/``.input``. Returns
    the matching frame to ``yield``, or ``None`` for an unrecognized tool (so a
    mixed tool loop can skip it).
    """
    name, args = _tool_call_parts(tool_call)
    if name == "build_canvas":
        return {"type": CANVAS, "specs": args.get("specs", [])}
    if name == "set_canvas_props":
        return {"type": SET_PROPS, "target": args.get("target"),
                "props": args.get("props", {})}
    if name == "set_input":
        return {"type": SET_INPUT, "name": args.get("name"),
                "value": args.get("value")}
    if name == "run_app":
        return {"type": RUN_APP}
    return None


# --------------------------------------------------------------------------- #
# History store
# --------------------------------------------------------------------------- #

class ChatHistory:
    """Bounded, per-session, thread-safe conversation history.

    Keyed by an opaque session id (a browser-session UUID in the UI). Stores a
    flat list of ``{"role": "user"|"assistant", "content": str}`` messages,
    bounded to ``size`` *turn pairs* (``2 * size`` messages). Only the turn
    runner writes; reads snapshot under the same per-session lock.
    """

    def __init__(self, size=50):
        self._size = max(1, int(size))
        self._store = {}          # sid -> collections.deque
        self._locks = {}          # sid -> threading.Lock
        self._registry_lock = threading.Lock()

    def _lock_for(self, sid):
        with self._registry_lock:
            lock = self._locks.get(sid)
            if lock is None:
                lock = self._locks[sid] = threading.Lock()
            return lock

    def get(self, sid):
        """Snapshot the message list for ``sid`` (list of role/content dicts)."""
        with self._lock_for(sid):
            dq = self._store.get(sid)
            return [dict(m) for m in dq] if dq else []

    def append_turn(self, sid, user_text, assistant_text):
        """Append a user+assistant message pair for ``sid``."""
        with self._lock_for(sid):
            dq = self._store.get(sid)
            if dq is None:
                dq = self._store[sid] = collections.deque(maxlen=2 * self._size)
            dq.append({"role": "user", "content": _as_text(user_text)})
            dq.append({"role": "assistant", "content": _as_text(assistant_text)})

    def clear(self, sid):
        with self._lock_for(sid):
            self._store.pop(sid, None)
        # Drop the per-sid lock too, so evicting sessions doesn't leave a
        # slowly-growing lock registry on a long-running server.
        with self._registry_lock:
            self._locks.pop(sid, None)
        # Free any run_python exec state keyed by this session (the run_python
        # thread_id IS the chat session id). Guarded/lazy: the [agent] extra may
        # be absent, and this module must stay heavy-import-free at the top.
        try:
            from .agent_tools import clear_python_state
            clear_python_state(sid)
        except Exception:                                 # noqa: BLE001
            pass                                          # best-effort cleanup


@dataclasses.dataclass
class ChatSession:
    """Per-session chat state — one object per browser session.

    Consolidates what were five parallel per-sid dicts. All access goes through
    the app's single sessions lock; ``last_seen`` drives idle eviction so a
    long-running server doesn't accumulate dead sessions.
    """

    active: bool = False              # a turn is streaming (one-in-flight guard)
    cancel: bool = False              # Stop pressed (observed across threads)
    pending: Any = None               # HITL: paused turn awaiting a decision
    msgs: list = dataclasses.field(default_factory=list)          # ASGI transcript
    canvas_specs: list = dataclasses.field(default_factory=list)  # canvas UI specs
    # Last-known transformed output values (per output slot), so a set_layout
    # re-mosaic preserves surviving slots' contents instead of reverting them to
    # the build-time defaults (Bug 3). Populated on manual Run, run_app, and
    # set_output; consumed when rebuilding the pushed layout tree.
    output_mirror: dict = dataclasses.field(default_factory=dict)
    last_seen: float = 0.0


# --------------------------------------------------------------------------- #
# Turn runner
# --------------------------------------------------------------------------- #

def wants_history(callback_fn):
    """True if the callback declares a ``history`` parameter (case-sensitive)."""
    return _declares(callback_fn, "history")


def _declares(callback_fn, name):
    try:
        return name in inspect.signature(callback_fn).parameters
    except (TypeError, ValueError):
        return False


def _drive(gen):
    """Yield items from a sync or async generator uniformly.

    Async generators are driven on a private event loop so the runner stays a
    plain blocking call (safe inside a Flask/socketio request thread).
    """
    if hasattr(gen, "__anext__"):          # async generator
        loop = asyncio.new_event_loop()
        try:
            while True:
                try:
                    yield loop.run_until_complete(gen.__anext__())
                except StopAsyncIteration:
                    break
        finally:
            try:
                loop.run_until_complete(gen.aclose())
            except Exception:
                pass
            loop.close()
    else:                                   # sync generator (or iterable)
        yield from gen


def blocks_text(blocks):
    """Concatenated text content of a turn's blocks (what history stores)."""
    return "".join(b["text"] for b in (blocks or []) if b.get("kind") == "text")


def has_text(blocks):
    """True if any text block carries content (used for spacing)."""
    return any(b.get("kind") == "text" and b.get("text") for b in (blocks or []))


def run_turn(callback_fn, query, *, history=None, settings=None, emit=None,
             friendly_error=None, cancelled=None, thread_id=None, resume=None,
             app_inputs=None, app_input_specs=None):
    """Run one chat turn.

    Drives ``callback_fn`` (a generator function, or a function returning a
    ``str``/generator), normalizing each yielded frame and pushing it through
    ``emit`` (a ``callable(frame_dict)`` supplied by the transport layer).
    Returns the assembled turn::

        {"content": <full assistant text>, "frames": [<normalized frames>]}

    Robustness contract:
      * a bare ``str`` yield is a content frame;
      * unknown frame types warn and are skipped;
      * an exception mid-stream is caught, converted to an ``error`` frame
        (via ``friendly_error`` if given), and the partial content is kept;
      * the generator is always closed in a ``finally``;
      * a ``complete`` frame is emitted exactly once at the end.
    """
    settings = settings or {}
    emit = emit or (lambda frame: None)

    kwargs = dict(settings)
    if wants_history(callback_fn):
        kwargs["history"] = list(history or [])
    if _declares(callback_fn, "ctx"):
        # Power features fold into one context object instead of separate magic
        # params (thread_id / resume / inputs).
        kwargs["ctx"] = ChatContext(
            thread_id=thread_id or "default",
            resume=resume,
            inputs=dict(app_inputs or {}),
            input_specs=list(app_input_specs or []),
        )

    parts = []       # accumulated assistant text (content frames)
    frames = []      # all normalized frames (content/tool/artifact/...)

    def _handle(raw):
        norm = _normalize_frame(raw)
        if norm is None:
            return
        if norm["type"] == COMPLETE:
            return          # completion is emitted once by the runner itself
        if norm["type"] == CONTENT:
            parts.append(norm["content"])
        frames.append(norm)
        emit(norm)

    gen = None
    try:
        result = callback_fn(query, **kwargs)

        if isinstance(result, str):
            _handle(result)                          # non-streaming str return
        elif result is None:
            pass
        elif hasattr(result, "__iter__") or hasattr(result, "__aiter__"):
            gen = result
            for raw in _drive(gen):
                if cancelled is not None and cancelled():
                    break                                # user hit Stop (D4)
                _handle(raw)
        else:
            # A non-str, non-iterable return: coerce to text (best-effort).
            _handle(_as_text(result))
    except ChatFrameError:
        raise                                        # developer bug: surface it
    except Exception as exc:                          # noqa: BLE001 (intentional)
        msg = friendly_error(str(exc)) if friendly_error else str(exc)
        err = {"type": ERROR, "message": _as_text(msg)}
        frames.append(err)
        emit(err)
    finally:
        if gen is not None and hasattr(gen, "close"):
            try:
                gen.close()
            except Exception:
                pass

    emit({"type": COMPLETE})
    # A turn that ends on an interrupt frame is *paused*, awaiting a decision
    # (HITL, Phase 4); surface it so the caller can hold the turn open.
    interrupt = frames[-1] if frames and frames[-1].get("type") == INTERRUPT else None
    return {"content": "".join(parts), "frames": frames, "interrupt": interrupt}
