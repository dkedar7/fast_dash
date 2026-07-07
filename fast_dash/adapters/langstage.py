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


def default_extractors():
    """Fresh instances of the built-in langstage typed-object extractors.

    These turn a LangGraph agent's tool results into ``extraction`` frames
    (``think_tool`` -> reflection, ``write_todos`` -> todos, ``display_inline``
    -> inline rich content, and the skill / memory / compression events) so the
    chat renderer can show a typed card per event instead of a raw tool blob.

    Imported lazily and extra-guarded: on a build without ``langstage-core`` the
    list is empty, so a plain ``(query, ctx)`` chat callback is unaffected.
    Returns fresh instances every call (extractors are cheap and stateless, and
    the caller may dedupe/merge with user extractors).
    """
    try:
        from langstage_core import (
            CompressionExtractor,
            DisplayInlineExtractor,
            MemoryExtractor,
            SkillManageExtractor,
            SkillViewExtractor,
            ThinkToolExtractor,
            TodoExtractor,
        )
    except ImportError:                                # extra not installed
        return []
    return [
        ThinkToolExtractor(),
        TodoExtractor(),
        MemoryExtractor(),
        SkillViewExtractor(),
        SkillManageExtractor(),
        CompressionExtractor(),
        DisplayInlineExtractor(),
    ]


def _merge_extractors(user_extractors):
    """Built-in defaults plus ``user_extractors``, deduped by ``tool_name``.

    A user extractor whose ``tool_name`` matches a built-in one wins (its entry
    replaces the default), so an app can override the rendering of any built-in
    tool while keeping the rest of the defaults. Order is preserved (defaults
    first, then any user extractors for new tool names).
    """
    by_tool = {}
    order = []
    for ex in default_extractors():
        name = getattr(ex, "tool_name", None)
        if name not in by_tool:
            order.append(name)
        by_tool[name] = ex
    for ex in (user_extractors or []):
        name = getattr(ex, "tool_name", None)
        if name not in by_tool:
            order.append(name)
        by_tool[name] = ex                             # user wins on collision
    return [by_tool[name] for name in order]


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


def build_chat_callback(target, extractors=None):
    """Return a chat callback ``(query, ctx)`` that streams ``target``.

    ``target`` is a compiled LangGraph graph or a spec string. The returned
    callback yields Fast Dash chat frames for one turn; ``ctx.thread_id`` (the
    chat session id, injected by the turn runner) selects the checkpointer thread
    so sequential turns on one session share memory, and ``ctx.resume`` continues
    a turn paused on an interrupt (HITL).

    ``extractors`` controls the typed-object streaming that turns tool results
    into ``extraction`` frames (rendered as typed cards):

    * ``None`` (default) -> the seven built-in extractors (see
      :func:`default_extractors`).
    * an iterable -> the built-ins **plus** those extractors, deduped by
      ``tool_name`` with the user's extractor winning on a collision.
    """
    try:
        from langstage_core import load_agent_spec
        from langstage_core.agui import build_agent, iter_event_frames
    except ImportError as e:                       # extra not installed
        raise ImportError(_MISSING_EXTRA_MSG) from e

    graph = load_agent_spec(target) if isinstance(target, str) else target
    agent = build_agent(graph)
    merged = _merge_extractors(extractors)

    def _langstage_chat(query, ctx):
        """Stream a LangGraph agent turn as chat frames (via langstage-core)."""
        # iter_event_frames yields an async generator; the chat turn runner
        # drives sync and async generators uniformly.
        return iter_event_frames(agent, query, thread_id=ctx.thread_id or "default",
                                 resume=ctx.resume, extractors=merged)

    _langstage_chat.__fast_dash_langstage__ = True
    _langstage_chat.__fast_dash_agent__ = agent
    return _langstage_chat


def validate_extractors(extractors):
    """Return a list of ``extractors`` after duck-type validation (ASCII errors).

    Each entry must satisfy the ``ToolExtractor`` protocol: a ``tool_name`` and
    ``extracted_type`` (str-ish attributes) plus a callable ``extract``. This is
    a construction-time check so a bad ``chat_extractors=`` fails with a friendly
    message rather than deep inside a streaming turn. ``None`` -> ``[]``.
    """
    if extractors is None:
        return []
    try:
        items = list(extractors)
    except TypeError:
        raise TypeError(
            "chat_extractors must be an iterable of extractor objects "
            "(each with tool_name, extracted_type, and extract). Got %r."
            % (type(extractors).__name__,)
        )
    for i, ex in enumerate(items):
        missing = [
            attr for attr in ("tool_name", "extracted_type", "extract")
            if not hasattr(ex, attr)
        ]
        if missing or not callable(getattr(ex, "extract", None)):
            raise TypeError(
                "chat_extractors[%d] is not a valid extractor: a %s is missing "
                "%s. An extractor needs a 'tool_name' string, an "
                "'extracted_type' string, and a callable 'extract(content)'."
                % (i, type(ex).__name__,
                   ", ".join(missing or ["a callable extract"]))
            )
    return items


def make_resume_input(decisions, value=None):
    """Build the ``resume`` payload answering an interrupt (langstage-core).

    ``decisions`` is a list of decision dicts (e.g. ``[{"type": "approve"}]``);
    the langstage adapter passes the result to ``iter_event_frames(resume=...)``.
    Kept here so ``fast_dash`` never imports ``langstage-core`` directly.
    """
    from langstage_core import create_resume_input
    return create_resume_input(decisions=list(decisions or []), value=value)
