"""Unit tests for the transport-independent chat core (fast_dash/chat.py, RFC #133)."""

import asyncio  # noqa: F401  (async generator tests use it implicitly)
import json
import warnings

import pytest

from fast_dash.chat import (
    ChatFrameError,
    ChatHistory,
    _normalize_frame,
    run_turn,
    wants_history,
    wire_safe,
)


# --- frame normalization --------------------------------------------------- #

class TestNormalizeFrame:
    def test_str_is_content_sugar(self):
        assert _normalize_frame("hi") == {"type": "content", "content": "hi"}

    def test_content_frame_passthrough(self):
        f = _normalize_frame({"type": "content", "content": "yo"})
        assert f == {"type": "content", "content": "yo"}

    def test_content_coerced_to_text(self):
        f = _normalize_frame({"type": "content", "content": 42})
        assert f == {"type": "content", "content": "42"}

    def test_unknown_type_warns_and_skips(self):
        with pytest.warns(UserWarning, match="Unknown chat frame type"):
            assert _normalize_frame({"type": "banana", "x": 1}) is None

    def test_non_frame_value_warns_and_skips(self):
        with pytest.warns(UserWarning, match="expected a str or a frame dict"):
            assert _normalize_frame(12345) is None

    def test_missing_type_raises_friendly_ascii(self):
        with pytest.raises(ChatFrameError) as ei:
            _normalize_frame({"content": "no type"})
        assert str(ei.value).isascii()

    def test_missing_required_key_raises(self):
        with pytest.raises(ChatFrameError):
            _normalize_frame({"type": "content"})           # no 'content'
        with pytest.raises(ChatFrameError):
            _normalize_frame({"type": "tool_start"})        # no 'name'

    def test_tool_start_defaults_id_to_name(self):
        f = _normalize_frame({"type": "tool_start", "name": "search"})
        assert f["id"] == "search" and f["args"] == {}

    def test_tool_end_carries_result(self):
        f = _normalize_frame({"type": "tool_end", "name": "search", "result": [1, 2]})
        assert f["result"] == [1, 2] and f["id"] == "search"

    def test_complete_and_error(self):
        assert _normalize_frame({"type": "complete"}) == {"type": "complete"}
        assert _normalize_frame({"type": "error", "message": "boom"}) == {
            "type": "error", "message": "boom"}


class TestWireSafe:
    def test_artifact_becomes_placeholder(self):
        # An artifact frame carries a rich object; the wire form must be a
        # JSON-safe placeholder (nothing non-serializable crosses the socket).
        import plotly.graph_objects as go
        f = _normalize_frame({"type": "artifact", "content": go.Figure()})
        w = wire_safe(f)
        assert w == {"type": "artifact", "pending": True}

    def test_content_wire_safe_passthrough(self):
        f = {"type": "content", "content": "x"}
        assert wire_safe(f) == f


# --- history store --------------------------------------------------------- #

class TestChatHistory:
    def test_append_and_get_pairs(self):
        h = ChatHistory(size=50)
        h.append_turn("s1", "hello", "hi there")
        assert h.get("s1") == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]

    def test_bounded_to_size_turn_pairs(self):
        h = ChatHistory(size=2)                 # keep 2 turns == 4 messages
        for i in range(5):
            h.append_turn("s1", f"q{i}", f"a{i}")
        msgs = h.get("s1")
        assert len(msgs) == 4
        assert msgs[0] == {"role": "user", "content": "q3"}   # oldest kept
        assert msgs[-1] == {"role": "assistant", "content": "a4"}

    def test_sessions_are_isolated(self):
        h = ChatHistory()
        h.append_turn("s1", "a", "b")
        h.append_turn("s2", "c", "d")
        assert h.get("s1")[0]["content"] == "a"
        assert h.get("s2")[0]["content"] == "c"
        assert len(h.get("unknown")) == 0

    def test_get_returns_copies(self):
        h = ChatHistory()
        h.append_turn("s1", "a", "b")
        snap = h.get("s1")
        snap[0]["content"] = "mutated"
        assert h.get("s1")[0]["content"] == "a"    # store not affected


# --- wants_history --------------------------------------------------------- #

def test_wants_history_detection():
    assert wants_history(lambda query, history: None) is True
    assert wants_history(lambda query: None) is False
    assert wants_history(lambda query, temperature=1: None) is False


# --- run_turn -------------------------------------------------------------- #

class TestRunTurn:
    def _collect(self):
        emitted = []
        return emitted, (lambda f: emitted.append(f))

    def test_str_yields_stream_and_complete(self):
        def bot(query):
            yield "Hello, "
            yield query
        emitted, emit = self._collect()
        out = run_turn(bot, "world", emit=emit)
        assert out["content"] == "Hello, world"
        assert [f["type"] for f in emitted] == ["content", "content", "complete"]

    def test_plain_str_return_non_streaming(self):
        def bot(query):
            return "just one"
        emitted, emit = self._collect()
        out = run_turn(bot, "x", emit=emit)
        assert out["content"] == "just one"
        assert [f["type"] for f in emitted] == ["content", "complete"]

    def test_history_injected_only_when_declared(self):
        seen = {}

        def bot(query, history):
            seen["history"] = history
            yield "ok"
        run_turn(bot, "q", history=[{"role": "user", "content": "prev"}],
                 emit=lambda f: None)
        assert seen["history"] == [{"role": "user", "content": "prev"}]

        def bot_no_hist(query):
            yield "ok"
        # Should not raise even though history is passed to run_turn.
        run_turn(bot_no_hist, "q", history=[{"role": "user", "content": "prev"}],
                 emit=lambda f: None)

    def test_settings_passed_as_kwargs(self):
        seen = {}

        def bot(query, temperature=0.0):
            seen["t"] = temperature
            yield "ok"
        run_turn(bot, "q", settings={"temperature": 0.9}, emit=lambda f: None)
        assert seen["t"] == 0.9

    def test_exception_midstream_becomes_error_frame_and_keeps_partial(self):
        def bot(query):
            yield "partial "
            raise RuntimeError("kaboom")
        emitted, emit = self._collect()
        out = run_turn(bot, "q", emit=emit,
                       friendly_error=lambda m: "friendly: " + m)
        assert out["content"] == "partial "
        types = [f["type"] for f in emitted]
        assert types == ["content", "error", "complete"]
        assert emitted[1]["message"] == "friendly: kaboom"

    def test_unknown_frame_skipped_midstream(self):
        def bot(query):
            yield "a"
            yield {"type": "nope"}
            yield "b"
        emitted, emit = self._collect()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out = run_turn(bot, "q", emit=emit)
        assert out["content"] == "ab"
        assert [f["type"] for f in emitted] == ["content", "content", "complete"]

    def test_async_generator_supported(self):
        async def bot(query):
            yield "async "
            yield "tokens"
        emitted, emit = self._collect()
        out = run_turn(bot, "q", emit=emit)
        assert out["content"] == "async tokens"
        assert emitted[-1]["type"] == "complete"

    def test_tool_frames_flow_through(self):
        def bot(query):
            yield {"type": "tool_start", "name": "search", "id": "1"}
            yield {"type": "tool_end", "name": "search", "id": "1", "result": "done"}
            yield "answer"
        emitted, emit = self._collect()
        out = run_turn(bot, "q", emit=emit)
        assert out["content"] == "answer"
        assert [f["type"] for f in emitted] == [
            "tool_start", "tool_end", "content", "complete"]

    def test_complete_yield_is_deduped(self):
        def bot(query):
            yield "hi"
            yield {"type": "complete"}       # explicit complete
        emitted, emit = self._collect()
        run_turn(bot, "q", emit=emit)
        # exactly one complete, emitted by the runner at the end
        assert [f["type"] for f in emitted].count("complete") == 1


