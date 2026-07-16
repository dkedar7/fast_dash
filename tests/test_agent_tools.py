"""Unit tests for the chat-agent toolkit (fast_dash/agent_tools.py, 0.6.0).

Split into buffer tests (no optional deps) and toolkit/agent tests (guarded on
the [agent] extra: langchain + langgraph). The HITL interrupt path is unit-
tested by patching ``langgraph.types.interrupt`` to capture its payload and
drive a decision back -- the deep end-to-end pause/resume belongs to Round 3.
"""

import importlib.util

import pytest

import fast_dash.agent_tools as AT
from fast_dash import FastDash
from fast_dash.agent_tools_config import RunPython

_HAS_AGENT = (
    importlib.util.find_spec("langchain") is not None
    and importlib.util.find_spec("langgraph") is not None
)
requires_agent = pytest.mark.skipif(
    not _HAS_AGENT, reason="agent extra (langchain + langgraph) not installed"
)


# --------------------------------------------------------------------------- #
# Frame buffer (no optional deps)
# --------------------------------------------------------------------------- #

class TestFrameBuffer:
    def test_drain_empty_off_turn_never_raises(self):
        # No active turn buffer: drain returns [] and emit is a silent no-op.
        assert AT.drain_frames() == []
        AT.emit_frame({"type": "run_app"})            # dropped, no error
        assert AT.drain_frames() == []

    def test_emit_then_drain_within_turn(self):
        with AT.turn_buffer():
            AT.emit_frame({"type": "run_app"})
            AT.emit_frame({"type": "set_input", "name": "a", "value": 1})
            drained = AT.drain_frames()
        assert drained == [
            {"type": "run_app"},
            {"type": "set_input", "name": "a", "value": 1},
        ]

    def test_drain_clears_buffer(self):
        with AT.turn_buffer():
            AT.emit_frame({"type": "run_app"})
            assert AT.drain_frames()                    # first drain returns it
            assert AT.drain_frames() == []              # cleared

    def test_turn_buffers_isolate(self):
        with AT.turn_buffer():
            AT.emit_frame({"type": "run_app"})
        # Exiting the context clears the buffer; a new turn starts fresh.
        with AT.turn_buffer():
            assert AT.drain_frames() == []
            AT.emit_frame({"type": "set_layout", "mosaic": "A"})
            assert AT.drain_frames() == [{"type": "set_layout", "mosaic": "A"}]

    def test_clear_python_state_frees_namespace_and_result(self):
        # The run_python exec state (per-thread namespace + stashed result) is
        # freed on demand; unknown thread ids are a safe no-op. Needs no extra.
        AT._PY_NAMESPACES["t-clear"] = {"x": 1}
        AT._LAST_RESULT["t-clear"] = "obj"
        AT.clear_python_state("t-clear")
        assert "t-clear" not in AT._PY_NAMESPACES
        assert "t-clear" not in AT._LAST_RESULT
        AT.clear_python_state("never-seen")             # no raise

    def test_no_heavy_imports_at_module_top(self):
        # Importing agent_tools must not drag in langchain/langgraph (the buffer
        # side runs in every chat session; the extra is lazy). agent_tools is
        # already imported by this test module, so assert the invariant holds.
        import sys
        assert "fast_dash.agent_tools" in sys.modules
        # The module's own globals must not bind the heavy names at import time.
        assert not hasattr(AT, "create_react_agent")
        assert not hasattr(AT, "init_chat_model")

    def test_top_level_lazy_exports_resolve(self):
        # The public toolkit entry points are exported from fast_dash (lazily via
        # PEP 562), alongside RunPython. Resolving them must not raise even when
        # only the buffer side of agent_tools has been touched.
        import fast_dash
        from fast_dash import (  # noqa: F401
            FastDashMiddleware,
            RunPython,
            agent_toolkit,
            app_prompt,
        )
        for name in ("agent_toolkit", "FastDashMiddleware", "app_prompt"):
            assert name in fast_dash.__all__
            assert callable(getattr(fast_dash, name))
        # An unknown attribute still raises a normal AttributeError (PEP 562).
        with pytest.raises(AttributeError):
            fast_dash.definitely_not_an_export


