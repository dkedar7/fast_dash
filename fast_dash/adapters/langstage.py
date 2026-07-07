"""LangGraph adapter for chat mode (RFC #133 Phase 3).

``chat=True`` accepts, in place of a callback function, either a compiled
LangGraph graph or a ``"module:attr"`` / ``"path.py:attr"`` spec string. The
graph is bridged to Fast Dash's frame grammar by ``langstage-core``'s
``iter_event_frames`` — a 1:1 mapping, since Fast Dash's grammar was adopted
from the same AG-UI contract. Multi-turn memory rides the graph's checkpointer
via ``thread_id`` = the chat session id.

The extra is optional: :func:`is_langstage_target` never imports
``langstage-core`` (so detection is free), and :func:`build_chat_callback`
raises a clear, ASCII ``ImportError`` naming the ``fast-dash[langstage]`` extra
when it is missing.
"""


_MISSING_EXTRA_MSG = (
    "This chat app was given a LangGraph agent, which needs the optional "
    "langstage extra. Install it with:\n"
    '    pip install "fast-dash[langstage]"'
)


def is_langstage_target(obj) -> bool:
    """True if ``obj`` should be driven by the LangGraph adapter.

    Recognizes a spec string (``"module:attr"``) or a compiled LangGraph graph,
    duck-typed (``get_graph`` + ``astream``) so this stays import-free — it must
    work even when ``langstage-core`` / ``langgraph`` is not installed.

    A chat *model* is also a LangChain Runnable, so it too carries ``get_graph``
    + ``astream`` — but it additionally has ``bind_tools`` (a compiled graph does
    not). Excluding objects with ``bind_tools`` keeps a model instance out of the
    graph path so it is routed to the auto-agent builder instead (SPEC O1 /
    model-instance detection).
    """
    if isinstance(obj, str):
        return True
    if callable(getattr(obj, "bind_tools", None)):
        return False
    return hasattr(obj, "get_graph") and hasattr(obj, "astream")


def build_chat_callback(target):
    """Return a chat callback ``(query, ctx)`` that streams ``target``.

    ``target`` is a compiled LangGraph graph or a spec string. The returned
    callback yields Fast Dash chat frames for one turn; ``ctx.thread_id`` (the
    chat session id, injected by the turn runner) selects the checkpointer thread
    so sequential turns on one session share memory, and ``ctx.resume`` continues
    a turn paused on an interrupt (HITL).
    """
    try:
        from langstage_core import load_agent_spec
        from langstage_core.agui import build_agent, iter_event_frames
    except ImportError as e:                       # extra not installed
        raise ImportError(_MISSING_EXTRA_MSG) from e

    graph = load_agent_spec(target) if isinstance(target, str) else target
    agent = build_agent(graph)

    def _langstage_chat(query, ctx):
        """Stream a LangGraph agent turn as chat frames (via langstage-core)."""
        # iter_event_frames yields an async generator; the chat turn runner
        # drives sync and async generators uniformly.
        return iter_event_frames(agent, query, thread_id=ctx.thread_id or "default",
                                 resume=ctx.resume)

    _langstage_chat.__fast_dash_langstage__ = True
    _langstage_chat.__fast_dash_agent__ = agent
    return _langstage_chat


def make_resume_input(decisions, value=None):
    """Build the ``resume`` payload answering an interrupt (langstage-core).

    ``decisions`` is a list of decision dicts (e.g. ``[{"type": "approve"}]``);
    the langstage adapter passes the result to ``iter_event_frames(resume=...)``.
    Kept here so ``fast_dash`` never imports ``langstage-core`` directly.
    """
    from langstage_core import create_resume_input
    return create_resume_input(decisions=list(decisions or []), value=value)