# --- integration: the chat app wiring (no browser) ------------------------- #

import importlib.util  # noqa: E402
from unittest import mock  # noqa: E402

from fast_dash import FastDash  # noqa: E402

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None
requires_fastapi = pytest.mark.skipif(
    not _HAS_FASTAPI, reason="fastapi backend extra not installed"
)
_HAS_LANGSTAGE = importlib.util.find_spec("langstage_core") is not None
requires_langstage = pytest.mark.skipif(
    not _HAS_LANGSTAGE, reason="langstage extra not installed"
)


def _layout_ids(comp, out=None):
    """Collect all string component ids in a Dash layout tree."""
    out = set() if out is None else out
    cid = getattr(comp, "id", None)
    if isinstance(cid, str):
        out.add(cid)
    ch = getattr(comp, "children", None)
    if ch is not None:
        for c in (ch if isinstance(ch, (list, tuple)) else [ch]):
            if c is not None:
                _layout_ids(c, out)
    return out


class TestChatConstruction:
    """The D1 interaction matrix (RFC #133), enforced at construction time."""

    def test_basic_chat_builds_and_forces_stream(self):
        def bot(query):
            yield "hi"
        app = FastDash(callback_fn=bot, chat=True)
        assert app.is_chat is True
        assert app.stream is True                 # chat is inherently streaming
        assert app.outputs_with_ids == []
        assert app.app.layout is not None

    def test_settings_params_become_sidebar_inputs(self):
        def bot(query, temperature: float = 0.7, mode: str = ["a", "b"]):
            yield "hi"
        app = FastDash(callback_fn=bot, chat=True)
        assert app._chat_setting_names == ["temperature", "mode"]
        assert len(app.inputs_with_ids) == 2

    def test_history_param_is_not_a_setting(self):
        def bot(query, history, temperature: float = 0.7):
            yield "hi"
        app = FastDash(callback_fn=bot, chat=True)
        assert app._chat_setting_names == ["temperature"]

    def test_missing_query_param_errors_ascii(self):
        def bot(prompt):
            yield "hi"
        with pytest.raises(TypeError) as ei:
            FastDash(callback_fn=bot, chat=True)
        assert "query" in str(ei.value) and str(ei.value).isascii()

    def test_update_live_incompatible(self):
        def bot(query):
            yield "hi"
        with pytest.raises(TypeError):
            FastDash(callback_fn=bot, chat=True, update_live=True)

    def test_multi_and_steps_rejected(self):
        def bot(query):
            yield "hi"
        with pytest.raises(TypeError):
            FastDash(callback_fn=[bot, bot], chat=True)
        with pytest.raises(TypeError):
            FastDash(callback_fn=None, steps=[bot], chat=True)

    def test_outputs_ignored_with_warning(self):
        from fast_dash import Text
        def bot(query):
            yield "hi"
        with pytest.warns(UserWarning, match="outputs= is ignored"):
            app = FastDash(callback_fn=bot, chat=True, outputs=Text)
        assert app.outputs_with_ids == []

    def test_mcp_supported_in_chat_mode(self):
        # Phase 3: mcp_server=True is now supported in chat mode (no skip
        # warning); the chat MCP contract is exposed instead.
        def bot(query):
            yield "hi"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            app = FastDash(callback_fn=bot, chat=True, mcp_server=True)
        assert not any("supported in chat mode" in str(w.message) for w in caught)
        assert app.mcp_server_enabled is True
        assert app._mcp_state is not None


