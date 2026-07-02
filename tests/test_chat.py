"""Unit tests for the transport-independent chat core (fast_dash/chat.py, RFC #133)."""

import asyncio  # noqa: F401  (async generator tests use it implicitly)
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

    def test_mcp_skipped_with_warning(self):
        def bot(query):
            yield "hi"
        with pytest.warns(UserWarning, match="not yet supported in chat mode"):
            app = FastDash(callback_fn=bot, chat=True, mcp_server=True)
        assert app.mcp_server_enabled is False


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