# --------------------------------------------------------------------------- #
# Helpers to build a sidecar app without needing a real model
# --------------------------------------------------------------------------- #

def _stub_agent(query, ctx):
    """A minimal (query, ctx) chat callable -> makes the app an agent sidecar."""
    yield "ok"


def _add(a: int, b: int = 2) -> int:
    """Add two numbers."""
    return a + b


def _sidecar_app(chat_tools):
    return FastDash(callback_fn=_add, chat=_stub_agent, chat_tools=chat_tools,
                    title="Add")


def _tool(toolkit, name):
    return next(t for t in toolkit if t.name == name)


# --------------------------------------------------------------------------- #
# agent_toolkit: allowlist trimming + tool behavior
# --------------------------------------------------------------------------- #

@requires_agent
class TestAgentToolkitAllowlist:
    def test_trims_to_allowlist(self):
        app = _sidecar_app(("read_app", "set_input"))
        names = {t.name for t in AT.agent_toolkit(app)}
        assert names == {"read_app", "set_input"}

    def test_empty_allowlist_is_empty_toolkit(self):
        app = _sidecar_app(())
        assert AT.agent_toolkit(app) == []

    def test_run_python_adds_push_result(self):
        app = _sidecar_app(("read_app", RunPython(approval=False)))
        names = {t.name for t in AT.agent_toolkit(app)}
        assert names == {"read_app", "run_python", "push_result"}

    def test_default_full_toolkit(self):
        app = _sidecar_app(None)                        # None -> default toolkit
        names = {t.name for t in AT.agent_toolkit(app)}
        # Default carries run_python (approval=True) -> push_result too.
        assert {"read_app", "set_input", "run_app", "set_output",
                "set_layout", "run_python", "push_result"} <= names


@requires_agent
class TestReadApp:
    def test_read_app_reports_inputs_and_slots(self):
        app = _sidecar_app(("read_app",))
        read = _tool(AT.agent_toolkit(app), "read_app")
        contract = read.invoke({})
        assert contract["title"] == "Add"
        assert contract["doc"] == "Add two numbers."
        ids = {e["id"] for e in contract["inputs"]}
        assert {"a", "b"} <= ids
        # One output slot, addressed by letter "A", with a clean string type.
        slots = contract["outputs"]
        assert slots and slots[0]["slot"] == "A"
        assert isinstance(slots[0]["type"], str)


@requires_agent
class TestSetInput:
    def test_invalid_value_returns_error_without_emitting(self):
        app = _sidecar_app(("set_input",))
        set_input = _tool(AT.agent_toolkit(app), "set_input")
        with AT.turn_buffer():
            msg = set_input.invoke({"name": "a", "value": "not-an-int"})
            frames = AT.drain_frames()
        assert "isn't a valid" in msg                   # error text for the model
        assert frames == []                             # no frame on validation fail

    def test_valid_value_emits_frame(self):
        app = _sidecar_app(("set_input",))
        set_input = _tool(AT.agent_toolkit(app), "set_input")
        with AT.turn_buffer():
            msg = set_input.invoke({"name": "a", "value": 5})
            frames = AT.drain_frames()
        assert "Set input" in msg
        assert frames == [{"type": "set_input", "name": "a", "value": 5}]

    def test_unknown_input_returns_error(self):
        app = _sidecar_app(("set_input",))
        set_input = _tool(AT.agent_toolkit(app), "set_input")
        with AT.turn_buffer():
            msg = set_input.invoke({"name": "zzz", "value": 1})
            assert AT.drain_frames() == []
        assert "No input named" in msg