class TestChatTurnWiring:
    """Drive _run_chat_turn end-to-end with a captured socket emit."""

    def _run(self, app, query, sid="s1", socket="sock", settings=()):
        captured = []
        with mock.patch("flask_socketio.emit",
                        side_effect=lambda ev, payload=None, **k: captured.append((ev, payload))):
            app._run_chat_turn(query, sid, socket, settings)
        return [p for (ev, p) in captured if ev == "chat_frames"]

    def test_turn_emits_start_then_replace0_and_appends_history(self):
        def bot(query):
            yield "Hello "
            yield "world"
        app = FastDash(callback_fn=bot, chat=True)
        payloads = self._run(app, "hi")
        ops = [p["op"] for p in payloads]
        assert ops[0] == "start"                       # user + assistant atomically
        assert "user" in payloads[0] and "assistant" in payloads[0]
        assert ops[-1] == "replace0"                   # final render
        assert set(ops[1:]) == {"replace0"}            # everything after start
        assert app.chat_history.get("s1") == [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello world"},
        ]

    def test_history_injected_on_second_turn(self):
        seen = {}
        def bot(query, history):
            seen["h"] = list(history)
            yield "ok"
        app = FastDash(callback_fn=bot, chat=True)
        self._run(app, "first")
        self._run(app, "second")
        assert seen["h"] == [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
        ]

    def test_settings_values_reach_callback(self):
        seen = {}
        def bot(query, temperature: float = 0.0):
            seen["t"] = temperature
            yield "ok"
        app = FastDash(callback_fn=bot, chat=True)
        self._run(app, "hi", settings=(0.9,))
        assert seen["t"] == 0.9

    def test_error_in_callback_is_surfaced_and_session_survives(self):
        def bot(query):
            yield "partial "
            raise RuntimeError("boom")
        app = FastDash(callback_fn=bot, chat=True)
        payloads = self._run(app, "hi")
        # history records the partial + error text; app stays usable.
        content = app.chat_history.get("s1")[-1]["content"]
        assert "partial" in content and "Error" in content
        # a subsequent turn still runs
        payloads2 = self._run(app, "again")
        assert payloads2[0]["op"] == "start"

    def test_sessions_isolated(self):
        def bot(query):
            yield "r"
        app = FastDash(callback_fn=bot, chat=True)
        self._run(app, "a", sid="s1")
        self._run(app, "b", sid="s2")
        assert app.chat_history.get("s1")[0]["content"] == "a"
        assert app.chat_history.get("s2")[0]["content"] == "b"


class TestChatRichFrames:
    """Phase 2: tool/reasoning/artifact frames and cancellation."""

    def _run(self, app, query, sid="s1", **kw):
        with mock.patch("flask_socketio.emit"):
            app._run_chat_turn(query, sid, "sock", (), **kw)

    def test_tool_frames_render_and_history_is_text_only(self):
        import plotly.graph_objects as go
        def bot(query):
            yield {"type": "tool_start", "name": "search", "id": "1", "args": {"q": "x"}}
            yield {"type": "tool_end", "name": "search", "id": "1", "result": "hit"}
            yield "Here is the answer."
            yield {"type": "artifact", "content": go.Figure()}
        app = FastDash(callback_fn=bot, chat=True)
        self._run(app, "hi")
        # History stores only the text content (not tool/artifact noise).
        assert app.chat_history.get("s1")[-1]["content"] == "Here is the answer."

    def test_bubble_renders_all_block_kinds_without_error(self):
        import pandas as pd
        import plotly.graph_objects as go
        app = FastDash(callback_fn=lambda query: iter(["x"]), chat=True)
        blocks = [
            {"kind": "text", "text": "**hi**"},
            {"kind": "reasoning", "text": "thinking..."},
            {"kind": "tool", "id": "1", "name": "t", "args": {"a": 1}, "result": "ok", "status": "done"},
            {"kind": "tool", "id": "2", "name": "u", "args": None, "result": None, "status": "running"},
            {"kind": "artifact", "content": go.Figure()},
            {"kind": "artifact", "content": pd.DataFrame({"a": [1, 2]})},
        ]
        # Both streaming and final renders must serialize cleanly to plotly-json.
        for streaming in (True, False):
            comp = app._chat_assistant_bubble(blocks, streaming=streaming)
            assert app._chat_bubble_json(comp)          # no exception, JSON-safe

    def test_cancellation_stops_and_marks_partial(self):
        def bot(query):
            yield "partial "
            yield "more"          # should not be reached once cancelled
        app = FastDash(callback_fn=bot, chat=True)
        app._session("s1").cancel = True                # Stop pressed before frames
        self._run(app, "hi")
        content = app.chat_history.get("s1")[-1]["content"]
        assert "(stopped)" in content

    def test_cancellation_midstream_keeps_partial_and_drops_rest(self):
        # Mirror a real Stop click: the flag flips *after* the first token, so
        # the partial text is kept and the later token is never appended.
        app = None

        def bot(query):
            yield "kept "
            app._session("s1").cancel = True            # user hits Stop here
            yield "dropped"                              # must not survive
        app = FastDash(callback_fn=bot, chat=True)
        self._run(app, "hi")
        content = app.chat_history.get("s1")[-1]["content"]
        assert content.startswith("kept ")
        assert "dropped" not in content
        assert "(stopped)" in content

    def test_blocks_text_and_has_text_helpers(self):
        from fast_dash.chat import blocks_text, has_text
        blocks = [
            {"kind": "text", "text": "hello "},
            {"kind": "reasoning", "text": "ignore me"},
            {"kind": "text", "text": "world"},
            {"kind": "tool", "id": "1", "name": "t"},
        ]
        assert blocks_text(blocks) == "hello world"     # text blocks only
        assert has_text(blocks) is True
        assert has_text([{"kind": "tool"}]) is False


class TestChatAsgiTransport:
    """Phase 2: ASGI/set_props streaming parity (RFC #133 D6)."""

    def test_native_stream_pushes_full_children_via_set_props(self):
        # On the ASGI backend, the server pushes the *full* rendered message
        # list straight to chat-messages.children via set_props (set_props is
        # latest-value-wins, so incremental ops would be lost to coalescing).
        # Verify deterministically without a running uvicorn.
        import dash

        def bot(query):
            yield {"type": "tool_start", "name": "s", "id": "1", "args": {}}
            yield "hello"
        app = FastDash(callback_fn=bot, chat=True)
        app._native_stream = True                        # simulate ASGI transport

        calls = []
        with mock.patch.object(dash, "set_props",
                               lambda cid, props: calls.append((cid, props))):
            app._run_chat_turn("hi", "s1", None, ())

        assert calls, "native stream pushed nothing"
        assert all(cid == "chat-messages" for cid, _ in calls)
        # Every push carries a children list; the final one has both the user
        # bubble AND the assistant bubble (the bug that coalescing would drop).
        final_children = calls[-1][1]["children"]
        assert isinstance(final_children, list) and len(final_children) == 2
        assert app.chat_history.get("s1")[-1]["content"] == "hello"

    def test_native_stream_transcript_accumulates_across_turns(self):
        # The server-owned transcript grows by one user+assistant pair per turn
        # and is pushed newest-first (index 0 = latest assistant).
        import dash

        app = FastDash(callback_fn=lambda query: "ok", chat=True)
        app._native_stream = True
        with mock.patch.object(dash, "set_props", lambda cid, props: None):
            app._run_chat_turn("first", "s1", None, ())
            app._run_chat_turn("second", "s1", None, ())
        # Two turns -> four messages retained server-side for the session.
        assert len(app._session("s1").msgs) == 4

    def test_native_stream_transcript_is_bounded_by_history_size(self):
        # The server-owned ASGI transcript is trimmed to the same window as
        # history (2 * chat_history_size), so a long session can't grow it
        # without bound.
        import dash

        app = FastDash(callback_fn=lambda query: "ok", chat=True,
                       chat_history_size=2)
        app._native_stream = True
        with mock.patch.object(dash, "set_props", lambda cid, props: None):
            for i in range(5):
                app._run_chat_turn(f"q{i}", "s1", None, ())
        # Five turns, but bounded to 2 pairs -> 4 messages retained.
        assert len(app._session("s1").msgs) == 2 * 2

    @requires_fastapi
    def test_asgi_chat_layout_omits_socketio(self):
        app = FastDash(callback_fn=lambda query: "hi", chat=True, backend="fastapi")
        assert app._native_stream is True
        ids = _layout_ids(app.app.layout)
        # ASGI pushes children via set_props; the WSGI-only socket component and
        # the composer/message list are as expected.
        assert "socketio" not in ids
        assert "chat-messages" in ids and "chat-input" in ids


