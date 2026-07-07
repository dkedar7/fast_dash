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
_HAS_AGENT = (
    importlib.util.find_spec("langchain") is not None
    and importlib.util.find_spec("langgraph") is not None
)
# The auto-built assistant needs [agent] (build) AND [langstage] (bridge to
# chat frames), so its end-to-end tests require both extras.
requires_auto_agent = pytest.mark.skipif(
    not (_HAS_AGENT and _HAS_LANGSTAGE),
    reason="auto-agent needs the agent + langstage extras",
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


def _find_by_id(comp, target):
    """Return the first component in the tree whose id == target, else None."""
    if getattr(comp, "id", None) == target:
        return comp
    ch = getattr(comp, "children", None)
    if ch is not None:
        for c in (ch if isinstance(ch, (list, tuple)) else [ch]):
            if c is not None:
                found = _find_by_id(c, target)
                if found is not None:
                    return found
    return None


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

    def test_full_page_chat_agent_must_be_query_first(self):
        # A full-page chat handler (agent supplied in chat= with no app callback)
        # must be query-first; the error is ASCII.
        def bot(prompt, ctx):
            yield "hi"
        with pytest.raises(TypeError) as ei:
            FastDash(chat=bot)
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
        # Make 'old' look ancient and force a sweep independent of the machine's
        # monotonic-clock base: eviction compares (now - last_seen) to the TTL,
        # and a freshly-booted CI runner starts near 0, so last_seen=0 is NOT
        # necessarily older than the 6h TTL. A large-negative base always is.
        old.last_seen = -1e12
        app._last_sweep = -1e12                        # force a sweep next call
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
        specs = app_tool_specs(["a", "b"])                # bare names still work
        assert {t["name"] for t in specs} == {"set_input", "run_app"}
        set_tool = next(t for t in specs if t["name"] == "set_input")
        assert set_tool["input_schema"]["properties"]["name"]["enum"] == ["a", "b"]
        assert apply_tool_call({"name": "set_input", "input": {"name": "a", "value": 3}}) == \
            {"type": "set_input", "name": "a", "value": 3}
        assert apply_tool_call({"name": "run_app", "input": {}}) == {"type": "run_app"}

    def test_app_tool_specs_from_contract_is_typed(self):
        # Given the input contract, set_input enumerates targets and describes
        # each one's type + allowed options (so the model sends valid values).
        from fast_dash import app_tool_specs
        contract = [
            {"id": "revenue", "type": "integer"},
            {"id": "region", "type": "string", "options": ["N", "S"]},
        ]
        name = app_tool_specs(contract)[0]["input_schema"]["properties"]["name"]
        assert name["enum"] == ["revenue", "region"]
        assert "region: string (one of: N, S)" in name["description"]


class TestChatSidecar:
    """chat=<agent> on an app callback: an independent chat agent sidecar."""

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
        app = FastDash(callback_fn=dashboard, chat=agent, chat_title="Helper")
        assert app.has_chat_sidecar is True
        assert app.chat_title == "Helper"
        ids = _layout_ids(app.app.layout)
        # The normal output surface AND the collapsible chat panel both exist.
        assert "output-group-col" in ids
        assert {"chat-messages", "chat-input", "chat-send",
                "chat-sidebar-panel", "chat-panel-collapse"} <= ids
        # No floating aside / toggle in 0.6.0 (sidebar is the only placement).
        assert "chat-aside" not in ids and "chat-sidecar-toggle" not in ids

    def test_chat_placeholder_default_and_override(self):
        # The empty-transcript hint (CSS reads data-placeholder) fits the mode:
        # a pure chat is a conversation, a sidecar drives the output. Overridable.
        def _placeholder(app):
            found = []
            def walk(c):
                if getattr(c, "id", None) == "chat-messages":
                    found.append(c)
                ch = getattr(c, "children", None)
                for x in (ch if isinstance(ch, (list, tuple)) else [ch]) if ch is not None else []:
                    if hasattr(x, "children") or hasattr(x, "id"):
                        walk(x)
            walk(app.app.layout)
            return found[0].to_plotly_json()["props"].get("data-placeholder")

        pure = FastDash(callback_fn=lambda query: query, chat=True)
        assert _placeholder(pure) == "Send a message to start the conversation."

        def dfn(a: int = 1) -> str:
            return str(a)
        side = FastDash(callback_fn=dfn, chat=lambda query, ctx: (yield "hi"))
        assert _placeholder(side) == "Ask the assistant to change the output."

        custom = FastDash(callback_fn=lambda query: query, chat=True,
                          chat_placeholder="Add a source, then ask.")
        assert _placeholder(custom) == "Add a source, then ask."

    def test_sidecar_chat_is_stacked_in_navbar_with_collapse_affordance(self):
        # The sidecar chat is stacked under the inputs in the left navbar and is
        # collapsible (the panel + a collapse chevron live inside the navbar).
        def dashboard(a: int = 1) -> str:
            return str(a)
        app = FastDash(callback_fn=dashboard,
                       chat=lambda query, ctx: (yield "hi"))
        ids = _layout_ids(app.app.layout)
        assert {"chat-messages", "chat-input", "chat-send",
                "chat-panel-collapse", "chat-panel-collapse-icon"} <= ids
        assert "chat-aside" not in ids                               # no right aside
        assert "chat-sidecar-toggle" not in ids                      # no float toggle
        # the transcript + collapse affordance are inside the navbar container
        navbar = _find_by_id(app.app.layout, "navbar3260780")
        navbar_ids = _layout_ids(navbar)
        assert "chat-messages" in navbar_ids
        assert "chat-panel-collapse" in navbar_ids

    def test_collapse_callback_toggles_panel_and_navbar_classnames(self):
        # The collapse affordance is wired to a clientside callback that flips a
        # className on the panel section and the navbar root.
        def dashboard(a: int = 1) -> str:
            return str(a)
        app = FastDash(callback_fn=dashboard,
                       chat=lambda query, ctx: (yield "hi"))
        wired = {"panel": False, "navbar": False}
        for out_key, spec in app.app.callback_map.items():
            inputs = [f"{i['id']}.{i['property']}" for i in spec.get("inputs", [])]
            if not any("chat-panel-collapse.n_clicks" in x for x in inputs):
                continue
            if "chat-sidebar-panel.className" in out_key:
                wired["panel"] = True
            if "appshell.className" in out_key:
                wired["navbar"] = True
        assert wired["panel"], "collapse must toggle the panel section className"
        assert wired["navbar"], "collapse must toggle the navbar root className"

    def test_plain_app_has_no_chat_dom(self):
        app = FastDash(callback_fn=lambda x: "hi")
        ids = _layout_ids(app.app.layout)
        assert "chat-messages" not in ids and "chat-sidebar-panel" not in ids

    def test_two_chat_handlers_are_rejected(self):
        # A chat-shaped callback AND an agent in chat= is ambiguous.
        def agent(query, ctx):
            yield "x"
        with pytest.raises(TypeError, match="[Tt]wo chat handlers"):
            FastDash(callback_fn=lambda query: "hi", chat=agent)

    def test_agent_must_be_query_first(self):
        def bad_agent(message, ctx):
            yield "x"
        with pytest.raises(TypeError, match="first parameter must be named 'query'"):
            FastDash(callback_fn=lambda a: a, chat=bad_agent)

    def test_turn_streams_and_records_history_independently(self):
        seen = {}
        def dashboard(a: int = 1) -> str:
            seen["ran"] = True                 # must NOT run on a chat turn
            return str(a)
        def agent(query, ctx):
            yield f"echo: {query}"
        app = FastDash(callback_fn=dashboard, chat=agent)
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
        app = FastDash(callback_fn=dashboard, chat=agent)
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
        app = FastDash(callback_fn=dashboard, chat=agent)
        ops = self._ops(app, "go", app_inputs={"a": 1, "b": 2})
        drive = [p for ev, p in ops if ev == "chat_drive"]
        # set_input a -> [10, 2]; set_input b -> [10, 20]; run_app -> outputs.
        assert drive[0]["inputs"] == [10, 2]
        assert drive[1]["inputs"] == [10, 20]
        assert drive[2]["outputs"] == ["sum=30"]
        # The run_app op carries the full inputs too, so the latest-wins
        # data-chat_drive prop can't clobber the set_inputs made this turn.
        assert drive[2]["inputs"] == [10, 20]

    def test_run_app_clears_pre_run_placeholder_flask(self):
        # A sidecar run_app writes the outputs, but the "Run to see results"
        # placeholder (fd-not-run on #output-group-col) is otherwise only cleared
        # by a manual Run (submit_inputs.n_clicks) -- so the agent's run left the
        # outputs written-but-hidden. The Flask drive reducer must also clear the
        # placeholder from the same chat_drive op.
        def dashboard(a: int = 1) -> str:
            return str(a)
        def agent(query, ctx):
            yield {"type": "run_app"}
        app = FastDash(callback_fn=dashboard, chat=agent)
        wired = False
        for out_key, spec in app.app.callback_map.items():
            if "output-group-col.className" not in out_key:
                continue
            inputs = [f"{i['id']}.{i['property']}" for i in spec.get("inputs", [])]
            if any("data-chat_drive" in x for x in inputs):
                wired = True
        assert wired, "drive reducer must clear output-group-col on a run"

    def test_drive_on_asgi_uses_set_props(self):
        import dash
        def dashboard(a: int = 1, b: int = 2) -> str:
            return f"sum={a + b}"
        def agent(query, ctx):
            yield {"type": "set_input", "name": "a", "value": 7}
            yield {"type": "run_app"}
        app = FastDash(callback_fn=dashboard, chat=agent)
        app._native_stream = True
        calls = []
        with mock.patch.object(dash, "set_props",
                               lambda cid, props: calls.append((cid, props))):
            app._run_chat_turn("go", "s1", None, (), app_inputs={"a": 1, "b": 2})
        non_transcript = [(c, p) for c, p in calls if c != "chat-messages"]
        assert ("a", {"value": 7}) in non_transcript
        # The single output component was updated with sum=9.
        assert any(list(p.values()) == ["sum=9"] for _, p in non_transcript)
        # ...and the pre-run "Run to see results" placeholder is cleared, so the
        # run reveals the outputs instead of leaving them hidden (issue: sidecar
        # run_app drove inputs but never rendered the view).
        assert ("output-group-col", {"className": ""}) in non_transcript

    def test_sidecar_on_multi_is_conversational_and_guards_drive(self):
        def f1(x: int = 1) -> str: return f"f1={x}"
        def f2(y: int = 2) -> str: return f"f2={y}"
        def agent(query, ctx):
            yield {"type": "set_input", "name": "x", "value": 9}
            yield {"type": "run_app"}
        app = FastDash(callback_fn=[f1, f2], chat=agent)
        assert app.has_chat_sidecar and app._chat_input_mode == "none"
        assert app._sidecar_can_drive is False
        # A multi-surface app trims chat_tools to read_app only.
        assert set(app.chat_tools_config) == {"read_app"}
        ids = _layout_ids(app.app.layout)
        assert {"chat-messages", "multi-function-tabs"} <= ids
        self._ops(app, "go")
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "multiple surfaces" in reply         # drive deflected, not fatal

    @requires_langstage
    def test_langgraph_graph_as_sidecar(self):
        def dashboard(a: int = 1) -> str:
            return str(a)
        app = FastDash(callback_fn=dashboard,
                       chat="langstage_core.demo.stub:graph")
        assert app.has_chat_sidecar and app.is_langstage
        self._ops(app, "hello there")
        assert "hello there" in app.chat_history.get("s1")[-1]["content"]

    def test_ctx_input_specs_carries_the_typed_contract(self):
        # A1: the agent sees the host app's input contract (types + options).
        from typing import Literal
        seen = {}
        def dashboard(revenue: int = 1, region: Literal["N", "S"] = "N") -> str:
            return "x"
        def agent(query, ctx):
            seen["specs"] = ctx.input_specs
            yield "ok"
        app = FastDash(callback_fn=dashboard, chat=agent)
        self._ops(app, "hi", app_inputs={"revenue": 1, "region": "N"})
        by_id = {s["id"]: s for s in seen["specs"]}
        assert by_id["revenue"]["type"] == "integer"
        assert by_id["region"]["options"] == ["N", "S"]

    def test_run_app_updates_server_output_state(self):
        # A2: the agent's run mirrors a manual Run server-side.
        def dashboard(a: int = 1, b: int = 2) -> str:
            return f"sum={a + b}"
        def agent(query, ctx):
            yield {"type": "set_input", "name": "a", "value": 5}
            yield {"type": "run_app"}
        app = FastDash(callback_fn=dashboard, chat=agent)
        assert app.app_initialized is False
        self._ops(app, "go", app_inputs={"a": 1, "b": 2})
        assert app.output_state == ["sum=7"]
        assert app.app_initialized is True

    def test_update_live_disables_drive_with_warning(self):
        # A3: driving an update_live app would double-run, so chat_tools trims
        # the drive verbs (with a warning) and the agent is read-only there.
        def dashboard(x: int = 1) -> str:
            return str(x)
        def agent(query, ctx):
            yield {"type": "set_input", "name": "x", "value": 9}
        with pytest.warns(UserWarning, match="double-run"):
            app = FastDash(callback_fn=dashboard, chat=agent, update_live=True)
        assert app._sidecar_can_drive is False
        assert "set_input" not in app.chat_tools_config
        self._ops(app, "go", app_inputs={"x": 1})
        assert "read-only" in app.chat_history.get("s1")[-1]["content"]

    def test_host_callback_lock_is_present(self):
        # A4: one lock serializes the user's Run and the agent's run_app.
        import _thread
        def dashboard(a: int = 1) -> str:
            return str(a)
        def agent(query, ctx):
            yield "ok"
        app = FastDash(callback_fn=dashboard, chat=agent)
        assert isinstance(app._host_callback_lock, type(_thread.allocate_lock()))

    def test_read_only_tools_refuse_drive(self):
        # #5: read-only opt-out via chat_tools — the agent still reads ctx.inputs
        # but its set_input / run_app are refused (no drive verbs in allowlist).
        seen = {}
        def dashboard(a: int = 1) -> str:
            return str(a)
        def agent(query, ctx):
            seen["inputs"] = dict(ctx.inputs)
            yield {"type": "set_input", "name": "a", "value": 9}
        app = FastDash(callback_fn=dashboard, chat=agent,
                       chat_tools=("read_app",))
        assert app._sidecar_can_drive is False
        self._ops(app, "go", app_inputs={"a": 5})
        assert seen["inputs"] == {"a": 5}                  # read still works
        assert "read-only" in app.chat_history.get("s1")[-1]["content"]

    def test_empty_tools_refuse_drive(self):
        # chat_tools=() -> a do-nothing agent: no read/drive verbs at all.
        def dashboard(a: int = 1) -> str:
            return str(a)
        def agent(query, ctx):
            yield {"type": "run_app"}
        app = FastDash(callback_fn=dashboard, chat=agent, chat_tools=())
        assert app.chat_tools_config == {}
        assert app._sidecar_can_drive is False
        self._ops(app, "go", app_inputs={"a": 1})
        assert app.app_initialized is False               # run_app was refused

    def test_input_names_come_from_inputs_with_ids(self):
        # #6: names are derived from inputs_with_ids (the same source as the
        # contract + set_input enum), not a positional guess off the signature.
        from fast_dash.mcp import _stringify_id
        def dashboard(revenue: int = 1, region: str = "N") -> str:
            return "x"
        def agent(query, ctx):
            yield "x"
        app = FastDash(callback_fn=dashboard, chat=agent)
        expected = [_stringify_id(i.id) for i in app.inputs_with_ids]
        assert app._chat_input_names == expected
        assert [s["id"] for s in app._sidecar_contract] == expected

    def test_set_input_validates_against_contract_options(self):
        # F1 (from dogfood): an invalid value / unknown input is refused with an
        # actionable message, and run_app then runs on the still-valid current
        # value — no raw callback exception reaches the user.
        from typing import Literal
        def dashboard(region: Literal["North", "South", "All"] = "All") -> str:
            return f"r={region}"
        def agent(query, ctx):
            yield {"type": "set_input", "name": "region", "value": "Central"}
            yield {"type": "set_input", "name": "ghost", "value": 1}
            yield {"type": "run_app"}
        app = FastDash(callback_fn=dashboard, chat=agent)
        self._ops(app, "go", app_inputs={"region": "All"})
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "isn't a valid value for 'region'" in reply
        assert "No input named 'ghost'" in reply
        assert "Error running the app" not in reply       # no raw exception
        assert app.output_state == ["r=All"]              # ran with the valid value

    def test_set_input_rejects_wrong_type(self):
        # OI-A (from Stage-3 dogfood): a wrong-type value is refused (not silently
        # coerced to garbage); run_app then runs on the valid current value.
        def dashboard(n: int = 1) -> str:
            return f"n={n}"
        def agent(query, ctx):
            yield {"type": "set_input", "name": "n", "value": "not-a-number"}
            yield {"type": "run_app"}
        app = FastDash(callback_fn=dashboard, chat=agent)
        self._ops(app, "go", app_inputs={"n": 1})
        assert "isn't a valid integer for 'n'" in app.chat_history.get("s1")[-1]["content"]
        assert app.output_state == ["n=1"]

    def test_malformed_frame_does_not_wedge_the_turn(self):
        # R2 (ship review): a malformed known-type frame is a developer bug, but
        # it must not abort the turn mid-stream (which stranded the streaming
        # bubble and left the composer disabled). The partial reply is kept, the
        # bug is surfaced in the transcript, and the next turn works.
        def bad_agent(query, ctx):
            yield "partial "
            yield {"type": "content"}                     # missing 'content' key
        app = FastDash(callback_fn=lambda a=1: a, chat=bad_agent)
        self._ops(app, "go", app_inputs={"a": 1})         # must not raise
        reply = app.chat_history.get("s1")[-1]["content"]
        assert reply.startswith("partial ")               # partial text kept
        assert "Malformed chat frame" in reply            # bug surfaced loudly
        assert app._session("s1").active is False
        self._ops(app, "again", app_inputs={"a": 1})      # session not poisoned
        assert len(app.chat_history.get("s1")) == 4

    def test_password_inputs_are_hidden_and_unsettable(self):
        # Security: a PasswordInput's value is redacted from ctx.inputs and the
        # contract, and set_input on it is refused — but run_app still runs the
        # callback with the real value.
        from fast_dash import PasswordInput
        seen = {}
        def app_fn(pwd: PasswordInput = "hunter2", n: int = 5) -> str:
            return f"pwd={pwd} n={n}"
        def agent(query, ctx):
            seen["inputs"] = dict(ctx.inputs)
            seen["spec_ids"] = [s.get("id") for s in ctx.input_specs]
            yield {"type": "set_input", "name": "pwd", "value": "leaked"}
            yield {"type": "set_input", "name": "n", "value": 9}
            yield {"type": "run_app"}
        app = FastDash(callback_fn=app_fn, chat=agent)
        self._ops(app, "go", app_inputs={"pwd": "hunter2", "n": 5})
        assert seen["inputs"] == {"pwd": "***", "n": 5}   # value never reaches the agent
        assert "pwd" not in seen["spec_ids"]              # not advertised as a target
        assert "can't set the 'pwd' field" in app.chat_history.get("s1")[-1]["content"]
        assert app.output_state == ["pwd=hunter2 n=9"]    # run_app used the real value


class TestSetOutputSetLayoutFrames:
    """set_output / set_layout frame normalization (RFC #145 Phase C)."""

    def test_set_output_frame_normalizes(self):
        f = _normalize_frame({"type": "set_output", "slot": "a", "value": 5})
        assert f == {"type": "set_output", "slot": "a", "value": 5}

    def test_set_output_requires_slot(self):
        with pytest.raises(ChatFrameError):
            _normalize_frame({"type": "set_output", "value": 5})

    def test_set_output_keeps_rich_value_raw(self):
        # A rich payload survives normalization untouched (transformed later
        # server-side), unlike an artifact which becomes a placeholder.
        import plotly.graph_objects as go
        fig = go.Figure()
        f = _normalize_frame({"type": "set_output", "slot": "a", "value": fig})
        assert f["value"] is fig

    def test_set_layout_frame_normalizes(self):
        f = _normalize_frame({"type": "set_layout", "mosaic": "AB"})
        assert f == {"type": "set_layout", "mosaic": "AB"}

    def test_set_layout_requires_mosaic(self):
        with pytest.raises(ChatFrameError):
            _normalize_frame({"type": "set_layout"})


def _two_output_sidecar(agent, **kw):
    """A two-output dashboard with a sidecar agent (stable slots A and B)."""
    from fast_dash import Text

    def dashboard(a: int = 1, b: int = 2):
        return f"x{a}", f"y{b}"
    return FastDash(callback_fn=dashboard, chat=agent, outputs=[Text, Text], **kw)


class TestStableSlotIdentity:
    """Each leaf output card sits in a stable fd-slot-<letter> wrapper."""

    def test_default_layout_has_slot_ids_and_preserves_leaf_ids(self):
        app = _two_output_sidecar(lambda query, ctx: (yield "hi"))
        ids = _layout_ids(app.app.layout)
        assert {"fd-slot-A", "fd-slot-B"} <= ids
        # The leaf component ids (which registered callbacks target) are intact.
        leaf_ids = {c.id for c in app.outputs_with_ids}
        assert leaf_ids <= ids

    def test_slot_letters_are_reported(self):
        app = _two_output_sidecar(lambda query, ctx: (yield "hi"))
        assert app.layout_object.output_slot_letters == ["A", "B"]


class TestRebuildOutputLayout:
    """rebuild_output_layout re-parents the same leaves and validates (SPEC O2)."""

    def _find_slot_leaf(self, comp, letter):
        if getattr(comp, "id", None) == f"fd-slot-{letter}":
            return comp.children[0]
        ch = getattr(comp, "children", None)
        if ch is not None:
            for c in (ch if isinstance(ch, (list, tuple)) else [ch]):
                if c is not None:
                    r = self._find_slot_leaf(c, letter)
                    if r is not None:
                        return r
        return None

    def test_valid_mosaic_reparents_same_leaf_objects(self):
        app = _two_output_sidecar(lambda query, ctx: (yield "hi"))
        lo = app.layout_object
        tree, reason = lo.rebuild_output_layout("A\nB")   # stack vertically
        assert reason is None
        # The SAME leaf card objects (from the mapper) are re-parented.
        assert self._find_slot_leaf(tree, "A") is lo.output_component_mapper["A"]
        assert self._find_slot_leaf(tree, "B") is lo.output_component_mapper["B"]
        ids = _layout_ids(tree)
        assert {"fd-slot-A", "fd-slot-B"} <= ids           # structure matches mosaic

    def test_superset_letter_is_refused(self):
        app = _two_output_sidecar(lambda query, ctx: (yield "hi"))
        tree, reason = app.layout_object.rebuild_output_layout("ABC")
        assert tree is None
        assert reason is not None and reason.isascii()
        assert "Unknown slot" in reason and "C" in reason

    def test_non_rectangular_is_refused(self):
        app = _two_output_sidecar(lambda query, ctx: (yield "hi"))
        tree, reason = app.layout_object.rebuild_output_layout("AB\nBA")
        assert tree is None
        assert reason is not None and reason.isascii()
        assert "rectangular" in reason or "contiguous" in reason


class TestSetOutputDispatch:
    """set_output frame renders through the transform + pushes per-client."""

    def _drive_ops(self, app, agent_frames, sid="s1", app_inputs=None):
        def agent(query, ctx):
            for f in agent_frames:
                yield f
        app._chat_fn = agent
        ops = []
        with mock.patch("flask_socketio.emit",
                        side_effect=lambda ev, payload=None, **k: ops.append((ev, payload))):
            app._run_chat_turn("go", sid, "sock", (), app_inputs=app_inputs)
        return [p for ev, p in ops if ev == "chat_drive"]

    def test_set_output_transforms_and_pushes_flask(self):
        # A DataFrame value must be transformed (records) the way a Run would,
        # then pushed to the target leaf via a 'set_output' op with a flash.
        import pandas as pd
        from fast_dash import Table

        def dashboard(a: int = 1):
            return pd.DataFrame({"x": [1]})
        app = FastDash(callback_fn=dashboard, chat=lambda query, ctx: (yield "hi"),
                       outputs=Table)
        drive = self._drive_ops(app, [
            {"type": "set_output", "slot": "a",
             "value": pd.DataFrame({"x": [1, 2]})}])
        assert len(drive) == 1
        op = drive[0]
        assert op["op"] == "set_output"
        assert op["prop"] == "data"                     # Table -> data prop
        assert op["value"] == [{"x": 1}, {"x": 2}]      # transformed to records
        assert op["id"] == app.outputs_with_ids[0].id
        assert op["ran"] is True                        # fires the drive flash

    def test_set_output_invalid_slot_refuses_with_valid_list(self):
        def dashboard(a: int = 1) -> str:
            return str(a)
        app = FastDash(callback_fn=dashboard, chat=lambda query, ctx: (yield "hi"))
        self._drive_ops(app, [
            {"type": "set_output", "slot": "z", "value": "x"}])
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "No output slot 'z'" in reply
        assert "Valid slots: A" in reply

    def test_set_output_on_asgi_uses_set_props(self):
        import dash
        from fast_dash import Text

        def dashboard(a: int = 1) -> str:
            return str(a)
        app = FastDash(callback_fn=dashboard, chat=lambda query, ctx: (yield "hi"),
                       outputs=Text)
        app._native_stream = True
        calls = []

        def agent(query, ctx):
            yield {"type": "set_output", "slot": "a", "value": "hello"}
        app._chat_fn = agent
        with mock.patch.object(dash, "set_props",
                               lambda cid, props: calls.append((cid, props))):
            app._run_chat_turn("go", "s1", None, (), app_inputs={"a": 1})
        non_transcript = [(c, p) for c, p in calls if c != "chat-messages"]
        leaf_id = app.outputs_with_ids[0].id
        assert (leaf_id, {app.outputs_with_ids[0].component_property: "hello"}) \
            in non_transcript
        assert ("output-group-col", {"className": ""}) in non_transcript


class TestSetLayoutDispatch:
    """set_layout frame re-mosaics and pushes new children per-client."""

    def _drive_ops(self, app, agent, sid="s1", app_inputs=None):
        app._chat_fn = agent
        ops = []
        with mock.patch("flask_socketio.emit",
                        side_effect=lambda ev, payload=None, **k: ops.append((ev, payload))):
            app._run_chat_turn("go", sid, "sock", (), app_inputs=app_inputs)
        return [p for ev, p in ops if ev == "chat_drive"]

    def test_valid_layout_pushes_tree_flask(self):
        def agent(query, ctx):
            yield {"type": "set_layout", "mosaic": "A\nB"}
        app = _two_output_sidecar(agent)
        drive = self._drive_ops(app, agent)
        assert len(drive) == 1 and drive[0]["op"] == "layout"
        tree = drive[0]["tree"]
        # Serialized Dash component JSON (JSON-safe); wraps the mosaic.
        assert json.dumps(tree)                          # JSON-safe on the wire
        assert tree["props"]["id"] == "output-loading-wrap"

    def test_invalid_layout_refuses_with_reason(self):
        def agent(query, ctx):
            yield {"type": "set_layout", "mosaic": "ABC"}
        app = _two_output_sidecar(agent)
        drive = self._drive_ops(app, agent)
        assert drive == []                               # nothing pushed
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "Unknown slot" in reply

    def test_set_layout_on_asgi_pushes_children(self):
        import dash

        def agent(query, ctx):
            yield {"type": "set_layout", "mosaic": "A\nB"}
        app = _two_output_sidecar(agent)
        app._native_stream = True
        calls = []
        with mock.patch.object(dash, "set_props",
                               lambda cid, props: calls.append((cid, props))):
            app._run_chat_turn("go", "s1", None, (), app_inputs={"a": 1, "b": 2})
        pushes = [(c, p) for c, p in calls if c == "output-group-col"]
        assert any("children" in p for _, p in pushes)   # full-state children push


class TestChatToolsGatingForLayout:
    """set_output / set_layout honor the chat_tools allowlist."""

    def _run(self, app, agent, sid="s1", app_inputs=None):
        app._chat_fn = agent
        with mock.patch("flask_socketio.emit"):
            app._run_chat_turn("go", sid, "sock", (), app_inputs=app_inputs)

    def test_set_layout_disabled_by_chat_tools_refuses(self):
        # chat_tools without set_layout -> the frame is refused with the SPEC
        # per-verb note (the app is otherwise drivable via run_app).
        def agent(query, ctx):
            yield {"type": "set_layout", "mosaic": "A\nB"}
        app = _two_output_sidecar(agent, chat_tools=("read_app", "run_app"))
        self._run(app, agent, app_inputs={"a": 1, "b": 2})
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "set_layout capability is disabled" in reply

    def test_set_output_disabled_by_chat_tools_refuses(self):
        def agent(query, ctx):
            yield {"type": "set_output", "slot": "a", "value": "x"}
        app = _two_output_sidecar(agent, chat_tools=("read_app", "run_app"))
        self._run(app, agent, app_inputs={"a": 1, "b": 2})
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "set_output capability is disabled" in reply


class TestRunAlwaysWins:
    """Default-layout store + Run-reset clientside callback (SPEC)."""

    def test_default_layout_store_present_when_sidecar_and_set_layout_allowed(self):
        app = _two_output_sidecar(lambda query, ctx: (yield "hi"))
        ids = _layout_ids(app.app.layout)
        assert "fd-default-layout" in ids
        # It carries the serialized default tree (JSON-safe, the loader wrap).
        store = _find_by_id(app.app.layout, "fd-default-layout")
        data = store.to_plotly_json()["props"]["data"]
        assert data["props"]["id"] == "output-loading-wrap"
        assert json.dumps(data)                          # JSON-safe

    def test_default_layout_store_absent_without_set_layout(self):
        app = _two_output_sidecar(lambda query, ctx: (yield "hi"),
                                  chat_tools=("read_app", "run_app"))
        ids = _layout_ids(app.app.layout)
        assert "fd-default-layout" not in ids

    def test_default_layout_store_absent_on_plain_app(self):
        app = FastDash(callback_fn=lambda a=1: str(a))
        ids = _layout_ids(app.app.layout)
        assert "fd-default-layout" not in ids

    def test_run_reset_callback_is_registered(self):
        # A clientside callback on submit_inputs.n_clicks restores
        # output-group-col.children from the store (children only, not className).
        app = _two_output_sidecar(lambda query, ctx: (yield "hi"))
        wired = False
        for out_key, spec in app.app.callback_map.items():
            if "output-group-col.children" not in out_key:
                continue
            inputs = [f"{i['id']}.{i['property']}" for i in spec.get("inputs", [])]
            states = [f"{s['id']}.{s['property']}" for s in spec.get("state", [])]
            if any("submit_inputs.n_clicks" in x for x in inputs) \
                    and any("fd-default-layout.data" in x for x in states):
                wired = True
        assert wired, "Run-reset must restore output-group-col.children from the store"

    def test_run_reset_never_touches_classname(self):
        # The restore sets children only; the fd-not-run machinery owns
        # output-group-col.className on the same submit_inputs trigger.
        app = _two_output_sidecar(lambda query, ctx: (yield "hi"))
        for out_key, spec in app.app.callback_map.items():
            inputs = [f"{i['id']}.{i['property']}" for i in spec.get("inputs", [])]
            if not any("submit_inputs.n_clicks" in x for x in inputs):
                continue
            # No single callback both restores children AND sets className.
            if "output-group-col.children" in out_key:
                assert "output-group-col.className" not in out_key


# --------------------------------------------------------------------------- #
# Round 3: auto-agent end-to-end (chat=True + app-shaped callback)
# --------------------------------------------------------------------------- #

def _scripted_tool_model(responses):
    """A streaming, tool-binding fake chat model that replays ``responses``.

    Each item is an ``AIMessage`` (plain content, or ``tool_calls=[...]``). The
    ``_stream`` path emits ``tool_call_chunks`` so ``create_react_agent`` +
    the langstage AG-UI bridge consume tool calls the way a real model would --
    GenericFakeChatModel cannot stream tool-call-only (empty-content) messages,
    which is exactly what the drive path needs, so this fake fills that gap.
    """
    import json as _json

    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

    class _ScriptedToolFake(BaseChatModel):
        responses: list
        i: int = 0

        @property
        def _llm_type(self):
            return "scripted-tool-fake"

        def bind_tools(self, tools, **kwargs):
            return self                                 # tools drive via the toolkit

        def _next(self):
            msg = self.responses[min(self.i, len(self.responses) - 1)]
            self.i += 1
            return msg

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[ChatGeneration(message=self._next())])

        def _stream(self, messages, stop=None, run_manager=None, **kwargs):
            msg = self._next()
            if msg.tool_calls:
                for idx, tc in enumerate(msg.tool_calls):
                    yield ChatGenerationChunk(message=AIMessageChunk(
                        content="", tool_call_chunks=[{
                            "name": tc["name"], "args": _json.dumps(tc["args"]),
                            "id": tc["id"], "index": idx}]))
            else:
                yield ChatGenerationChunk(message=AIMessageChunk(content=msg.content))

    return _ScriptedToolFake(responses=list(responses))


