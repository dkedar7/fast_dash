"""The chat-agent toolkit: tools an LLM uses to read and drive a Fast Dash app.

This module is imported at package import time (its buffer functions are called
by the sidecar turn loop), so it keeps **no heavy imports at module top** --
langchain / langgraph are imported *inside* the functions that need them, each
raising a friendly ASCII ``ImportError`` pointing at ``pip install
"fast-dash[agent]"`` when the extra is missing.

Contents
--------

* A per-turn **frame buffer** (``emit_frame`` / ``drain_frames`` /
  ``turn_buffer``). Tools push frames onto a ``contextvars.ContextVar`` list;
  the sidecar turn loop drains them after each agent step and streams them to
  the browser. A ContextVar (not a threading.local) is used deliberately: it
  propagates into the async tasks langgraph spawns to run tools, so a tool
  running inside the graph's executor still writes to the turn that started it.

* ``agent_toolkit(app)`` -- the list of langchain ``@tool`` functions, bound to
  one app via closures and trimmed to the app's ``chat_tools`` allowlist.

* ``app_prompt(app)`` -- the system-prompt text describing the app + tools.

* ``FastDashMiddleware(app)`` and ``build_auto_agent(app, model)`` -- the two
  ways to wire the toolkit into a langchain / langgraph agent.

Every string a tool returns is meant for the model to read (it steers the next
turn), so the returns are short, plain, ASCII acknowledgements or errors.
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import Any

from .agent_tools_config import RunPython

# --------------------------------------------------------------------------- #
# Per-turn frame buffer
# --------------------------------------------------------------------------- #

# The list a tool's ``emit_frame`` appends to. Set fresh per turn by the sidecar
# loop via ``turn_buffer()``; unset outside a turn (drain returns an empty list
# and never raises, so a stray tool call off-turn is a silent no-op).
_FRAME_BUFFER: contextvars.ContextVar[list] = contextvars.ContextVar(
    "fast_dash_frame_buffer", default=None
)

# The per-turn app-input state the drive tools share: ``set_input`` writes staged
# values here, ``run_app`` reads them to run the callback. Seeded by the sidecar
# turn loop with the *same* dict object the turn uses to dispatch frames (via
# ``turn_buffer``), so a tool mutating it in place is seen both by ``run_app``
# (same graph, another task) and by the frame drain -- the exact cross-task
# sharing that already makes ``_FRAME_BUFFER`` work.
_DRIVE_INPUTS: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "fast_dash_drive_inputs", default=None
)


def current_drive_inputs():
    """The mutable per-turn app-input dict, or None outside a seeded turn."""
    return _DRIVE_INPUTS.get()


def emit_frame(frame: dict) -> None:
    """Append ``frame`` to the current turn's buffer (no-op if none is active).

    Thread/async note: the buffer is a ContextVar, which copies into the tasks
    langgraph spawns to run tools, so a tool executing inside the graph still
    targets the turn that opened the buffer. If some executor runs a tool in a
    thread that did *not* inherit the context (rare), the frame is dropped
    rather than raising -- the tool's return still reaches the model.
    """
    buf = _FRAME_BUFFER.get()
    if buf is not None:
        buf.append(frame)


def drain_frames() -> list[dict]:
    """Return the buffered frames and clear the buffer (never raises).

    Returns an empty list when no turn buffer is active. The sidecar loop calls
    this after each agent step to stream whatever the tools emitted.
    """
    buf = _FRAME_BUFFER.get()
    if not buf:
        return []
    drained, buf[:] = list(buf), []
    return drained


@contextlib.contextmanager
def turn_buffer(drive_inputs=None):
    """Open a fresh frame buffer for one turn; clear it on exit.

    The sidecar turn loop wraps a turn in this so ``emit_frame`` calls made by
    tools during the turn accumulate in an isolated list, and nothing leaks into
    the next turn. ``drive_inputs`` (the turn's own app-input dict) is published
    for the drive tools to read/write in place; pass the SAME object the turn
    dispatches frames against so ``set_input`` and ``run_app`` stay in lockstep
    with it.
    """
    frame_token = _FRAME_BUFFER.set([])
    # None (the bare turn_buffer() unit-test / off-turn case) means "not a drive
    # turn" -- run_app then keeps its fire-and-forget behavior. A real sidecar
    # turn always passes a dict (even {} for an input-less app), enabling the
    # run-in-tool path that reports the result.
    drive_token = _DRIVE_INPUTS.set(drive_inputs)
    try:
        yield
    finally:
        # Clear the list (defensive; drop the reference regardless of drains).
        buf = _FRAME_BUFFER.get()
        if buf is not None:
            buf[:] = []
        _FRAME_BUFFER.reset(frame_token)
        _DRIVE_INPUTS.reset(drive_token)


# --------------------------------------------------------------------------- #
# run_python execution state (per langgraph thread)
# --------------------------------------------------------------------------- #

# ``run_python`` keeps a persistent namespace per conversation so variables set
# in one call are visible in the next -- keyed by the langgraph ``thread_id``
# (the chat session id). ``_LAST_RESULT`` stashes the last rich object a run
# produced (a Figure / DataFrame) so ``push_result`` can send it to an output
# slot without the object ever crossing the model's string-only tool API.
_PY_NAMESPACES: dict[str, dict] = {}
_LAST_RESULT: dict[str, Any] = {}


def clear_python_state(thread_id: str) -> None:
    """Drop the persistent run_python namespace + stashed result for a thread.

    Called when a chat session's history is cleared or the session is evicted
    (the run_python thread_id IS the chat session id), so a long-running server
    doesn't accumulate per-session exec namespaces (which can hold large frames
    / figures) after the conversation they belonged to is gone. Never raises for
    an unknown thread_id -- it is a plain best-effort cleanup.
    """
    _PY_NAMESPACES.pop(thread_id, None)
    _LAST_RESULT.pop(thread_id, None)


def _thread_id_from_config(config) -> str:
    """The langgraph thread id carried on a tool's RunnableConfig, or a default.

    ``@tool`` functions may declare a ``config: RunnableConfig`` parameter;
    langgraph injects the running config, whose ``configurable.thread_id`` is the
    chat session id. Falls back to a shared key when absent (e.g. a direct unit
    call), which is fine -- namespaces are only ever process-local scratch.
    """
    try:
        return (config or {}).get("configurable", {}).get("thread_id") or "__default__"
    except Exception:
        return "__default__"


def _exec_python(code: str, thread_id: str) -> dict:
    """Run ``code`` in the app process against the thread's persistent namespace.

    Returns ``{"stdout", "result", "figure", "table", "error"}`` -- the same
    shape as ``sandbox.run_code`` -- but here ``figure`` / ``table`` hold the
    *live* rich objects (a plotly Figure / a DataFrame), not JSON, because the
    result stays server-side (stashed for ``push_result``). Uses the notebook
    last-expression capture ported from DataChat's runner.
    """
    import ast
    import io
    import traceback
    from contextlib import redirect_stdout

    ns = _PY_NAMESPACES.setdefault(thread_id, {"__name__": "__fd_exec__"})
    # Convenience globals, imported lazily (missing ones are simply skipped).
    for name, mod in (("pd", "pandas"), ("np", "numpy"),
                      ("px", "plotly.express"), ("go", "plotly.graph_objects")):
        if name in ns:
            continue
        try:
            ns[name] = __import__(mod, fromlist=["*"]) if "." in mod else __import__(mod)
        except Exception:
            pass

    out = {"stdout": "", "result": None, "figure": None, "table": None, "error": None}
    buf = io.StringIO()
    last_val = None
    try:
        tree = ast.parse(code)
        with redirect_stdout(buf):
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                exec(compile(ast.Module(tree.body[:-1], []), "<code>", "exec"), ns)
                last_val = eval(
                    compile(ast.Expression(tree.body[-1].value), "<code>", "eval"), ns
                )
            else:
                exec(compile(tree, "<code>", "exec"), ns)
    except Exception:
        out["error"] = traceback.format_exc(limit=3)[-1500:]
    out["stdout"] = buf.getvalue()[-4000:]

    try:
        import plotly.graph_objects as go

        fig = ns.get("fig")
        if not isinstance(fig, go.Figure):
            fig = last_val if isinstance(last_val, go.Figure) else None
        if isinstance(fig, go.Figure):
            out["figure"] = fig
    except Exception:
        pass

    try:
        import pandas as pd

        tbl = ns.get("result")
        if not isinstance(tbl, (pd.DataFrame, pd.Series)):
            tbl = last_val if isinstance(last_val, (pd.DataFrame, pd.Series)) else None
        if isinstance(tbl, pd.Series):
            tbl = tbl.rename(tbl.name or "value").reset_index()
        if isinstance(tbl, pd.DataFrame):
            out["table"] = tbl
    except Exception:
        pass

    if out["figure"] is None and out["table"] is None and last_val is not None:
        out["result"] = last_val
    return out


def _summarize_py_result(res: dict) -> str:
    """A short ASCII text summary of a run_python result, for the model to read."""
    parts = []
    if res.get("error"):
        parts.append("Error:\n" + str(res["error"]))
    if res.get("stdout"):
        parts.append("Output:\n" + str(res["stdout"]).rstrip())
    fig = res.get("figure")
    if fig is not None:
        parts.append("Produced a figure (shown in chat).")
    tbl = res.get("table")
    if tbl is not None:
        try:
            shape = getattr(tbl, "shape", None)
            parts.append("Produced a table%s (shown in chat)." % (
                " with shape %s" % (list(shape),) if shape else ""))
        except Exception:
            parts.append("Produced a table (shown in chat).")
    if res.get("result") is not None:
        parts.append("Result: " + repr(res["result"])[:500])
    if not parts:
        parts.append("Ran with no output.")
    if fig is not None or tbl is not None:
        parts.append("Call push_result(slot) to place it into an output slot.")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# App-contract helpers (shared with the MCP describe machinery)
# --------------------------------------------------------------------------- #

# Mosaic letters map positionally to outputs (A = first output, B = second, ...),
# matching Components._infer_mosaic. Slots are advertised and addressed by these
# same uppercase letters, so a set_layout mosaic and a set_output slot agree.
_SLOT_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _brief_output(value, redact=False) -> str:
    """A one-line, model-facing description of one output value.

    Reuses the MCP history summarizer, then flattens its dict form into prose a
    model reads at a glance: a figure's trace count + title, a table's shape, a
    long string's preview. Short scalars/strings pass through verbatim.

    ``redact=True`` reports **shape/type only** -- trace count, table dimensions,
    text length -- and never a value, title, or preview. The sidecar guarantees a
    PasswordInput's value never reaches the LLM (it redacts ctx.inputs), but a
    callback may *derive* an output from that secret (a decrypt/echo app), so when
    the app has any secret input the run summary must not carry output *content*
    back to the model (found in adversarial review of #135).
    """
    from .utils import _summarize_for_history

    # Value-bearing shapes handled before the summarizer, so redaction sees the
    # real type (the summarizer passes short scalars/strings through verbatim).
    if isinstance(value, bool):
        return "a boolean" if redact else str(value)
    if isinstance(value, (int, float)):
        return "a number" if redact else str(value)
    if isinstance(value, str):
        if redact:
            return "text (%d chars)" % len(value)
        return "text (%d chars): %r" % (len(value), value[:80]) if len(value) > 200 \
            else repr(value)

    s = _summarize_for_history(value)
    if not isinstance(s, dict):
        return str(s)
    kind = s.get("type")
    if kind == "Figure":
        n = s.get("n_traces", 0)
        bit = "a figure with %d trace%s" % (n, "" if n == 1 else "s")
        title = s.get("layout_title")
        return bit if redact else bit + (" titled %r" % title if title else "")
    if kind == "DataFrame":
        shape = s.get("shape") or [None, None]
        return "a table (%s rows x %s cols)" % (shape[0], shape[1])
    if kind == "Image":
        return "an image" if redact else "an image (%s %s)" % (s.get("mode"), s.get("size"))
    if kind == "data_url":
        return "an image (%s)" % s.get("mime")
    if kind == "bytes":
        return "binary data (%d bytes)" % s.get("size", 0)
    if kind in ("list", "dict"):
        return "a %s of %d item%s" % (kind, s.get("len"), "" if s.get("len") == 1 else "s")
    return kind if redact else "%s %s" % (kind, s.get("repr", ""))


def _summarize_run(app, raw_outputs) -> str:
    """Model-facing summary of a run: each output slot and what it now holds.

    ``raw_outputs`` is the callback's own return list (before the display
    transform), which describes far more cleanly than the transformed props.
    This is the reply ``run_app`` hands back so the agent can *see* what its run
    produced rather than being told the outputs are merely "updating". When the
    app has a secret (password) input, values are withheld -- shape/type only --
    so an output derived from the secret can't slip back to the model (#135).
    """
    redact = bool(getattr(app, "_sidecar_secret_inputs", None))
    slots = _output_slots(app)
    lines = ["Ran the app. It produced:"]
    for i, value in enumerate(raw_outputs):
        slot = slots[i]["slot"] if i < len(slots) else "slot %d" % i
        lines.append("- %s: %s" % (slot, _brief_output(value, redact=redact)))
    if len(raw_outputs) == 0:
        lines.append("- (no outputs)")
    return "\n".join(lines)


def _output_slots(app) -> list[dict]:
    """``[{"slot": "A", "type": "Graph"}, ...]`` for the app's output components.

    Reuses the MCP ``_enumerate_outputs`` describer (already stringifies ids and
    tags), so the agent's view of the outputs matches a headless MCP agent's.
    """
    try:
        from .mcp import _enumerate_outputs
        outs = _enumerate_outputs(app)
    except Exception:
        outs = []
    slots = []
    for i, d in enumerate(outs):
        letter = _SLOT_LETTERS[i] if i < len(_SLOT_LETTERS) else "slot%d" % i
        tag = d.get("tag")
        # ``tag`` is usually a component name string ("Graph"); a plain-typed
        # output carries the raw type (e.g. ``int``). Stringify to a clean,
        # JSON-safe name so the contract never leaks a type/object repr.
        type_name = getattr(tag, "__name__", None) or (str(tag) if tag else "output")
        slots.append({"slot": letter, "type": type_name})
    return slots


def _read_app_contract(app) -> dict:
    """The app contract an agent reads: title, doc, inputs (with current values),
    and output slots. Reuses the MCP describe machinery so there is one source of
    truth for what an app looks like to an agent (headless MCP or in-app sidecar).
    """
    contract = list(getattr(app, "_sidecar_contract", None) or [])
    return {
        "title": getattr(app, "title", None) or "",
        "doc": (getattr(getattr(app, "callback_fn", None), "__doc__", "") or "").strip(),
        "inputs": contract,
        "outputs": _output_slots(app),
    }


# --------------------------------------------------------------------------- #
# The toolkit
# --------------------------------------------------------------------------- #

_AGENT_EXTRA_MSG = (
    "The chat agent toolkit needs the optional agent extra (langchain + "
    "langgraph). Install it with:\n"
    '    pip install "fast-dash[agent]"'
)


def _require_langchain_tool():
    """Import langchain's ``@tool`` decorator, with a clear ASCII ImportError."""
    try:
        from langchain_core.tools import tool
    except ImportError as e:                       # extra not installed
        raise ImportError(_AGENT_EXTRA_MSG) from e
    return tool