class TestSessionState:
    """One ChatSession per session, with idle eviction (RFC #133 hardening)."""

    def test_session_is_created_and_reused(self):
        from fast_dash.chat import ChatSession
        app = FastDash(callback_fn=lambda query: "ok", chat=True)
        s = app._session("s1")
        assert isinstance(s, ChatSession)
        assert app._session("s1") is s                 # same object reused

    def test_idle_sessions_are_evicted_with_history(self):
        app = FastDash(callback_fn=lambda query: "ok", chat=True)
        old = app._session("old")
        app.chat_history.append_turn("old", "q", "a")
        old.last_seen = 0.0                            # ancient
        app._last_sweep = 0.0                          # force a sweep next call
        app._session("new")                            # triggers eviction
        assert "old" not in app._sessions              # evicted
        assert app.chat_history.get("old") == []       # history cleared too
        assert "new" in app._sessions                  # current session kept


class TestChatContext:
    """A single `ctx` object carries thread_id / resume (RFC #133)."""

    def _run(self, app, query, sid="s1"):
        with mock.patch("flask_socketio.emit"):
            app._run_chat_turn(query, sid, "sock", ())

    def test_ctx_injected_when_declared(self):
        from fast_dash import ChatContext
        seen = {}

        def bot(query, ctx):
            seen["ctx"] = ctx
            yield "ok"
        app = FastDash(callback_fn=bot, chat=True)
        assert app._chat_setting_names == []          # ctx is not a setting
        self._run(app, "hi", sid="sessionABC")
        assert isinstance(seen["ctx"], ChatContext)
        assert seen["ctx"].thread_id == "sessionABC"
        assert seen["ctx"].resume is None

    def test_ctx_not_passed_when_undeclared(self):
        # A callback without ctx must never receive it (the 5-line promise).
        def bot(query):
            yield "ok"
        app = FastDash(callback_fn=bot, chat=True)
        self._run(app, "hi")                          # would TypeError if injected
        assert app.chat_history.get("s1")[-1]["content"] == "ok"

    def test_history_and_ctx_coexist(self):
        seen = {}

        def bot(query, history, ctx):
            seen["h"] = history
            seen["tid"] = ctx.thread_id
            yield "ok"
        app = FastDash(callback_fn=bot, chat=True)
        assert app._chat_setting_names == []
        self._run(app, "hi", sid="s9")
        assert seen["tid"] == "s9" and isinstance(seen["h"], list)


class TestLangstageAdapter:
    """The LangGraph adapter for chat mode (RFC #133 Phase 3)."""

    def test_detection_is_import_free(self):
        from fast_dash.adapters.langstage import is_langstage_target
        assert is_langstage_target("pkg.mod:graph") is True     # spec string
        assert is_langstage_target(lambda query: "x") is False  # plain callable
        assert is_langstage_target(object()) is False

    def test_missing_extra_raises_clear_ascii_error(self):
        import sys
        from fast_dash.adapters.langstage import build_chat_callback
        # Force the langstage import to fail even if it happens to be installed.
        with mock.patch.dict(sys.modules, {"langstage_core": None,
                                           "langstage_core.agui": None}):
            with pytest.raises(ImportError) as ei:
                build_chat_callback("pkg.mod:graph")
        msg = str(ei.value)
        assert 'fast-dash[langstage]' in msg
        assert msg.isascii()                          # Windows cp1252 consoles

    @requires_langstage
    def test_stub_graph_spec_streams_a_turn(self):
        app = FastDash(callback_fn="langstage_core.demo.stub:graph", chat=True)
        assert app.is_langstage is True
        assert app._chat_setting_names == []          # no sidebar settings
        with mock.patch("flask_socketio.emit"):
            app._run_chat_turn("hello there", "s1", "sock", ())
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "hello there" in reply                 # stub echoes the query

    @requires_langstage
    def test_sequential_turns_share_thread_id(self):
        app = FastDash(callback_fn="langstage_core.demo.stub:graph", chat=True)
        with mock.patch("flask_socketio.emit"):
            app._run_chat_turn("first", "s1", "sock", ())
            app._run_chat_turn("second", "s1", "sock", ())
        assert len(app.chat_history.get("s1")) == 4   # two user+assistant pairs

    @requires_langstage
    def test_accepts_compiled_graph_object(self):
        from langstage_core.demo import stub
        app = FastDash(callback_fn=stub.graph, chat=True)
        assert app.is_langstage is True


def _interrupt_graph():
    """A keyless LangGraph that interrupts once, then echoes the decision."""
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.types import interrupt

    def gate(state):
        decision = interrupt({
            "action_requests": [{"action": "write_file", "args": {"path": "notes.txt"}}],
            "allowed_decisions": ["approve", "reject"],
        })
        return {"messages": [AIMessage(content=f"Proceeding: {decision}")]}

    g = StateGraph(MessagesState)
    g.add_node("gate", gate)
    g.add_edge(START, "gate")
    g.add_edge("gate", END)
    return g.compile(checkpointer=InMemorySaver())