@requires_auto_agent
class TestAutoAgentEndToEnd:
    """chat=True on an app-shaped callback auto-builds an assistant and streams
    a full turn through the sidecar loop (build_auto_agent -> langstage bridge).
    """

    def _ops(self, app, query, sid="s1", app_inputs=None):
        ops = []
        with mock.patch("flask_socketio.emit",
                        side_effect=lambda ev, p=None, **k: ops.append((ev, p))):
            app._run_chat_turn(query, sid, "sock", (), app_inputs=app_inputs)
        return ops

    def test_plain_text_turn_completes(self):
        # A fake model that just answers with text: the auto-agent is built on
        # first use, bridged through langstage, and the reply reaches history.
        from langchain_core.messages import AIMessage
        def dashboard(revenue: int = 100) -> str:
            """A revenue dashboard."""
            return f"rev {revenue}"
        model = _scripted_tool_model([AIMessage(content="Here is your answer.")])
        app = FastDash(callback_fn=dashboard, chat=True, chat_model=model)
        assert app.has_chat_sidecar is True
        assert app.is_langstage is True               # bridged, so HITL wires
        # The placeholder is built lazily -- not until the first turn runs.
        assert app._chat_fn.__class__.__name__ == "_AutoAgentPlaceholder"
        self._ops(app, "hi", app_inputs={"revenue": 100})
        assert app.chat_history.get("s1")[-1]["content"] == "Here is your answer."

    def test_tool_call_set_input_then_run_app_drives_the_app(self):
        # The model emits a set_input tool call then a run_app tool call; the
        # toolkit executes them, their frames drain to the sidecar, the host
        # callback runs, and the output is pushed -- a full agentic drive.
        from langchain_core.messages import AIMessage
        def dashboard(a: int = 1, b: int = 2) -> str:
            return f"sum={a + b}"
        model = _scripted_tool_model([
            AIMessage(content="", tool_calls=[
                {"name": "set_input", "args": {"name": "a", "value": 10}, "id": "c1"}]),
            AIMessage(content="", tool_calls=[
                {"name": "run_app", "args": {}, "id": "c2"}]),
            AIMessage(content="I set a to 10 and ran the app."),
        ])
        app = FastDash(callback_fn=dashboard, chat=True, chat_model=model)
        ops = self._ops(app, "set a to 10 and run", app_inputs={"a": 1, "b": 2})
        drive = [p for ev, p in ops if ev == "chat_drive"]
        # set_input -> inputs [10, 2]; run_app -> outputs computed with a=10.
        assert any(d.get("inputs") == [10, 2] for d in drive)
        assert any(d.get("outputs") == ["sum=12"] and d.get("ran") for d in drive)
        assert app.output_state == ["sum=12"]         # server state mirrored
        assert app.chat_history.get("s1")[-1]["content"].startswith("I set a to 10")

    def test_model_instance_is_not_mistaken_for_a_graph(self):
        # A chat model is a LangChain Runnable, so it carries get_graph +
        # astream just like a compiled graph -- but it also has bind_tools. It
        # must route to the auto-agent builder, NOT the langstage graph path
        # (which would crash trying to read the model's non-existent .nodes).
        from langchain_core.messages import AIMessage
        model = _scripted_tool_model([AIMessage(content="via model instance")])
        # Full-page: model in chat=, no app callback.
        full = FastDash(chat=model)
        assert full.is_chat and not full.has_chat_sidecar
        self._ops(full, "hi")
        assert full.chat_history.get("s1")[-1]["content"] == "via model instance"
        # Sidecar: model in chat= alongside an app callback.
        def dashboard(a: int = 1) -> str:
            return str(a)
        side = FastDash(callback_fn=dashboard,
                        chat=_scripted_tool_model([AIMessage(content="beside the app")]))
        assert side.has_chat_sidecar
        self._ops(side, "hi", sid="s2", app_inputs={"a": 1})
        assert side.chat_history.get("s2")[-1]["content"] == "beside the app"

    def test_tool_call_respects_chat_tools_refusal(self):
        # With run_app trimmed from chat_tools, the toolkit doesn't even expose
        # it -- so a model that (somehow) tried to drive is limited to reading.
        # The server-side allowlist is the choke point; here we prove the
        # toolkit surface itself is trimmed for the auto-agent's app.
        import fast_dash.agent_tools as AT
        from langchain_core.messages import AIMessage
        def dashboard(a: int = 1) -> str:
            return str(a)
        model = _scripted_tool_model([AIMessage(content="read-only here")])
        app = FastDash(callback_fn=dashboard, chat=True, chat_model=model,
                       chat_tools=("read_app",))
        assert app._sidecar_can_drive is False
        names = {t.name for t in AT.agent_toolkit(app)}
        assert names == {"read_app"}                  # no drive verbs advertised
        self._ops(app, "hi", app_inputs={"a": 1})
        assert app.chat_history.get("s1")[-1]["content"] == "read-only here"