@requires_agent
class TestRunAppAndLayout:
    def test_run_app_emits_frame(self):
        # Off-turn (bare turn_buffer, no drive inputs seeded): keep the old
        # fire-and-forget behavior -- a plain frame the drain will run.
        app = _sidecar_app(("run_app",))
        run_app = _tool(AT.agent_toolkit(app), "run_app")
        with AT.turn_buffer():
            run_app.invoke({})
            assert AT.drain_frames() == [{"type": "run_app"}]

    def test_set_layout_emits_mosaic(self):
        app = _sidecar_app(("set_layout",))
        set_layout = _tool(AT.agent_toolkit(app), "set_layout")
        with AT.turn_buffer():
            set_layout.invoke({"mosaic": "AB"})
            assert AT.drain_frames() == [{"type": "set_layout", "mosaic": "AB"}]

    def test_set_output_emits_value(self):
        app = _sidecar_app(("set_output",))
        set_output = _tool(AT.agent_toolkit(app), "set_output")
        with AT.turn_buffer():
            set_output.invoke({"slot": "A", "value": 42})
            assert AT.drain_frames() == [
                {"type": "set_output", "slot": "A", "value": 42}]


@requires_agent
class TestRunAppClosesTheLoop:
    """#135: run_app runs the callback and REPORTS the result to the model.

    Before this, run_app only queued a frame and returned "outputs are
    updating" -- the agent could trigger a run but was blind to what it
    produced. Now, inside a seeded drive turn, run_app runs the callback, returns
    a summary naming each output slot, and marks its frame so the frame drain
    renders the carried outputs instead of running the callback a second time.
    """

    def test_run_app_runs_and_reports_the_outputs(self):
        app = _sidecar_app(("set_input", "run_app"))     # _add(a, b) -> int
        tk = AT.agent_toolkit(app)
        run_app, set_input = _tool(tk, "run_app"), _tool(tk, "set_input")
        with AT.turn_buffer({"a": 1, "b": 2}):
            set_input.invoke({"name": "a", "value": 10})
            reply = run_app.invoke({})
        # The model is told what the run produced (10 + 2 == 12), not just that
        # outputs are "updating".
        assert "updating" not in reply
        assert "A:" in reply and "12" in reply

    def test_run_app_runs_on_the_value_set_this_turn(self):
        # set_input stages into the shared per-turn dict, so a following run_app
        # in the same turn runs on the value just set (not the turn-start value).
        app = _sidecar_app(("set_input", "run_app"))
        tk = AT.agent_toolkit(app)
        run_app, set_input = _tool(tk, "run_app"), _tool(tk, "set_input")
        with AT.turn_buffer({"a": 1, "b": 2}):
            set_input.invoke({"name": "a", "value": 100})
            set_input.invoke({"name": "b", "value": 5})
            reply = run_app.invoke({})
        assert "105" in reply

    def test_run_app_frame_carries_outputs_so_dispatch_does_not_rerun(self):
        # The single callback execution IS the run; the frame carries its outputs
        # so the drain renders them rather than running the callback again.
        calls = {"n": 0}

        def counting(x: int = 1) -> int:
            """count."""
            calls["n"] += 1
            return x * 10

        app = FastDash(callback_fn=counting, chat=_stub_agent,
                       chat_tools=("run_app",), title="Count")
        run_app = _tool(AT.agent_toolkit(app), "run_app")
        with AT.turn_buffer({"x": 4}):
            run_app.invoke({})
            frames = AT.drain_frames()

        assert calls["n"] == 1                            # ran exactly once
        run_frame = next(f for f in frames if f["type"] == "run_app")
        assert run_frame.get("ran") is True
        assert run_frame.get("outputs") == [40]           # rendered, not re-run

    def test_run_app_reports_a_callback_error_without_a_frame(self):
        def boom(x: int = 1) -> int:
            """boom."""
            raise ValueError("kaboom")

        app = FastDash(callback_fn=boom, chat=_stub_agent,
                       chat_tools=("run_app",), title="Boom")
        run_app = _tool(AT.agent_toolkit(app), "run_app")
        with AT.turn_buffer({"x": 1}):
            reply = run_app.invoke({})
            frames = AT.drain_frames()
        # The model is told it failed (so it can fix inputs), and no run_app
        # frame is emitted (nothing ran to render).
        assert "error" in reply.lower() and "kaboom" in reply
        assert not any(f["type"] == "run_app" for f in frames)

    def test_run_app_off_turn_keeps_fire_and_forget(self):
        # No seeded drive turn -> the fallback frame the drain will run.
        app = _sidecar_app(("run_app",))
        run_app = _tool(AT.agent_toolkit(app), "run_app")
        with AT.turn_buffer():                            # None, not a drive turn
            reply = run_app.invoke({})
            assert AT.drain_frames() == [{"type": "run_app"}]
        assert "updating" in reply

    def test_run_app_summary_withholds_output_derived_from_a_secret(self):
        # The sidecar guarantees a PasswordInput value never reaches the LLM, but
        # a callback may derive an output from it. run_app's summary must then
        # report shape/type only -- never the value -- so a decrypt/echo app
        # can't leak the secret back to the model through the run report.
        from fast_dash import PasswordInput

        def reveal(user: str = "kedar", password: PasswordInput = "hunter2") -> str:
            """Worst case: an output that echoes the secret."""
            return "%s:%s" % (user, password)

        app = FastDash(callback_fn=reveal, chat=_stub_agent,
                       chat_tools=("run_app",), title="Reveal")
        assert app._sidecar_secret_inputs == {"password"}
        run_app = _tool(AT.agent_toolkit(app), "run_app")
        with AT.turn_buffer({"user": "kedar", "password": "hunter2"}):
            reply = run_app.invoke({})
        assert "hunter2" not in reply                     # secret withheld
        assert "text (" in reply                          # shape reported instead

    def test_run_app_summary_keeps_full_value_without_secrets(self):
        # No secret inputs -> the model gets the real output value (the point of
        # the feature: read the result and react to it).
        def calc(n: int = 3) -> str:
            """calc."""
            return "answer is %d" % (n * 2)

        app = FastDash(callback_fn=calc, chat=_stub_agent,
                       chat_tools=("run_app",), title="Calc")
        assert app._sidecar_secret_inputs == set()
        run_app = _tool(AT.agent_toolkit(app), "run_app")
        with AT.turn_buffer({"n": 5}):
            reply = run_app.invoke({})
        assert "answer is 10" in reply