# The default full toolkit's tool names, in a stable, documented order.
_ALL_TOOL_NAMES = (
    "read_app", "set_input", "run_app", "set_output", "set_layout", "run_python",
)


def _run_python_interrupt_payload(code: str) -> dict:
    """The interrupt payload run_python raises for approval.

    Its keys mirror what the langstage bridge maps straight through onto an
    ``interrupt`` frame (``iter_event_frames`` copies ``action_requests`` /
    ``review_configs`` / ``allowed_decisions`` from the interrupt value). Round 3
    renders this: an ``action`` of ``run_python`` and the code in ``args.code``.
    """
    return {
        "action_requests": [{"action": "run_python", "args": {"code": code}}],
        "review_configs": [],
        "allowed_decisions": ["approve", "edit", "reject"],
    }


def agent_toolkit(app) -> list:
    """Build the list of langchain ``@tool`` functions bound to ``app``.

    Only the tools present in ``app.chat_tools_config`` are returned (the server
    still enforces the allowlist at frame dispatch; this just trims the surface
    the model sees). ``run_python`` is included when the allowlist carries either
    a ``RunPython(...)`` config or the bare name; its approval policy comes from
    the config (``RunPython(approval=...)``, default True). When ``run_python``
    is enabled, ``push_result`` is added too so the model can place a produced
    figure / table into an output slot.
    """
    tool = _require_langchain_tool()
    allow = dict(getattr(app, "chat_tools_config", None) or {})
    tools: list = []

    @tool
    def read_app() -> dict:
        """Read the app: its title, description, inputs (name, type, options, and
        current value), and output slots (letter -> component type). Call this
        first to learn what you can change."""
        return _read_app_contract(app)

    @tool
    def set_input(name: str, value: Any) -> str:
        """Set one of the app's inputs to a value. ``name`` is an input id from
        read_app; ``value`` must fit that input's type/options. The change is
        staged; call run_app to apply it. Returns an error string to correct if
        the value is invalid."""
        err = app._sidecar_validate_input(name, value)
        if err:
            return err                                   # no frame -- model retries
        # Stage into the shared per-turn dict so a following run_app (same turn,
        # another graph task) runs on this value -- the frame drain reads the
        # same object, so the two never diverge.
        staged = current_drive_inputs()
        if staged is not None:
            staged[name] = value
        emit_frame({"type": "set_input", "name": name, "value": value})
        return "Set input '%s' to %r." % (name, value)

    @tool
    def run_app() -> str:
        """Run the app with the current inputs and return what it produced.
        Use after set_input to apply changes. A Run always overwrites the
        outputs, so call this last. The reply names each output slot and
        summarizes its value, so you can see the result and react to it."""
        staged = current_drive_inputs()
        run = getattr(app, "_sidecar_run_app_with_result", None)
        # Off-turn (no seeded turn) or a non-sidecar app: keep the old fire-and-
        # forget behavior -- emit the frame for the drain to run, return a note.
        if staged is None or run is None:
            emit_frame({"type": "run_app"})
            return "Ran the app; its outputs are updating."
        try:
            outputs, raw = run(dict(staged))
        except Exception as exc:                          # noqa: BLE001
            # The run failed; nothing to render. Tell the model so it can fix the
            # inputs and try again.
            return "The app raised an error while running: %s" % exc
        # Carry the computed outputs so the frame drain renders them instead of
        # running the callback a second time (single execution per run_app).
        emit_frame({"type": "run_app", "outputs": outputs, "ran": True})
        return _summarize_run(app, raw)

    @tool
    def set_output(slot: str, value: Any) -> str:
        """Set the value of one output slot directly (bypassing a full Run).
        ``slot`` is an output letter from read_app (e.g. "A"). ``value`` is the
        value to render through that slot's output component. Prefer run_app when
        you changed inputs; use set_output to place a specific value."""
        emit_frame({"type": "set_output", "slot": slot, "value": value})
        return "Set output slot '%s'." % slot

    @tool
    def set_layout(mosaic: str) -> str:
        """Rearrange or resize the existing output slots. ``mosaic`` is rows of
        slot letters (newline-separated), rectangular, using only letters that
        already exist (a subset). It never adds or removes slots. Example: "AB"
        puts slots A and B side by side; "A\\nB" stacks them."""
        emit_frame({"type": "set_layout", "mosaic": mosaic})
        return "Requested layout:\n%s" % mosaic

    # ---- assemble, honoring the allowlist -------------------------------- #
    _by_name = {
        "read_app": read_app,
        "set_input": set_input,
        "run_app": run_app,
        "set_output": set_output,
        "set_layout": set_layout,
    }
    for name in ("read_app", "set_input", "run_app", "set_output", "set_layout"):
        if name in allow:
            tools.append(_by_name[name])

    if "run_python" in allow:
        cfg = allow["run_python"]
        needs_approval = cfg.approval if isinstance(cfg, RunPython) else True
        tools.extend(_make_run_python_tools(tool, needs_approval))

    return tools