def _run_python_hitl_graph(code):
    """A langstage sidecar graph that interrupts for run_python approval, then
    executes (or edits / rejects) the code via the real agent_tools engine.

    Mirrors ``_interrupt_graph`` but exercises the run_python HITL contract at
    the frame level: the interrupt payload is the toolkit's own payload, and the
    decision drives the toolkit's own exec/read helpers -- so approve executes,
    reject denies, edit runs the replacement.
    """
    import fast_dash.agent_tools as AT
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.types import interrupt

    def gate(state):
        decision = interrupt(AT._run_python_interrupt_payload(code))
        verdict, edited = AT._read_decision(decision, code)
        if verdict == "reject":
            return {"messages": [AIMessage(content="User denied execution.")]}
        res = AT._exec_python(edited, "hitl-thread")
        return {"messages": [AIMessage(content=AT._summarize_py_result(res))]}

    g = StateGraph(MessagesState)
    g.add_node("gate", gate)
    g.add_edge(START, "gate")
    g.add_edge("gate", END)
    return g.compile(checkpointer=InMemorySaver())


@requires_auto_agent
class TestSidecarRunPythonHitl:
    """run_python approval, at the frame level, in SIDECAR mode.

    TestChatHitl covers the pause/resume mechanics in full-page chat mode; this
    extends it to a chat sidecar on a normal app, and asserts the observable
    exec side effect of each decision (approve / reject / edit).
    """

    def _pause(self, app, sid="s1"):
        with mock.patch("flask_socketio.emit"):
            app._run_chat_turn("run it", sid, "sock", (), app_inputs={"a": 1})

    def test_approve_executes_the_code(self):
        def dashboard(a: int = 1) -> str:
            return str(a)
        app = FastDash(callback_fn=dashboard,
                       chat=_run_python_hitl_graph("print('EXECUTED'); 21 * 2"))
        assert app.has_chat_sidecar and app.is_langstage
        self._pause(app)
        assert app._session("s1").pending is not None
        with mock.patch("flask_socketio.emit"):
            app._resume_chat_turn("s1", "sock", "approve")
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "EXECUTED" in reply and "42" in reply   # code ran, result captured
        assert app._session("s1").pending is None

    def test_reject_denies_without_executing(self):
        def dashboard(a: int = 1) -> str:
            return str(a)
        app = FastDash(callback_fn=dashboard,
                       chat=_run_python_hitl_graph("print('SHOULD_NOT_RUN')"))
        self._pause(app)
        with mock.patch("flask_socketio.emit"):
            app._resume_chat_turn("s1", "sock", "reject")
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "denied" in reply.lower()
        assert "SHOULD_NOT_RUN" not in reply           # never executed

    def test_edit_executes_replacement_code(self):
        from fast_dash.adapters.langstage import make_resume_input
        def dashboard(a: int = 1) -> str:
            return str(a)
        app = FastDash(callback_fn=dashboard,
                       chat=_run_python_hitl_graph("print('ORIGINAL')"))
        self._pause(app)
        pending = app._session("s1").pending
        # An edit decision carries the replacement code (the UI would supply it).
        resume = make_resume_input(
            [{"type": "edit", "args": {"code": "print('EDITED')"}}])
        with mock.patch("flask_socketio.emit"):
            app._run_chat_turn(pending["query"], "s1", "sock", (), resume=resume,
                               resume_decision="edit", resume_blocks=pending["blocks"])
        reply = app.chat_history.get("s1")[-1]["content"]
        assert "EDITED" in reply and "ORIGINAL" not in reply