class TestBriefOutput:
    """The model-facing one-liner per output value (no agent extra needed)."""

    def test_figure_reports_traces_and_title(self):
        import plotly.graph_objects as go
        fig = go.Figure(go.Bar(x=[1], y=[1]), layout={"title": "Sales"})
        assert AT._brief_output(fig) == "a figure with 1 trace titled 'Sales'"

    def test_dataframe_reports_shape(self):
        import pandas as pd
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        assert AT._brief_output(df) == "a table (3 rows x 2 cols)"

    def test_short_scalar_and_string_pass_through(self):
        assert AT._brief_output(42) == "42"
        assert AT._brief_output("hi") == "'hi'"

    def test_bytes_output_is_prose_not_a_raw_dict(self):
        # The summarizer returns a {type: bytes, size, sha1} dict for bytes; the
        # brief must render prose, not dump the dict at the model.
        out = AT._brief_output(b"\x00\x01\x02\x03")
        assert out == "binary data (4 bytes)"
        assert "{" not in out

    def test_redact_reports_shape_without_values(self):
        import plotly.graph_objects as go
        assert AT._brief_output(42, redact=True) == "a number"
        assert AT._brief_output(True, redact=True) == "a boolean"
        assert AT._brief_output("s3cr3t-value", redact=True) == "text (12 chars)"
        # A figure's title could echo a secret -- dropped under redaction.
        fig = go.Figure(go.Bar(x=[1], y=[1]), layout={"title": "s3cr3t"})
        assert AT._brief_output(fig, redact=True) == "a figure with 1 trace"


# --------------------------------------------------------------------------- #
# run_python: direct-exec (approval=False)
# --------------------------------------------------------------------------- #