def _make_run_python_tools(tool, needs_approval: bool) -> list:
    """Build ``run_python`` (+ ``push_result``), closing over the approval flag.

    ``run_python`` executes code in the app process against a per-conversation
    namespace and, on success, auto-emits an ``artifact`` frame for any produced
    figure/table (so it appears inline in chat immediately) and stashes the rich
    object for ``push_result``. The model only ever exchanges strings with these
    tools; rich objects stay server-side.
    """
    from langchain_core.runnables import RunnableConfig

    # ``@tool`` resolves each function's annotations against THIS module's
    # globals (langchain runs get_type_hints), and ``from __future__ import
    # annotations`` makes them lazy strings. ``RunnableConfig`` is a lazy import
    # (not a module-top name), so publish it into globals before the decorator
    # evaluates the ``config: RunnableConfig`` hint, or schema generation raises
    # NameError. (Same lesson as FastMCP's future-annotations gotcha.)
    globals().setdefault("RunnableConfig", RunnableConfig)

    def _execute(code: str, thread_id: str) -> str:
        res = _exec_python(code, thread_id)
        rich = res.get("figure") if res.get("figure") is not None else res.get("table")
        if rich is not None:
            # Show it inline right away, and stash it so push_result can place it.
            emit_frame({"type": "artifact", "content": rich})
            _LAST_RESULT[thread_id] = rich
        return _summarize_py_result(res)

    @tool
    def run_python(code: str, config: RunnableConfig) -> str:
        """Execute Python ``code`` in the app process and return a text summary of
        stdout, the last expression, and any figure/table it produced. Variables
        persist across calls in the same conversation. A produced figure or
        DataFrame is shown inline; call push_result(slot) to place it into an
        output slot. Use this for computation the app's own inputs can't express."""
        thread_id = _thread_id_from_config(config)
        if needs_approval:
            from langgraph.types import interrupt

            # Pause for a human decision. The resume payload arrives as
            # {"decisions": [{"type": "approve"|"edit"|"reject", ...}]} (the
            # langstage create_resume_input shape); an edit may carry replacement
            # code under an "args"/"code"/"value" key.
            decision = interrupt(_run_python_interrupt_payload(code))
            verdict, edited = _read_decision(decision, code)
            if verdict == "reject":
                return "User denied execution."
            return _execute(edited, thread_id)
        return _execute(code, thread_id)

    @tool
    def push_result(slot: str, config: RunnableConfig) -> str:
        """Place the figure or table produced by the most recent run_python call
        into an output slot. ``slot`` is an output letter from read_app (e.g.
        "A"). Use this after run_python reports it produced a figure/table."""
        thread_id = _thread_id_from_config(config)
        rich = _LAST_RESULT.get(thread_id)
        if rich is None:
            return "No stored result to push. Run run_python that produces a figure or table first."
        emit_frame({"type": "set_output", "slot": slot, "value": rich})
        return "Placed the last result into output slot '%s'." % slot

    return [run_python, push_result]


