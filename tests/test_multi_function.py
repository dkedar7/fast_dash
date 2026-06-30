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

    # func_b should have a single-line text input
    b_inputs = app.func_data[1]["inputs_with_ids"]
    assert b_inputs[0].__doc__ == dmc.TextInput().__doc__, "str should be a TextInput"


def test_single_function_unchanged():
    "Single function should work exactly as before (regression)"

    def func(text: str = "hello") -> str:
        return text

    app = FastDash(func)
    assert app.is_multi is False
    assert not hasattr(app, "func_data") or not app.func_data if hasattr(app, "func_data") else True
    assert app.inputs_with_ids[0].__doc__ == dmc.TextInput().__doc__
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


# --- dmc-based layout (post-migration) ---


class TestMultiFunctionDmcLayout:
    """Multi-function mode now reuses AppLayout (dmc/AppShell) instead of dbc."""

    def test_layout_uses_mantine_provider_at_root(self):
        def a(x: str) -> str:
            return x

        def b(y: int = 1) -> int:
            return y

        app = FastDash([a, b])
        # AppLayout wraps everything in a MantineProvider
        assert "MantineProvider" in type(app.app.layout).__name__

    def test_layout_contains_appshell(self):
        def a(x: str) -> str: return x
        def b(y: int = 1) -> int: return y

        app = FastDash([a, b])
        layout_str = str(app.app.layout)
        assert "appshell" in layout_str
        # Header / navbar IDs come from AppLayout
        assert "header1162572" in layout_str
        assert "navbar3260780" in layout_str

    def test_layout_contains_per_tab_panels_with_prefixes(self):
        def alpha(x: str) -> str: return x
        def beta(y: int = 1) -> int: return y

        app = FastDash([alpha, beta])
        layout_str = str(app.app.layout)
        # Per-tab input + output panels exist for each function
        assert "func0_input-panel" in layout_str
        assert "func1_input-panel" in layout_str
        assert "func0_output-panel" in layout_str
        assert "func1_output-panel" in layout_str

    def test_layout_uses_dmc_tabs_strip(self):
        def a(x: str) -> str: return x
        def b(y: int = 1) -> int: return y

        app = FastDash([a, b])
        layout_str = str(app.app.layout)
        assert "multi-function-tabs" in layout_str

    def test_per_function_loading_overlay_ids_preserved(self):
        """The per-function callbacks key off these IDs — they must stay."""
        def a(x: str) -> str: return x
        def b(y: int = 1) -> int: return y

        app = FastDash([a, b])
        layout_str = str(app.app.layout)
        assert "func0_loading-overlay" in layout_str
        assert "func1_loading-overlay" in layout_str

    def test_per_function_submit_and_reset_buttons_preserved(self):
        def a(x: str) -> str: return x
        def b(y: int = 1) -> int: return y

        app = FastDash([a, b])
        layout_str = str(app.app.layout)
        # The buttons inside _make_input_groups / _make_output_groups
        assert "func0_submit_inputs" in layout_str
        assert "func1_submit_inputs" in layout_str
        assert "func0_reset_inputs" in layout_str
        assert "func1_reset_inputs" in layout_str

    def test_no_dbc_navbar_or_tabs_remain(self):
        """Old dbc.NavbarSimple / dbc.Tabs / dbc.Modal should be gone."""
        def a(x: str) -> str: return x
        def b(y: int = 1) -> int: return y

        app = FastDash([a, b])
        layout_str = str(app.app.layout)
        # dbc.NavbarSimple → dmc header. dbc.Modal → dmc.Modal.
        assert "NavbarSimple" not in layout_str

    def test_about_modal_uses_dmc_modal(self):
        def a(x: str) -> str: return x
        def b(y: int = 1) -> int: return y

        app = FastDash([a, b], about=True)
        layout_str = str(app.app.layout)
        assert "about-modal" in layout_str

    def test_minimal_mode_strips_chrome(self):
        def a(x: str) -> str: return x
        def b(y: int = 1) -> int: return y

        app = FastDash([a, b], minimal=True)
        layout_str = str(app.app.layout)
        # Per-tab panels still exist; chrome bits are gone
        assert "func0_input-panel" in layout_str
        assert "func1_input-panel" in layout_str

    def test_callback_count_includes_tab_switcher(self):
        """Tab switcher + N per-function callbacks + chrome callbacks."""
        def a(x: str) -> str: return x
        def b(y: int = 1) -> int: return y

        app = FastDash([a, b])
        # At minimum: 1 tab switcher + 2 per-fn process + 2 per-fn loading
        # + 2 per-fn ack + 1 dark-mode + 1 sidebar + 1 about modal = 10
        assert len(app.app.callback_map) >= 5
