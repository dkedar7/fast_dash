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