class TestRunPythonNamespaceLifecycle:
    """run_python exec state is freed when a session's history is cleared."""

    def test_clearing_history_frees_python_state(self):
        import fast_dash.agent_tools as AT
        from fast_dash.chat import ChatHistory
        AT._PY_NAMESPACES["sess-x"] = {"counter": 5}
        AT._LAST_RESULT["sess-x"] = "a-figure"
        hist = ChatHistory(size=5)
        hist.append_turn("sess-x", "hi", "there")
        hist.clear("sess-x")
        assert "sess-x" not in AT._PY_NAMESPACES     # namespace freed
        assert "sess-x" not in AT._LAST_RESULT       # stashed result freed

    def test_clear_python_state_is_safe_for_unknown_thread(self):
        import fast_dash.agent_tools as AT
        AT.clear_python_state("no-such-thread")      # must not raise


class TestUpdateLiveTrimsAllDriveVerbs:
    """update_live trims every drive verb (set_input/run_app/set_output/set_layout)."""

    def test_all_drive_verbs_dropped_with_warning(self):
        def dashboard(x: int = 1) -> str:
            return str(x)
        with pytest.warns(UserWarning, match="read-only"):
            app = FastDash(callback_fn=dashboard,
                           chat=lambda query, ctx: (yield "hi"),
                           update_live=True)
        # None of the four drive verbs survive; read_app remains.
        for verb in ("set_input", "run_app", "set_output", "set_layout"):
            assert verb not in app.chat_tools_config
        assert "read_app" in app.chat_tools_config
        assert app._sidecar_can_drive is False

    @requires_auto_agent
    def test_toolkit_does_not_advertise_trimmed_verbs(self):
        # The point of trimming the allowlist (not only refusing at dispatch):
        # agent_toolkit must not advertise the app-driving verbs on update_live.
        # (run_python survives -- executing code doesn't double-run the callback.)
        import fast_dash.agent_tools as AT
        def dashboard(x: int = 1) -> str:
            return str(x)
        with pytest.warns(UserWarning):
            app = FastDash(callback_fn=dashboard,
                           chat=lambda query, ctx: (yield "hi"),
                           update_live=True)
        names = {t.name for t in AT.agent_toolkit(app)}
        assert names.isdisjoint(
            {"set_input", "run_app", "set_output", "set_layout"})
        assert "read_app" in names