class TestChatInterruptFrame:
    """interrupt frame validation + card rendering (RFC #133 Phase 4)."""

    def test_interrupt_frame_normalizes_with_review_configs(self):
        from fast_dash.chat import _normalize_frame
        f = _normalize_frame({
            "type": "interrupt",
            "action_requests": [{"action": "x"}],
            "allowed_decisions": ["approve", "reject"],
        })
        assert f["type"] == "interrupt"
        assert f["action_requests"] == [{"action": "x"}]
        assert f["allowed_decisions"] == ["approve", "reject"]
        assert f["review_configs"] == []              # carried for later phases

    def test_run_turn_reports_pausing_interrupt(self):
        from fast_dash.chat import run_turn

        def bot(query):
            yield {"type": "interrupt", "action_requests": [],
                   "allowed_decisions": ["approve"]}
        result = run_turn(bot, "hi")
        assert result["interrupt"] is not None        # turn paused on interrupt

    def test_interrupt_card_renders_decision_buttons(self):
        app = FastDash(callback_fn=lambda query: "x", chat=True)
        block = {"kind": "interrupt",
                 "action_requests": [{"action": "write_file", "args": {"p": 1}}],
                 "allowed_decisions": ["approve", "reject"], "resolved": False}
        comp = app._chat_interrupt_card(block, pending=True)
        assert app._chat_bubble_json(comp)            # JSON-safe, no exception


class TestChatHitl:
    """End-to-end human-in-the-loop pause + resume (RFC #133 Phase 4)."""

    def _run(self, app, query, sid="s1"):
        with mock.patch("flask_socketio.emit"):
            app._run_chat_turn(query, sid, "sock", ())

    @requires_langstage
    def test_pause_then_resume_completes_turn(self):
        app = FastDash(callback_fn=_interrupt_graph(), chat=True)
        assert app.is_langstage is True

        # First pass pauses on the interrupt: pending is set, no history yet.
        self._run(app, "please write")
        assert app._session("s1").pending is not None
        assert app.chat_history.get("s1") == []       # turn not finished

        pending_blocks = app._session("s1").pending["blocks"]
        assert any(b.get("kind") == "interrupt" for b in pending_blocks)

        # Approving resumes and completes the same turn.
        with mock.patch("flask_socketio.emit"):
            app._resume_chat_turn("s1", "sock", "approve")
        assert app._session("s1").pending is None     # cleared
        hist = app.chat_history.get("s1")
        assert len(hist) == 2                          # one user+assistant pair
        assert "approve" in hist[-1]["content"].lower()

    @requires_langstage
    def test_resume_without_pending_is_noop(self):
        app = FastDash(callback_fn=_interrupt_graph(), chat=True)
        with mock.patch("flask_socketio.emit"):
            assert app._resume_chat_turn("nosuch", "sock", "approve") is False


class TestCanvasFrames:
    """Frame grammar for the canvas hybrid (chat ⇄ DynamicDash)."""

    def test_canvas_frame_normalizes(self):
        from fast_dash.chat import _normalize_frame
        f = _normalize_frame({"type": "canvas",
                              "specs": [{"name": "a", "type": "Graph"}]})
        assert f == {"type": "canvas", "specs": [{"name": "a", "type": "Graph"}]}

    def test_canvas_frame_requires_specs_list(self):
        from fast_dash.chat import ChatFrameError, _normalize_frame
        for bad in ({"type": "canvas"}, {"type": "canvas", "specs": "no"}):
            with pytest.raises(ChatFrameError):
                _normalize_frame(bad)

    def test_set_props_frame_normalizes_and_validates(self):
        from fast_dash.chat import ChatFrameError, _normalize_frame
        f = _normalize_frame({"type": "set_props", "target": "a", "props": {"max": 9}})
        assert f == {"type": "set_props", "target": "a", "props": {"max": 9}}
        with pytest.raises(ChatFrameError):
            _normalize_frame({"type": "set_props"})            # missing target
        with pytest.raises(ChatFrameError):
            _normalize_frame({"type": "set_props", "target": "a", "props": "x"})


