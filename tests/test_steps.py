#!/usr/bin/env python
"""Tests for the multi-step pipeline feature.

Pipelines are declared via ``FastDash(steps=[fn_a, fn_b, ...])``. Each step
function gets its own panel in a stepper UI; downstream steps can pull
upstream outputs via ``from_step`` defaults. These tests exercise the
construction-time behavior (signature splitting, layout assembly) and the
runtime helpers without needing a browser.
"""
import inspect

from fast_dash import FastDash, from_step
import pandas as pd


# --- helper: build a small linear pipeline ---


def _load_data(rows: int = 10) -> pd.DataFrame:
    """Generate sample rows."""
    return pd.DataFrame({"x": list(range(rows)), "y": [i * 2 for i in range(rows)]})


def _double(data=from_step(_load_data)) -> pd.DataFrame:
    """Double every value in the upstream DataFrame."""
    return data * 2


def _summarise(data=from_step(_double), prefix: str = "Result:") -> str:
    """Return a one-line summary string."""
    return f"{prefix} {len(data)} rows, sum={data.values.sum()}"


# --- _make_user_params_fn ---


class TestMakeUserParamsFn:
    def test_signature_only_includes_listed_params(self):
        def fn(a: int = 1, b: str = "x", c: float = 0.5): pass
        params = list(inspect.signature(fn).parameters.items())
        # Pretend `b` is wired via from_step and shouldn't reach the UI
        user_params = [p for p in params if p[0] != "b"]
        synth = FastDash._make_user_params_fn(user_params)
        assert list(inspect.signature(synth).parameters) == ["a", "c"]

    def test_annotations_are_preserved(self):
        def fn(a: int, b: str = "x"): pass
        params = list(inspect.signature(fn).parameters.items())
        synth = FastDash._make_user_params_fn(params)
        assert synth.__annotations__ == {"a": int, "b": str}

    def test_defaults_are_preserved(self):
        def fn(a: int = 42, b: str = "hi"): pass
        params = list(inspect.signature(fn).parameters.items())
        synth = FastDash._make_user_params_fn(params)
        sig = inspect.signature(synth)
        assert sig.parameters["a"].default == 42
        assert sig.parameters["b"].default == "hi"

    def test_empty_user_params_produces_empty_signature(self):
        synth = FastDash._make_user_params_fn([])
        assert list(inspect.signature(synth).parameters) == []


# --- _init_steps: construction & metadata ---


class TestInitSteps:
    def test_step_count_matches_input(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double])
        assert len(app.step_data) == 2

    def test_step_prefixes_are_unique(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double, _summarise])
        prefixes = [sd["prefix"] for sd in app.step_data]
        assert prefixes == ["step0_", "step1_", "step2_"]
        assert len(set(prefixes)) == len(prefixes)

    def test_fn_to_idx_mapping(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double, _summarise])
        assert app.fn_to_idx == {_load_data: 0, _double: 1, _summarise: 2}

    def test_from_step_params_separated_from_user_params(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double, _summarise])
        # Step 0: only user params, no from_step
        assert app.step_data[0]["from_step_params"] == {}
        assert [p[0] for p in app.step_data[0]["user_params"]] == ["rows"]

        # Step 1: only from_step, no user params
        assert "data" in app.step_data[1]["from_step_params"]
        assert app.step_data[1]["user_params"] == []

        # Step 2: mix
        assert "data" in app.step_data[2]["from_step_params"]
        assert [p[0] for p in app.step_data[2]["user_params"]] == ["prefix"]

    def test_steps_with_no_user_inputs_have_empty_input_groups(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double])
        # _double has no user params (only from_step)
        assert app.step_data[1]["inputs_with_ids"] == []

    def test_input_ids_are_prefixed_per_step(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _summarise])
        # Step 2 (_summarise) has user param `prefix`
        prefix_ids = [c.id for c in app.step_data[1]["inputs_with_ids"]]
        assert any("step1_" in i for i in prefix_ids)

    def test_step_titles_derived_from_function_names(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double, _summarise])
        titles = [sd["title"].strip() for sd in app.step_data]
        # Leading underscores in the helper names produce a leading space; strip it.
        assert titles == ["Load Data", "Double", "Summarise"]

    def test_descriptions_pulled_from_docstring(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double])
        # _load_data's docstring is "Generate sample rows."
        assert "Generate sample rows" in app.step_data[0]["description"]


# --- App-level integration ---