def _read_decision(decision, original_code: str):
    """Interpret a resume payload into ``(verdict, code_to_run)``.

    Accepts the langstage decisions shape (``{"decisions": [{"type": ...}]}``),
    a bare decision dict (``{"type": ...}``), or a plain string. An ``edit``
    decision may carry replacement code under ``args.code`` / ``code`` / ``value``.
    Anything unrecognized is treated as approval of the original code (the
    conservative default when a surface resumes without detail).

    A ``langgraph.types.Command`` (or any object carrying a ``resume`` attr) is
    unwrapped first: some bridges (ag-ui-langgraph) hand the whole ``Command``
    to ``interrupt()``'s return rather than its ``.resume`` payload, so peel it
    off before matching the decisions shape.
    """
    d = decision
    resume_attr = getattr(d, "resume", None)
    if resume_attr is not None and not isinstance(d, (dict, str)):
        d = resume_attr
    if isinstance(d, dict) and "decisions" in d:
        decisions = d.get("decisions") or []
        d = decisions[0] if decisions else {}
    if isinstance(d, str):
        dtype, edited = d, None
    elif isinstance(d, dict):
        dtype = d.get("type") or d.get("decision") or "approve"
        args = d.get("args") if isinstance(d.get("args"), dict) else {}
        edited = d.get("code") or args.get("code") or d.get("value")
    else:
        dtype, edited = "approve", None
    dtype = str(dtype).lower()
    if dtype in ("reject", "deny", "denied", "no"):
        return "reject", original_code
    if dtype in ("edit", "edited") and isinstance(edited, str) and edited.strip():
        return "edit", edited
    return "approve", original_code


