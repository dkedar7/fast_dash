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

from unittest import mock  # noqa: E402

from fast_dash import FastDash  # noqa: E402


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