class TestChatCanvas:
    """The assistant-driven canvas end-to-end (RFC #133 follow-up)."""

    def _ids(self, comp, out=None):
        return _layout_ids(comp, out)

    def _ops(self, app, query, sid="s1", **kw):
        ops = []
        with mock.patch("flask_socketio.emit",
                        side_effect=lambda ev, payload=None, **k: ops.append(payload)):
            app._run_chat_turn(query, sid, "sock", (), **kw)
        return ops

    def test_canvas_only_with_chat(self):
        # canvas without chat warns and is a no-op.
        with pytest.warns(UserWarning, match="have no effect without chat"):
            app = FastDash(callback_fn=lambda x: "hi", canvas=True)
        assert app.is_canvas is False

    def test_canvas_layout_present_and_backward_compatible(self):
        app = FastDash(callback_fn=lambda query: "hi", chat=True, canvas=True)
        assert app.is_canvas is True
        ids = self._ids(app.app.layout)
        # Output canvas (main) + transcript.
        assert {"chat-canvas", "chat-messages"} <= ids
        # A plain chat app has no canvas region.
        plain = FastDash(callback_fn=lambda query: "hi", chat=True)
        plain_ids = self._ids(plain.app.layout)
        assert "chat-canvas" not in plain_ids

    def test_declared_settings_render_in_canvas_and_feed_callback(self):
        # Developer-declared inputs (model/temperature) render on the chat side
        # in canvas mode and their live values reach the callback each turn.
        seen = {}
        def bot(query, model: str = "sonnet", temperature: float = 0.7):
            seen["model"], seen["temp"] = model, temperature
            yield "ok"
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        assert app._chat_setting_names == ["model", "temperature"]
        ids = self._ids(app.app.layout)
        assert {"chat-settings", "model", "temperature"} <= ids   # rendered, not dropped
        with mock.patch("flask_socketio.emit"):
            app._run_chat_turn("hi", "s1", "sock", ("opus", 0.9))
        assert seen == {"model": "opus", "temp": 0.9}

    def test_canvas_frame_renders_and_stores_state(self):
        def bot(query):
            yield {"type": "canvas", "specs": [
                {"name": "note", "type": "Markdown", "value": "## Report"},
            ]}
            yield "done"
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        ops = self._ops(app, "build")
        canvas_ops = [p for p in ops if isinstance(p, dict) and p.get("op") == "canvas"]
        assert canvas_ops, "no canvas op emitted"
        assert app._session("s1").canvas_specs[0]["name"] == "note"
        # The transcript is unaffected by canvas frames.
        assert app.chat_history.get("s1")[-1]["content"] == "done"

    def test_set_props_routes_value_and_props(self):
        def bot(query):
            yield {"type": "canvas", "specs": [
                {"name": "chart", "type": "Graph", "value": {"data": []},
                 "props": {"style": {"height": "300px"}}}]}
            yield {"type": "set_props", "target": "chart",
                   "props": {"figure": {"data": [{"type": "bar"}]},
                             "config": {"staticPlot": True}}}
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        ops = self._ops(app, "patch")
        spec = app._session("s1").canvas_specs[0]
        # 'figure' is Graph's value-prop, so it routes to spec['value'];
        # 'config' is an ordinary prop and merges into spec['props'].
        assert spec["value"] == {"data": [{"type": "bar"}]}
        assert spec["props"]["config"] == {"staticPlot": True}
        last = json.dumps([p for p in ops if isinstance(p, dict)
                           and p.get("op") == "canvas"][-1]["value"])
        assert '"bar"' in last

    def test_canvas_renders_display_components(self):
        # E1: the assistant can build dashboards (charts/tables), not just forms.
        import plotly.graph_objects as go
        def bot(query):
            yield {"type": "canvas", "specs": [
                {"name": "chart", "type": "Graph",
                 "value": go.Figure(go.Bar(x=[1, 2], y=[3, 4])), "label": "Sales"},
                {"name": "tbl", "type": "Table",
                 "value": [{"a": 1, "b": 2}], "label": ""},
            ]}
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        ops = self._ops(app, "dashboard")
        last = json.dumps([p for p in ops if isinstance(p, dict)
                           and p.get("op") == "canvas"][-1]["value"])
        assert '"bar"' in last                          # Graph rendered on the canvas
        assert app._session("s1").canvas_specs[0]["type"] == "Graph"

    def test_canvas_span_arranges_into_grid(self):
        # The assistant controls arrangement via per-spec `span` (out of 12).
        def bot(query):
            yield {"type": "canvas", "specs": [
                {"name": "a", "type": "Markdown", "value": "left", "span": 8},
                {"name": "b", "type": "Markdown", "value": "right", "span": 4},
            ]}
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        ops = self._ops(app, "grid")
        val = [p for p in ops if isinstance(p, dict)
               and p.get("op") == "canvas"][-1]["value"]
        assert val["type"] == "Grid"                     # laid out in a grid
        cols = val["props"]["children"]
        assert [c["props"]["span"] for c in cols] == [8, 4]   # side-by-side widths

    def test_canvas_renders_image_component(self):
        # Image is a display component too (src-based) — the last of the four.
        def bot(query):
            yield {"type": "canvas", "specs": [
                {"name": "logo", "type": "Image", "label": "Logo",
                 "value": "data:image/png;base64,iVBORw0KGgo="}]}
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        ops = self._ops(app, "show image")
        last = json.dumps([p for p in ops if isinstance(p, dict)
                           and p.get("op") == "canvas"][-1]["value"])
        assert "base64" in last                          # the src reached the canvas
        assert app._session("s1").canvas_specs[0]["type"] == "Image"

    def test_empty_specs_clears_the_canvas(self):
        # Rebuilding from an empty spec list is how the assistant clears the
        # canvas — both the stored state and the emitted output go empty.
        def bot(query):
            if "build" in query:
                yield {"type": "canvas", "specs": [
                    {"name": "n", "type": "Markdown", "value": "hi"}]}
            else:
                yield {"type": "canvas", "specs": []}
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        self._ops(app, "build")
        assert app._session("s1").canvas_specs             # built
        ops = self._ops(app, "clear it")
        assert app._session("s1").canvas_specs == []       # state cleared
        last = [p for p in ops if isinstance(p, dict)
                and p.get("op") == "canvas"][-1]["value"]
        assert last == []                                  # emptied on the wire too

    def test_set_props_patches_a_canvas_from_an_earlier_turn(self):
        # The canvas is a surface the assistant maintains ACROSS turns: a later
        # set_props patches specs built in an earlier turn (session-persisted).
        def bot(query):
            if "build" in query:
                yield {"type": "canvas", "specs": [
                    {"name": "chart", "type": "Graph", "value": {"data": []}}]}
            else:
                yield {"type": "set_props", "target": "chart",
                       "props": {"figure": {"data": [{"type": "bar"}]}}}
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        self._ops(app, "build")                            # turn 1 builds
        ops = self._ops(app, "update it")                  # turn 2 patches turn 1's spec
        assert app._session("s1").canvas_specs[0]["value"] == {"data": [{"type": "bar"}]}
        last = json.dumps([p for p in ops if isinstance(p, dict)
                           and p.get("op") == "canvas"][-1]["value"])
        assert '"bar"' in last

    def test_set_props_to_unknown_target_is_a_safe_noop(self):
        # Patching a component that was never built must not crash the turn.
        def bot(query):
            yield {"type": "set_props", "target": "ghost", "props": {"figure": {}}}
            yield "ok"
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        self._ops(app, "patch ghost")                      # must not raise
        assert app._session("s1").canvas_specs == []       # nothing created
        assert app.chat_history.get("s1")[-1]["content"] == "ok"

    def test_unknown_component_type_is_surfaced_not_fatal(self):
        # The canvas is display-only, so a non-display type (e.g. an input
        # widget) is caught at render and surfaced as an error — the session
        # survives and a later well-formed turn still works.
        def bot(query):
            if "bad" in query:
                yield {"type": "canvas", "specs": [
                    {"name": "x", "type": "Slider", "value": 1}]}
            else:
                yield {"type": "canvas", "specs": [
                    {"name": "n", "type": "Markdown", "value": "ok"}]}
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        self._ops(app, "build bad")                        # must not raise
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "Error" in reply and "Slider" in reply      # surfaced to the user
        self._ops(app, "build good")                       # session not poisoned
        assert app._session("s1").canvas_specs[0]["type"] == "Markdown"