# --------------------------------------------------------------------------- #
# System prompt
# --------------------------------------------------------------------------- #

def app_prompt(app) -> str:
    """The system-prompt text describing the app and how to drive it (ASCII).

    Covers what the app does, its inputs (names/types/current values), its output
    slots (letter -> type), the tools available *for this app* (allowlist-aware)
    with when-to-use guidance, the Run-always-wins rule, and the mosaic format.
    """
    contract = _read_app_contract(app)
    allow = dict(getattr(app, "chat_tools_config", None) or {})
    lines: list[str] = []

    title = contract["title"] or "this app"
    lines.append("You are the assistant embedded in a Fast Dash app: %s." % title)
    if contract["doc"]:
        lines.append(contract["doc"])
    lines.append("")

    # Inputs.
    inputs = contract["inputs"]
    if inputs:
        lines.append("Inputs you can read and set:")
        for e in inputs:
            bits = ["- %s" % e.get("id")]
            if e.get("type"):
                bits.append("(%s)" % e["type"])
            if e.get("options"):
                bits.append("options: %s" % (e["options"],))
            cur = e.get("current_value")
            if cur is not None:
                bits.append("current: %r" % (cur,))
            lines.append(" ".join(bits))
    else:
        lines.append("This app has no settable inputs.")
    lines.append("")

    # Output slots.
    slots = contract["outputs"]
    if slots:
        lines.append("Output slots (address by letter):")
        for s in slots:
            lines.append("- %s: %s" % (s["slot"], s["type"]))
    lines.append("")

    # Tools (allowlist-aware).
    guidance = {
        "read_app": "read_app() -- read the app's inputs, current values, and output slots.",
        "set_input": "set_input(name, value) -- stage an input change (validated).",
        "run_app": "run_app() -- run the app on the current inputs; returns a "
                   "summary of each output slot's new value, so you can see the "
                   "result and react to it.",
        "set_output": "set_output(slot, value) -- set one output slot directly.",
        "set_layout": "set_layout(mosaic) -- rearrange/resize existing slots.",
        "run_python": "run_python(code) -- run Python for computation the inputs can't express; "
                      "produced figures/tables show inline, then push_result(slot) places them.",
    }
    tool_lines = [guidance[n] for n in _ALL_TOOL_NAMES if n in allow and n in guidance]
    if tool_lines:
        lines.append("Tools available:")
        lines.extend("- " + t for t in tool_lines)
        lines.append("")

    # Rules.
    lines.append("Rules:")
    if "run_app" in allow:
        lines.append(
            "- A Run always wins: run_app overwrites all outputs, so set inputs "
            "first and call run_app last."
        )
    if "set_layout" in allow:
        lines.append(
            "- set_layout uses a mosaic: rows of slot letters separated by "
            "newlines, forming a rectangle, using only letters that already "
            "exist (a subset). It never adds or removes slots."
        )
    lines.append("- Prefer the app's own inputs and Run over ad-hoc output edits.")

    return "\n".join(lines).strip()