@requires_auto_agent
class TestReadAppAgreesWithSlots:
    """The read_app tool's output slots agree with output_slot_letters (MCP)."""

    def test_read_app_slots_match_output_slot_letters(self):
        import fast_dash.agent_tools as AT
        from fast_dash import Text
        def dashboard(a: int = 1, b: int = 2):
            return f"x{a}", f"y{b}"
        app = FastDash(callback_fn=dashboard,
                       chat=lambda query, ctx: (yield "hi"), outputs=[Text, Text])
        read = next(t for t in AT.agent_toolkit(app) if t.name == "read_app")
        contract = read.invoke({})
        slots = [s["slot"] for s in contract["outputs"]]
        assert slots == app.layout_object.output_slot_letters == ["A", "B"]

    def test_sidecar_mcp_describe_has_no_removed_concepts(self):
        # A 0.6.0 sidecar app's MCP describe reports title/doc/inputs only -- no
        # canvas / drawer / chat_agent leftovers from the removed 0.5.x surface.
        from fast_dash import Text
        def dashboard(a: int = 1) -> str:
            return str(a)
        app = FastDash(callback_fn=dashboard,
                       chat=lambda query, ctx: (yield "hi"), outputs=[Text],
                       mcp_server=True)
        # The describe machinery the agent reads (read_app) is the same source
        # of truth as MCP; assert it carries none of the removed vocabulary.
        import fast_dash.agent_tools as AT
        contract = AT._read_app_contract(app)
        blob = json.dumps(contract).lower()
        for removed in ("canvas", "drawer", "chat_agent"):
            assert removed not in blob