class TestCanvasLLMOnramp:
    """canvas_tool_specs / apply_tool_call: wire an LLM to the canvas (E2)."""

    def test_tool_specs_shape_and_types(self):
        from fast_dash import canvas_tool_specs
        specs = canvas_tool_specs()
        names = {t["name"] for t in specs}
        assert names == {"build_canvas", "set_canvas_props"}
        build = next(t for t in specs if t["name"] == "build_canvas")
        item = build["input_schema"]["properties"]["specs"]["items"]
        # The canvas is display-only, so only display components are offered.
        assert set(item["properties"]["type"]["enum"]) == {
            "Graph", "Image", "Markdown", "Table"}
        assert item["required"] == ["name", "type"]

    def test_apply_build_canvas_tool_call(self):
        from fast_dash import apply_tool_call
        frame = apply_tool_call({"name": "build_canvas",
                                 "input": {"specs": [{"name": "a", "type": "Graph"}]}})
        assert frame == {"type": "canvas", "specs": [{"name": "a", "type": "Graph"}]}

    def test_apply_set_props_tool_call(self):
        from fast_dash import apply_tool_call
        frame = apply_tool_call({"name": "set_canvas_props",
                                 "input": {"target": "a", "props": {"max": 20}}})
        assert frame == {"type": "set_props", "target": "a", "props": {"max": 20}}

    def test_apply_handles_json_string_and_openai_shapes(self):
        from fast_dash import apply_tool_call
        # OpenAI-style: function.arguments as a JSON string.
        frame = apply_tool_call({"function": {"name": "build_canvas",
                                              "arguments": '{"specs": []}'}})
        assert frame == {"type": "canvas", "specs": []}

    def test_apply_object_form_and_unknown(self):
        from fast_dash import apply_tool_call

        class ToolUse:                                    # Anthropic-like block
            name = "set_canvas_props"
            input = {"target": "x", "props": {"value": 1}}
        assert apply_tool_call(ToolUse())["type"] == "set_props"
        assert apply_tool_call({"name": "some_other_tool", "input": {}}) is None

    def test_frames_from_tool_calls_drive_the_canvas(self):
        # End-to-end: an LLM's tool calls -> frames -> canvas render.
        from fast_dash import apply_tool_call
        calls = [
            {"name": "build_canvas", "input": {"specs": [
                {"name": "chart", "type": "Graph", "value": {"data": []}, "props": {}}]}},
            {"name": "set_canvas_props",
             "input": {"target": "chart", "props": {"config": {"staticPlot": True}}}},
        ]
        def bot(query):
            for tc in calls:
                yield apply_tool_call(tc)
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        with mock.patch("flask_socketio.emit"):
            app._run_chat_turn("go", "s1", "sock", ())
        assert app._session("s1").canvas_specs[0]["props"]["config"] == {"staticPlot": True}


class TestChatDrawer:
    """App-first layout: settings + Run drive the canvas; chat is a drawer add-on."""

    def _ids(self, comp, out=None):
        return _layout_ids(comp, out)

    def test_drawer_implies_canvas_and_builds_layout(self):
        from typing import Literal
        def app(query, ctx, model: Literal["a", "b"] = "a", temperature: float = 0.5):
            yield "ok"
        fd = FastDash(callback_fn=app, chat=True, chat_drawer=True)
        assert fd.is_chat_drawer is True
        assert fd.is_canvas is True                     # implied by chat_drawer
        ids = self._ids(fd.app.layout)
        # Left panel toggles between the inputs view (settings + Run + an expand
        # button) and the chat view (with a Back button); output canvas in main.
        assert {"chat-run", "chat-open", "chat-back", "chat-inputs-view",
                "chat-panel-view", "chat-canvas", "model", "temperature"} <= ids

    def test_drawer_without_chat_warns(self):
        with pytest.warns(UserWarning, match="have no effect without chat"):
            fd = FastDash(callback_fn=lambda x: "hi", chat_drawer=True)
        assert fd.is_chat_drawer is False

    def test_run_updates_canvas_without_transcript(self):
        import plotly.graph_objects as go
        def app(query, ctx, temperature: float = 0.5):
            if query:
                yield f"said {query}"                    # chat narration
            yield {"type": "canvas", "specs": [
                {"name": "c", "type": "Graph",
                 "value": go.Figure(go.Bar(x=[1], y=[temperature])), "label": "Out"}]}
        fd = FastDash(callback_fn=app, chat=True, chat_drawer=True)
        ops = []
        with mock.patch("flask_socketio.emit",
                        side_effect=lambda ev, p=None, **k: ops.append(p)):
            fd._run_chat_turn("", "s1", "sock", (0.9,), to_transcript=False)
        payloads = [p for p in ops if isinstance(p, dict)]
        assert any(p.get("op") == "canvas" for p in payloads)          # canvas updated
        assert not any(p.get("op") in ("start", "replace0") for p in payloads)  # no transcript
        assert fd.chat_history.get("s1") == []                          # no history

    def test_chat_turn_still_records_transcript(self):
        def app(query, ctx):
            yield "reply"
        fd = FastDash(callback_fn=app, chat=True, chat_drawer=True)
        with mock.patch("flask_socketio.emit"):
            fd._run_chat_turn("hi", "s1", "sock", (), to_transcript=True)
        assert fd.chat_history.get("s1")[-1]["content"] == "reply"


class TestSidecarFrames:
    """set_input / run_app frame grammar (chat sidecar drive)."""

    def test_set_input_frame_normalizes(self):
        f = _normalize_frame({"type": "set_input", "name": "a", "value": 5})
        assert f == {"type": "set_input", "name": "a", "value": 5}

    def test_set_input_requires_name(self):
        with pytest.raises(ChatFrameError):
            _normalize_frame({"type": "set_input", "value": 5})

    def test_run_app_frame_normalizes(self):
        assert _normalize_frame({"type": "run_app"}) == {"type": "run_app"}

    def test_app_tool_specs_and_apply(self):
        from fast_dash import app_tool_specs, apply_tool_call
        specs = app_tool_specs(["a", "b"])
        assert {t["name"] for t in specs} == {"set_input", "run_app"}
        set_tool = next(t for t in specs if t["name"] == "set_input")
        assert set_tool["input_schema"]["properties"]["name"]["enum"] == ["a", "b"]
        assert apply_tool_call({"name": "set_input", "input": {"name": "a", "value": 3}}) == \
            {"type": "set_input", "name": "a", "value": 3}
        assert apply_tool_call({"name": "run_app", "input": {}}) == {"type": "run_app"}