# --------------------------------------------------------------------------- #
# langchain / langgraph wiring
# --------------------------------------------------------------------------- #

def _resolve_model(model):
    """Return a chat-model instance: pass an instance through, resolve a str.

    A ``"provider:model"`` string is resolved via
    ``langchain.chat_models.init_chat_model``; anything else is assumed to be a
    ready model instance and returned unchanged.
    """
    if isinstance(model, str):
        try:
            from langchain.chat_models import init_chat_model
        except ImportError as e:
            raise ImportError(_AGENT_EXTRA_MSG) from e
        return init_chat_model(model)
    return model


def build_auto_agent(app, model):
    """Build a compiled ReAct agent that drives ``app`` with ``model``.

    ``model`` is a chat-model instance or a ``"provider:model"`` string. Returns
    the compiled langgraph graph (a langstage-shaped target the chat sidecar can
    stream). Round 3 calls this from the auto-agent placeholder.
    """
    try:
        from langgraph.prebuilt import create_react_agent
    except ImportError as e:
        raise ImportError(_AGENT_EXTRA_MSG) from e
    resolved = _resolve_model(model)
    return create_react_agent(
        resolved, tools=agent_toolkit(app), prompt=app_prompt(app)
    )


def _require_middleware_base():
    """Import ``AgentMiddleware``, with a clear ASCII ImportError if missing."""
    try:
        from langchain.agents.middleware import AgentMiddleware
    except ImportError as e:
        raise ImportError(_AGENT_EXTRA_MSG) from e
    return AgentMiddleware


