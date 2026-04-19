#!/usr/bin/env python
"""Tests for multi-function tabbed app support in fast_dash."""

from typing import Literal, Annotated
from fast_dash import FastDash, dbc, dmc, html
from fast_dash.Components import Text


def test_multi_function_creates_tabs():
    "Multi-function app should have tabs in layout"

    def func_a(text: str = "hello") -> str:
        return text.upper()

    def func_b(num: int = 5) -> int:
        return num * 2

    app = FastDash([func_a, func_b])
    assert app.is_multi is True
    assert len(app.func_data) == 2


def test_multi_function_func_data_populated():
    "Each function should have its own data dict"

    def func_a(text: str) -> str:
        return text

    def func_b(value: int = 10) -> int:
        return value

    app = FastDash([func_a, func_b])

    # Check func_data structure
    for idx, fd in enumerate(app.func_data):
        assert fd["prefix"] == f"func{idx}_"
        assert fd["fn"] is not None
        assert len(fd["inputs_with_ids"]) > 0
        assert len(fd["outputs_with_ids"]) > 0


def test_multi_function_namespaced_ids():
    "Component IDs should be namespaced with func{idx}_ prefix"

    def func_a(text: str) -> str:
        return text

    def func_b(text: str) -> str:
        return text

    app = FastDash([func_a, func_b])

    # Same parameter name "text" should get different IDs
    a_input_ids = [i.id for i in app.func_data[0]["inputs_with_ids"]]
    b_input_ids = [i.id for i in app.func_data[1]["inputs_with_ids"]]

    assert a_input_ids[0] == "func0_text"
    assert b_input_ids[0] == "func1_text"

    # Output IDs should also be namespaced
    a_output_ids = [o.id for o in app.func_data[0]["outputs_with_ids"]]
    b_output_ids = [o.id for o in app.func_data[1]["outputs_with_ids"]]

    assert a_output_ids[0].startswith("func0_output_")
    assert b_output_ids[0].startswith("func1_output_")


def test_multi_function_with_custom_titles():
    "Custom tab titles should be stored"

    def func_a(x: str) -> str:
        return x

    def func_b(y: str) -> str:
        return y

    app = FastDash([func_a, func_b], tab_titles=["Alpha", "Beta"])
    assert app.tab_titles == ["Alpha", "Beta"]


def test_multi_function_with_modern_hints():
    "Multi-function should work with modern type hints"

    def func_a(
        model: Literal["gpt-4", "claude"],
        temp: Annotated[int, range(0, 100)],
    ) -> str:
        result = f"{model}:{temp}"
        return result

    def func_b(text: str = "hello") -> str:
        return text.upper()

    app = FastDash([func_a, func_b])

    # func_a should have Select and Slider inputs
    a_inputs = app.func_data[0]["inputs_with_ids"]
    assert a_inputs[0].__doc__ == dmc.Select().__doc__, "Literal should be Select"
    assert a_inputs[1].__doc__ == dmc.Slider().__doc__, "Annotated range should be Slider"

    # func_b should have Text input
    b_inputs = app.func_data[1]["inputs_with_ids"]
    assert b_inputs[0].__doc__ == Text.__doc__, "str should be Text"


def test_single_function_unchanged():
    "Single function should work exactly as before (regression)"

    def func(text: str = "hello") -> str:
        return text

    app = FastDash(func)
    assert app.is_multi is False
    assert not hasattr(app, "func_data") or not app.func_data if hasattr(app, "func_data") else True
    assert app.inputs_with_ids[0].__doc__ == Text.__doc__
    assert app.inputs_with_ids[0].id == "text"


def test_single_function_no_tabs():
    "Single function should not have is_multi set"

    def func(x: str) -> str:
        return x

    app = FastDash(func)
    assert app.is_multi is False


def test_multi_function_three_functions():
    "Three functions should create three entries in func_data"

    def f1(a: str) -> str:
        return a

    def f2(b: int = 5) -> int:
        return b

    def f3(c: bool = True) -> str:
        return str(c)

    app = FastDash([f1, f2, f3])
    assert len(app.func_data) == 3
    assert app.func_data[0]["prefix"] == "func0_"
    assert app.func_data[1]["prefix"] == "func1_"
    assert app.func_data[2]["prefix"] == "func2_"
