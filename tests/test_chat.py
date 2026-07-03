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
            {"kind": "extraction", "content": {"k": "v"}},
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
        app._chat_cancel["s1"] = True                   # Stop pressed before frames
        self._run(app, "hi")
        content = app.chat_history.get("s1")[-1]["content"]
        assert "(stopped)" in content

    def test_cancellation_midstream_keeps_partial_and_drops_rest(self):
        # Mirror a real Stop click: the flag flips *after* the first token, so
        # the partial text is kept and the later token is never appended.
        app = None

        def bot(query):
            yield "kept "
            app._chat_cancel["s1"] = True               # user hits Stop here
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
        assert len(app._chat_msgs["s1"]) == 4

    @requires_fastapi
    def test_asgi_chat_layout_omits_socketio(self):
        app = FastDash(callback_fn=lambda query: "hi", chat=True, backend="fastapi")
        assert app._native_stream is True
        ids = _layout_ids(app.app.layout)
        # ASGI pushes children via set_props; the WSGI-only socket component and
        # the composer/message list are as expected.
        assert "socketio" not in ids
        assert "chat-messages" in ids and "chat-input" in ids


class TestChatContext:
    """A single `ctx` object carries thread_id / canvas / resume (RFC #133)."""

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
        assert seen["ctx"].canvas == {} and seen["ctx"].resume is None

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
        assert app._chat_pending.get("s1") is not None
        assert app.chat_history.get("s1") == []       # turn not finished

        pending_blocks = app._chat_pending["s1"]["blocks"]
        assert any(b.get("kind") == "interrupt" for b in pending_blocks)

        # Approving resumes and completes the same turn.
        with mock.patch("flask_socketio.emit"):
            app._resume_chat_turn("s1", "sock", "approve")
        assert app._chat_pending.get("s1") is None    # cleared
        hist = app.chat_history.get("s1")
        assert len(hist) == 2                          # one user+assistant pair
        assert "approve" in hist[-1]["content"].lower()

    @requires_langstage
    def test_resume_without_pending_is_noop(self):
        app = FastDash(callback_fn=_interrupt_graph(), chat=True)
        with mock.patch("flask_socketio.emit"):
            assert app._resume_chat_turn("nosuch", "sock", "approve") is False


class TestAguiServing:
    """AG-UI SSE endpoint serving (RFC #133 Phase 4)."""

    @requires_langstage
    def test_non_asgi_warns_and_skips(self):
        with pytest.warns(UserWarning, match="ASGI backend"):
            app = FastDash(callback_fn="langstage_core.demo.stub:graph",
                           chat=True, serve_agui=True)
        assert app.serve_agui is True                 # requested, but not mounted

    @requires_langstage
    def test_non_langstage_warns_and_skips(self):
        with pytest.warns(UserWarning, match="LangGraph agent"):
            FastDash(callback_fn=lambda query: "hi", chat=True,
                     backend="fastapi", serve_agui=True)

    @requires_fastapi
    @requires_langstage
    def test_agui_endpoint_mounted_on_asgi(self):
        app = FastDash(callback_fn="langstage_core.demo.stub:graph", chat=True,
                       backend="fastapi", serve_agui=True)
        paths = {getattr(r, "path", None) for r in app.app.server.routes}
        assert "/agui" in paths


class TestCanvasFrames:
    """Frame grammar for the canvas hybrid (chat ⇄ DynamicDash)."""

    def test_canvas_frame_normalizes(self):
        from fast_dash.chat import _normalize_frame
        f = _normalize_frame({"type": "canvas",
                              "specs": [{"name": "a", "type": "Slider"}]})
        assert f == {"type": "canvas", "specs": [{"name": "a", "type": "Slider"}]}

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
        with pytest.warns(UserWarning, match="canvas=True has no effect"):
            app = FastDash(callback_fn=lambda x: "hi", canvas=True)
        assert app.is_canvas is False

    def test_canvas_layout_present_and_backward_compatible(self):
        app = FastDash(callback_fn=lambda query: "hi", chat=True, canvas=True)
        assert app.is_canvas is True
        ids = self._ids(app.app.layout)
        assert "chat-canvas" in ids and "chat-messages" in ids
        # A plain chat app has no canvas region.
        plain = FastDash(callback_fn=lambda query: "hi", chat=True)
        assert "chat-canvas" not in self._ids(plain.app.layout)

    def test_canvas_frame_renders_and_stores_state(self):
        def bot(query):
            yield {"type": "canvas", "specs": [
                {"name": "amount", "type": "Slider", "value": 3,
                 "props": {"min": 0, "max": 10}},
            ]}
            yield "done"
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        ops = self._ops(app, "build")
        canvas_ops = [p for p in ops if isinstance(p, dict) and p.get("op") == "canvas"]
        assert canvas_ops, "no canvas op emitted"
        assert app._chat_canvas["s1"][0]["name"] == "amount"
        # The transcript is unaffected by canvas frames.
        assert app.chat_history.get("s1")[-1]["content"] == "done"

    def test_set_props_routes_value_and_props(self):
        def bot(query):
            yield {"type": "canvas", "specs": [
                {"name": "amount", "type": "Slider", "value": 3,
                 "props": {"min": 0, "max": 10}}]}
            yield {"type": "set_props", "target": "amount",
                   "props": {"max": 100, "value": 42}}
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        ops = self._ops(app, "patch")
        spec = app._chat_canvas["s1"][0]
        assert spec["value"] == 42                      # value routed to spec['value']
        assert spec["props"]["max"] == 100              # other props merged
        last = json.dumps([p for p in ops if isinstance(p, dict)
                           and p.get("op") == "canvas"][-1]["value"])
        assert '"max": 100' in last or '"max":100' in last

    def test_canvas_values_injected_via_ctx(self):
        seen = {}
        def bot(query, ctx):
            seen.update(ctx.canvas)
            yield f"amount={ctx.canvas.get('amount')}"
        app = FastDash(callback_fn=bot, chat=True, canvas=True)
        assert app._chat_setting_names == []            # ctx is not a setting
        self._ops(app, "read", canvas_values={"amount": 7})
        assert seen == {"amount": 7}
        assert app.chat_history.get("s1")[-1]["content"] == "amount=7"

    def test_gather_canvas_values_by_name(self):
        app = FastDash(callback_fn=lambda query: "x", chat=True, canvas=True)
        states = (
            [7], [True], [],
            [{"role": "dyn-input", "name": "amount", "prop": "value"}],
            [{"role": "dyn-input", "name": "agree", "prop": "checked"}],
            [],
        )
        assert app._gather_canvas_values(states) == {"amount": 7, "agree": True}