@requires_agent
class TestRunPythonDirect:
    def _cfg(self, thread_id):
        return {"configurable": {"thread_id": thread_id}}

    def test_stdout_and_last_expression(self):
        app = _sidecar_app((RunPython(approval=False),))
        rp = _tool(AT.agent_toolkit(app), "run_python")
        cfg = self._cfg("rp-basic")
        with AT.turn_buffer():
            out = rp.invoke({"code": "print('hey'); 6 * 7", "config": cfg}, config=cfg)
            assert AT.drain_frames() == []              # no artifact for a scalar
        assert "hey" in out and "42" in out

    def test_error_surfaces_to_model(self):
        app = _sidecar_app((RunPython(approval=False),))
        rp = _tool(AT.agent_toolkit(app), "run_python")
        cfg = self._cfg("rp-err")
        with AT.turn_buffer():
            out = rp.invoke({"code": "1/0", "config": cfg}, config=cfg)
        assert "Error" in out and "ZeroDivisionError" in out

    def test_figure_emits_artifact_and_push_result_works(self):
        app = _sidecar_app((RunPython(approval=False),))
        toolkit = AT.agent_toolkit(app)
        rp = _tool(toolkit, "run_python")
        push = _tool(toolkit, "push_result")
        cfg = self._cfg("rp-fig")
        code = "import plotly.graph_objects as go\nfig = go.Figure()\nfig"
        with AT.turn_buffer():
            out = rp.invoke({"code": code, "config": cfg}, config=cfg)
            frames = AT.drain_frames()
        assert "figure" in out.lower()
        # An artifact frame carries the live Figure inline.
        assert len(frames) == 1 and frames[0]["type"] == "artifact"
        import plotly.graph_objects as go
        assert isinstance(frames[0]["content"], go.Figure)
        # push_result emits a set_output frame carrying the stored Figure.
        with AT.turn_buffer():
            msg = push.invoke({"slot": "A", "config": cfg}, config=cfg)
            pframes = AT.drain_frames()
        assert "slot 'A'" in msg
        assert pframes and pframes[0]["type"] == "set_output"
        assert pframes[0]["slot"] == "A"
        assert isinstance(pframes[0]["value"], go.Figure)

    def test_push_result_without_stored_result(self):
        app = _sidecar_app((RunPython(approval=False),))
        push = _tool(AT.agent_toolkit(app), "push_result")
        cfg = self._cfg("rp-empty")
        with AT.turn_buffer():
            msg = push.invoke({"slot": "A", "config": cfg}, config=cfg)
            assert AT.drain_frames() == []
        assert "No stored result" in msg

    def test_namespace_persists_across_calls_same_thread(self):
        app = _sidecar_app((RunPython(approval=False),))
        rp = _tool(AT.agent_toolkit(app), "run_python")
        cfg = self._cfg("rp-persist")
        with AT.turn_buffer():
            rp.invoke({"code": "counter = 10", "config": cfg}, config=cfg)
        with AT.turn_buffer():
            out = rp.invoke({"code": "counter + 5", "config": cfg}, config=cfg)
        assert "15" in out


# --------------------------------------------------------------------------- #
# run_python: HITL interrupt (approval=True) -- payload shape + decisions
# --------------------------------------------------------------------------- #