class TestChatSidecar:
    """chat_agent=: an independent chat agent mounted on a normal app."""

    def _ops(self, app, query, sid="s1", app_inputs=None):
        ops = []
        with mock.patch("flask_socketio.emit",
                        side_effect=lambda ev, payload=None, **k: ops.append((ev, payload))):
            app._run_chat_turn(query, sid, "sock", (), app_inputs=app_inputs)
        return ops

    def test_builds_on_a_normal_app_with_both_surfaces(self):
        def dashboard(revenue: int = 100) -> str:
            return f"rev {revenue}"
        def agent(query, ctx):
            yield "hi"
        app = FastDash(callback_fn=dashboard, chat_agent=agent, chat_agent_title="Helper")
        assert app.has_chat_sidecar is True
        ids = _layout_ids(app.app.layout)
        # The normal output surface AND the chat panel both exist.
        assert "output-group-col" in ids
        assert {"chat-messages", "chat-input", "chat-send", "chat-aside",
                "chat-sidecar-toggle", "chat-sidecar-close"} <= ids

    def test_plain_app_has_no_chat_dom(self):
        app = FastDash(callback_fn=lambda x: "hi")
        ids = _layout_ids(app.app.layout)
        assert "chat-messages" not in ids and "chat-aside" not in ids

    def test_chat_and_chat_agent_are_rejected(self):
        def agent(query):
            yield "x"
        with pytest.raises(TypeError, match="cannot be combined with chat=True"):
            FastDash(callback_fn=lambda query: "hi", chat=True, chat_agent=agent)

    def test_agent_must_be_query_first(self):
        def bad_agent(message, ctx):
            yield "x"
        with pytest.raises(TypeError, match="first parameter must be named 'query'"):
            FastDash(callback_fn=lambda a: a, chat_agent=bad_agent)

    def test_turn_streams_and_records_history_independently(self):
        seen = {}
        def dashboard(a: int = 1) -> str:
            seen["ran"] = True                 # must NOT run on a chat turn
            return str(a)
        def agent(query, ctx):
            yield f"echo: {query}"
        app = FastDash(callback_fn=dashboard, chat_agent=agent)
        self._ops(app, "hello")
        assert app.chat_history.get("s1")[-1]["content"] == "echo: hello"
        assert "ran" not in seen               # the host callback was untouched

    def test_ctx_inputs_reads_host_inputs(self):
        seen = {}
        def dashboard(revenue: int = 1, region: str = "W") -> str:
            return "x"
        def agent(query, ctx):
            seen["inputs"] = dict(ctx.inputs)
            yield "ok"
        app = FastDash(callback_fn=dashboard, chat_agent=agent)
        assert app._chat_input_mode == "ctx"
        self._ops(app, "hi", app_inputs={"revenue": 42, "region": "E"})
        assert seen["inputs"] == {"revenue": 42, "region": "E"}

    def test_set_input_accumulates_and_run_app_pushes_outputs(self):
        def dashboard(a: int = 1, b: int = 2) -> str:
            return f"sum={a + b}"
        def agent(query, ctx):
            yield {"type": "set_input", "name": "a", "value": 10}
            yield {"type": "set_input", "name": "b", "value": 20}
            yield {"type": "run_app"}
        app = FastDash(callback_fn=dashboard, chat_agent=agent)
        ops = self._ops(app, "go", app_inputs={"a": 1, "b": 2})
        drive = [p for ev, p in ops if ev == "chat_drive"]
        # set_input a -> [10, 2]; set_input b -> [10, 20]; run_app -> outputs.
        assert drive[0]["inputs"] == [10, 2]
        assert drive[1]["inputs"] == [10, 20]
        assert drive[2]["outputs"] == ["sum=30"]
        # The run_app op carries the full inputs too, so the latest-wins
        # data-chat_drive prop can't clobber the set_inputs made this turn.
        assert drive[2]["inputs"] == [10, 20]

    def test_drive_on_asgi_uses_set_props(self):
        import dash
        def dashboard(a: int = 1, b: int = 2) -> str:
            return f"sum={a + b}"
        def agent(query, ctx):
            yield {"type": "set_input", "name": "a", "value": 7}
            yield {"type": "run_app"}
        app = FastDash(callback_fn=dashboard, chat_agent=agent)
        app._native_stream = True
        calls = []
        with mock.patch.object(dash, "set_props",
                               lambda cid, props: calls.append((cid, props))):
            app._run_chat_turn("go", "s1", None, (), app_inputs={"a": 1, "b": 2})
        non_transcript = [(c, p) for c, p in calls if c != "chat-messages"]
        assert ("a", {"value": 7}) in non_transcript
        # The single output component was updated with sum=9.
        assert any(list(p.values()) == ["sum=9"] for _, p in non_transcript)

    def test_sidecar_on_multi_is_conversational_and_guards_drive(self):
        def f1(x: int = 1) -> str: return f"f1={x}"
        def f2(y: int = 2) -> str: return f"f2={y}"
        def agent(query, ctx):
            yield {"type": "set_input", "name": "x", "value": 9}
            yield {"type": "run_app"}
        app = FastDash(callback_fn=[f1, f2], chat_agent=agent)
        assert app.has_chat_sidecar and app._chat_input_mode == "none"
        assert app._sidecar_can_drive is False
        ids = _layout_ids(app.app.layout)
        assert {"chat-aside", "multi-function-tabs"} <= ids
        self._ops(app, "go")
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "multiple surfaces" in reply         # drive deflected, not fatal

    @requires_langstage
    def test_langgraph_graph_as_sidecar(self):
        def dashboard(a: int = 1) -> str:
            return str(a)
        app = FastDash(callback_fn=dashboard,
                       chat_agent="langstage_core.demo.stub:graph")
        assert app.has_chat_sidecar and app.is_langstage
        self._ops(app, "hello there")
        assert "hello there" in app.chat_history.get("s1")[-1]["content"]
