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

Frame types (Phase 1 handles content/complete/error; the rest are validated and
carried for later phases):

    content    {"type": "content",   "content": str}
    reasoning  {"type": "reasoning", "content": str}
    tool_start {"type": "tool_start","name": str, "args": dict|str, "id"?: str}
    tool_end   {"type": "tool_end",  "name": str, "result": Any,   "id"?: str}
    artifact   {"type": "artifact",  "content": Figure|DataFrame|Image|str}
    interrupt  {"type": "interrupt", "action_requests": [...], "allowed_decisions": [...]}
    extraction {"type": "extraction","content": Any}
    complete   {"type": "complete"}
    error      {"type": "error",     "message": str}

A bare ``str`` yield is sugar for a ``content`` frame. Unknown frame types are
warned-about and skipped (never crash). Error strings are ASCII (Windows
cp1252 consoles).
"""

import asyncio
import collections
import inspect
import threading
import warnings

# Frame type constants -------------------------------------------------------
CONTENT = "content"
REASONING = "reasoning"
TOOL_START = "tool_start"
TOOL_END = "tool_end"
ARTIFACT = "artifact"
INTERRUPT = "interrupt"
EXTRACTION = "extraction"
CANVAS = "canvas"          # rebuild the output canvas from a UI-spec list
SET_PROPS = "set_props"    # patch one canvas component's props/value
COMPLETE = "complete"
ERROR = "error"

_KNOWN_FRAME_TYPES = frozenset(
    {CONTENT, REASONING, TOOL_START, TOOL_END, ARTIFACT,
     INTERRUPT, EXTRACTION, CANVAS, SET_PROPS, COMPLETE, ERROR}
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
    elif ftype == INTERRUPT:
        frame = {
            "type": INTERRUPT,
            "action_requests": frame.get("action_requests", []),
            "review_configs": frame.get("review_configs", []),
            "allowed_decisions": frame.get("allowed_decisions", []),
        }
    elif ftype == EXTRACTION:
        frame = {"type": EXTRACTION, "content": frame.get("content")}
    elif ftype == CANVAS:
        specs = frame.get("specs")
        if not isinstance(specs, (list, tuple)):
            raise ChatFrameError(
                "A 'canvas' frame must have a 'specs' list of UI-spec dicts.")
        frame = {"type": CANVAS, "specs": list(specs)}
    elif ftype == SET_PROPS:
        if "target" not in frame:
            raise ChatFrameError("A 'set_props' frame must have a 'target' key.")
        props = frame.get("props", {})
        if not isinstance(props, dict):
            raise ChatFrameError("A 'set_props' frame's 'props' must be a dict.")
        frame = {"type": SET_PROPS, "target": str(frame["target"]), "props": dict(props)}
    elif ftype == ERROR:
        frame = {"type": ERROR, "message": _as_text(frame.get("message", ""))}
    elif ftype == COMPLETE:
        frame = {"type": COMPLETE}

    return frame


def _as_text(value):
    """Coerce a content payload to text without leaking a non-ASCII repr."""
    return value if isinstance(value, str) else str(value)


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


# --------------------------------------------------------------------------- #
# Turn runner
# --------------------------------------------------------------------------- #

def wants_history(callback_fn):
    """True if the callback declares a ``history`` parameter (case-sensitive)."""
    return _declares(callback_fn, "history")


def wants_thread_id(callback_fn):
    """True if the callback declares a ``thread_id`` parameter (case-sensitive).

    A ``thread_id`` param receives the chat session id (the langstage adapter
    uses it as the checkpointer thread; any callback may opt in the same way).
    """
    return _declares(callback_fn, "thread_id")


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
             canvas=None):
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
    if wants_thread_id(callback_fn):
        kwargs["thread_id"] = thread_id
    if _declares(callback_fn, "resume"):
        kwargs["resume"] = resume
    if _declares(callback_fn, "canvas"):
        kwargs["canvas"] = dict(canvas or {})

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