@requires_agent
class TestRunPythonInterrupt:
    def _patch_interrupt(self, monkeypatch, decision):
        import langgraph.types as lt
        captured = {}

        def fake(payload):
            captured["payload"] = payload
            return decision

        monkeypatch.setattr(lt, "interrupt", fake)
        return captured

    def test_interrupt_payload_matches_frame_contract(self, monkeypatch):
        # The payload shape must be what the langstage bridge maps onto an
        # interrupt frame (action_requests / review_configs / allowed_decisions).
        captured = self._patch_interrupt(monkeypatch, {"decisions": [{"type": "approve"}]})
        app = _sidecar_app((RunPython(approval=True),))
        rp = _tool(AT.agent_toolkit(app), "run_python")
        cfg = {"configurable": {"thread_id": "hitl-approve"}}
        with AT.turn_buffer():
            out = rp.invoke({"code": "print('ran')", "config": cfg}, config=cfg)
        payload = captured["payload"]
        assert payload["action_requests"] == [
            {"action": "run_python", "args": {"code": "print('ran')"}}]
        assert payload["review_configs"] == []
        assert payload["allowed_decisions"] == ["approve", "edit", "reject"]
        assert "ran" in out                             # approved -> executed

    def test_reject_returns_denial_without_executing(self, monkeypatch):
        self._patch_interrupt(monkeypatch, {"decisions": [{"type": "reject"}]})
        app = _sidecar_app((RunPython(approval=True),))
        rp = _tool(AT.agent_toolkit(app), "run_python")
        cfg = {"configurable": {"thread_id": "hitl-reject"}}
        with AT.turn_buffer():
            out = rp.invoke({"code": "raise RuntimeError('should not run')",
                             "config": cfg}, config=cfg)
        assert out == "User denied execution."

    def test_edit_executes_replacement_code(self, monkeypatch):
        self._patch_interrupt(
            monkeypatch,
            {"decisions": [{"type": "edit", "args": {"code": "print('edited')"}}]},
        )
        app = _sidecar_app((RunPython(approval=True),))
        rp = _tool(AT.agent_toolkit(app), "run_python")
        cfg = {"configurable": {"thread_id": "hitl-edit"}}
        with AT.turn_buffer():
            out = rp.invoke({"code": "print('original')", "config": cfg}, config=cfg)
        assert "edited" in out and "original" not in out


# --------------------------------------------------------------------------- #
# app_prompt
# --------------------------------------------------------------------------- #

@requires_agent
class TestAppPrompt:
    def test_prompt_is_ascii_and_covers_contract(self):
        app = _sidecar_app(None)                        # default full toolkit
        prompt = AT.app_prompt(app)
        assert prompt.isascii()
        assert "Add" in prompt                          # title
        assert "Output slots" in prompt                 # slots section
        assert "A:" in prompt                           # slot letter listed
        assert "run_python" in prompt                   # tool listed
        assert "Run always wins" in prompt              # the rule

    def test_prompt_omits_disabled_tools(self):
        app = _sidecar_app(("read_app",))
        prompt = AT.app_prompt(app)
        assert "read_app" in prompt
        assert "run_python" not in prompt
        assert "set_layout" not in prompt


# --------------------------------------------------------------------------- #
# build_auto_agent + FastDashMiddleware
# --------------------------------------------------------------------------- #

def _fake_model(scripted):
    """A tool-binding fake chat model yielding scripted AIMessages."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class _ToolBindingFake(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self                                 # ignore tools for the test

    return _ToolBindingFake(messages=iter(scripted))


@requires_agent
class TestBuildAutoAgent:
    def test_model_instance_builds_compiled_graph(self):
        from langchain_core.messages import AIMessage
        app = _sidecar_app(("read_app", "run_app"))
        graph = AT.build_auto_agent(app, _fake_model([AIMessage(content="done")]))
        assert hasattr(graph, "invoke") and hasattr(graph, "astream")
        res = graph.invoke({"messages": [("user", "hi")]})
        assert res["messages"][-1].content == "done"

    def test_str_model_goes_through_init_chat_model(self):
        # A provider string reaches init_chat_model; without the provider package
        # it raises there (ImportError / ValueError) -- NOT our NameError. Proves
        # the resolution path runs rather than treating the str as a model.
        app = _sidecar_app(("read_app",))
        with pytest.raises(Exception) as ei:
            AT.build_auto_agent(app, "made-up-provider:model-x")
        assert not isinstance(ei.value, NameError)


@requires_agent
class TestFastDashMiddleware:
    def test_contributes_tools(self):
        app = _sidecar_app(("read_app", "run_app"))
        mw = AT.FastDashMiddleware(app)
        assert {t.name for t in mw.tools} == {"read_app", "run_app"}

    def test_create_agent_smoke_with_fake_model(self):
        from langchain.agents import create_agent
        from langchain_core.messages import AIMessage
        app = _sidecar_app(("read_app",))
        mw = AT.FastDashMiddleware(app)
        agent = create_agent(
            _fake_model([AIMessage(content="hello from agent")]),
            tools=[], middleware=[mw],
        )
        res = agent.invoke({"messages": [("user", "hi")]})
        assert res["messages"][-1].content == "hello from agent"
