#!/usr/bin/env python
"""Test that the primary submit button is labeled "Run", not "Submit"."""
import re

from fast_dash import FastDash, Text
from fast_dash.utils import _make_input_groups, _assign_ids_to_inputs


def test_run_label_in_input_groups():
    """_make_input_groups should emit a button labeled 'Run' at the end."""
    def f(x: str) -> str:
        return x

    inputs_with_ids = _assign_ids_to_inputs([Text], f)
    groups = _make_input_groups(inputs_with_ids, update_live=False)
    rendered = str(groups)
    assert "'Run'" in rendered or '"Run"' in rendered
    # And the old label is gone
    assert "'Submit'" not in rendered and '"Submit"' not in rendered


def test_show_submit_false_omits_button():
    """With show_submit=False (used by steps mode), no submit button should render."""
    def f(x: str) -> str:
        return x

    inputs_with_ids = _assign_ids_to_inputs([Text], f)
    groups = _make_input_groups(inputs_with_ids, update_live=False, show_submit=False)
    rendered = str(groups)
    # No "Run" button, no submit_inputs id
    assert "submit_inputs" not in rendered
    assert "'Run'" not in rendered and '"Run"' not in rendered


def test_show_submit_default_is_true():
    """The default must render the Run button (preserves existing single-function behavior)."""
    def f(x: str) -> str:
        return x

    inputs_with_ids = _assign_ids_to_inputs([Text], f)
    groups = _make_input_groups(inputs_with_ids, update_live=False)  # no show_submit kwarg
    rendered = str(groups)
    assert "submit_inputs" in rendered


def test_app_layout_contains_run_button():
    """End-to-end: a FastDash app's layout should contain the 'Run' button."""
    def f(x: str) -> str:
        return x

    app = FastDash(callback_fn=f, inputs=Text, outputs=Text)
    layout_str = str(app.app.layout)
    assert "'Run'" in layout_str or '"Run"' in layout_str
    assert '"Submit"' not in layout_str and "'Submit'" not in layout_str


def _classname_gate_js(app):
    """The clientside JS registered for #output-group-col.className."""
    hit = next(
        cb for cb in app.app._callback_list
        if "output-group-col.className" in str(cb.get("output", ""))
    )
    fn_hash = hit["clientside_function"]["function_name"]
    return next(s for s in app.app._inline_scripts if fn_hash in s)


def test_no_input_app_does_not_gate_output_behind_placeholder():
    """A 0-input callback auto-enables update_live and must render on load.

    Regression: the pre-run `.fd-not-run` placeholder gate (keyed only on the
    Run button's click count) hid the output the initial auto-run had already
    computed, so the app rendered blank. update_live apps have no Run step, so
    the gate must never engage for them.
    """
    import plotly.graph_objects as go

    def dashboard() -> go.Figure:
        return go.Figure(go.Bar(x=["a", "b"], y=[3, 1]))

    app = FastDash(callback_fn=dashboard)
    assert app.update_live is True           # auto-enabled for 0 inputs
    js = _classname_gate_js(app)
    assert "fd-not-run" not in js            # never gates -> output is shown


def test_run_mode_app_still_gates_until_first_run():
    """A normal Run-mode app keeps the pre-run placeholder until the first Run."""
    def f(x: str = "hi") -> str:
        return x

    app = FastDash(callback_fn=f)             # 1 input, update_live stays False
    assert app.update_live is False
    js = _classname_gate_js(app)
    assert "fd-not-run" in js                 # gate preserved