class TestStepsAppBuild:
    def test_app_builds_with_two_step_pipeline(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double])
        assert app.app.layout is not None

    def test_app_builds_with_three_step_pipeline(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double, _summarise])
        assert app.app.layout is not None

    def test_app_builds_with_single_step(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data])
        assert app.app.layout is not None
        assert len(app.step_data) == 1

    def test_steps_mode_overrides_multi_function_mode(self):
        """If both `steps=` and a list `callback_fn=` are provided, steps wins."""
        app = FastDash(
            callback_fn=[_load_data, _double],   # would normally be multi-function
            steps=[_load_data, _double],
        )
        assert app.is_steps is True
        assert app.is_multi is False

    def test_callback_fn_optional_when_steps_provided(self):
        """Users should be able to write FastDash(steps=[...]) without callback_fn."""
        app = FastDash(steps=[_load_data, _double])
        assert app.is_steps is True
        assert app.app.layout is not None

    def test_no_callback_fn_and_no_steps_raises(self):
        """Construction with neither callback_fn nor steps must fail loudly."""
        import pytest
        with pytest.raises(TypeError, match="callback_fn|steps"):
            FastDash()

    def test_layout_contains_step_containers_and_buttons(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double])
        layout_str = str(app.app.layout)
        assert "step-inputs-0" in layout_str
        assert "step-inputs-1" in layout_str
        assert "step-outputs-0" in layout_str
        assert "step-outputs-1" in layout_str
        assert "step-run-btn" in layout_str
        assert "step-back-btn" in layout_str
        assert "step-next-btn" in layout_str
        assert "pipeline-stepper" in layout_str

    def test_layout_contains_session_stores(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double])
        layout_str = str(app.app.layout)
        assert "step-session-id" in layout_str
        assert "step-current-idx" in layout_str
        assert "step-completed-set" in layout_str

    def test_steps_app_registers_callbacks(self):
        """run, next, back, visibility, session-init = at least 5 callbacks."""
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double])
        assert len(app.app.callback_map) >= 5


# --- Backward compatibility ---


class TestStepsDoesNotBreakOtherModes:
    def test_single_function_app_still_works_when_steps_kwarg_omitted(self):
        def fn(x: str) -> str:
            return x.upper()
        app = FastDash(callback_fn=fn)
        assert app.is_steps is False
        assert app.app.layout is not None

    def test_multi_function_app_still_works_when_steps_kwarg_omitted(self):
        def a(x: str) -> str: return x
        def b(x: int) -> int: return x
        app = FastDash(callback_fn=[a, b])
        assert app.is_steps is False
        assert app.is_multi is True
        assert app.app.layout is not None


# --- from_step behavior ---


class TestFromStep:
    def test_from_step_records_source_function(self):
        fs = from_step(_load_data)
        assert fs.source_fn is _load_data
        assert fs.transform is None

    def test_from_step_with_transform(self):
        fs = from_step(_load_data, transform=lambda df: list(df.columns))
        assert fs.source_fn is _load_data
        assert callable(fs.transform)

    def test_from_step_consumed_by_init_steps(self):
        """A from_step in a step's signature should be picked up as a from_step_param,
        not as a user-facing input."""
        def consumer(data=from_step(_load_data)) -> str:
            return f"got {len(data)} rows"

        app = FastDash(callback_fn=_load_data, steps=[_load_data, consumer])
        assert "data" in app.step_data[1]["from_step_params"]
        # No UI input was created for `data`
        assert all(
            "data" not in c.id
            for c in app.step_data[1]["inputs_with_ids"]
        )


# --- _step_cache lifecycle (a process-level dict) ---


class TestStepCache:
    def setup_method(self, method):
        # Don't pollute across tests
        FastDash._step_cache.clear()

    def teardown_method(self, method):
        FastDash._step_cache.clear()

    def test_cache_is_class_level_dict(self):
        assert isinstance(FastDash._step_cache, dict)

    def test_cache_can_store_and_retrieve_values(self):
        FastDash._step_cache["session-A"] = {0: "step-0-result"}
        assert FastDash._step_cache["session-A"][0] == "step-0-result"

    def test_independent_sessions_dont_collide(self):
        FastDash._step_cache["session-A"] = {0: "A-result"}
        FastDash._step_cache["session-B"] = {0: "B-result"}
        assert FastDash._step_cache["session-A"][0] == "A-result"
        assert FastDash._step_cache["session-B"][0] == "B-result"


# --- Output labels for steps ---


class TestStepOutputLabels:
    def test_each_step_gets_one_output_with_a_label(self):
        app = FastDash(callback_fn=_load_data, steps=[_load_data, _double])
        for sd in app.step_data:
            assert len(sd["outputs_with_ids"]) == 1
            # Label should be derived from function name
            assert sd["outputs_with_ids"][0].label_ is not None
