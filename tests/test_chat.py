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