def FastDashMiddleware(app):
    """A langchain ``AgentMiddleware`` contributing this app's toolkit + prompt.

    Attach it to a ``create_agent`` (``middleware=[FastDashMiddleware(app)]``) to
    give any agent the app's tools and system prompt without rebuilding the
    agent. The middleware contributes ``agent_toolkit(app)`` via the base class's
    ``tools`` attribute and appends ``app_prompt(app)`` to the model's system
    message in ``wrap_model_call`` (the documented request-modification hook in
    langchain 1.x -- ``ModelRequest.override(system_message=...)``).

    Implemented as a factory function (not a bare class) so the app is bound at
    construction and the base class stays a lazy import (no langchain at module
    top).
    """
    base = _require_middleware_base()
    from langchain_core.messages import SystemMessage

    prompt = app_prompt(app)
    toolkit = agent_toolkit(app)

    def _augmented(request):
        """A copy of ``request`` with the app prompt appended to its system message."""
        existing = getattr(request, "system_message", None)
        existing_text = getattr(existing, "content", existing) or ""
        combined = (str(existing_text) + "\n\n" + prompt).strip() if existing_text \
            else prompt
        return request.override(system_message=SystemMessage(content=combined))

    class _FastDashMiddleware(base):
        """AgentMiddleware bound to one Fast Dash app."""

        tools = toolkit

        def wrap_model_call(self, request, handler):
            return handler(_augmented(request))

        async def awrap_model_call(self, request, handler):
            return await handler(_augmented(request))

    _FastDashMiddleware.__name__ = "FastDashMiddleware"
    return _FastDashMiddleware()
