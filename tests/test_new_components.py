#!/usr/bin/env python
"""Tests for new Fast Dash components exported in v0.2.16."""
import pytest

from fast_dash import (
    FastDash,
    MultiSelect,
    DateRange,
    Switch,
    PasswordInput,
    Markdown,
)


# --- existence & shape ---


def test_multiselect_shape():
    assert MultiSelect.component_property == "value"
    assert MultiSelect.tag == "Text"
    assert MultiSelect.component.__class__.__name__ == "MultiSelect"


def test_daterange_shape():
    assert DateRange.component_property == "value"
    assert DateRange.tag == "Text"
    assert DateRange.component.__class__.__name__ == "DatePickerInput"


def test_switch_shape():
    # Switch binds to `checked` not `value`, because dmc.Switch exposes checked
    assert Switch.component_property == "checked"
    assert Switch.tag == "Bool"
    assert Switch.component.__class__.__name__ == "Switch"


def test_passwordinput_shape():
    assert PasswordInput.component_property == "value"
    assert PasswordInput.tag == "Text"
    assert PasswordInput.component.__class__.__name__ == "PasswordInput"


def test_markdown_shape():
    # Markdown outputs html children, not a form `value`
    assert Markdown.component_property == "children"
    assert Markdown.tag == "Text"
    assert Markdown.component.__class__.__name__ == "Markdown"


# --- integration: building a FastDash app that uses each ---


def _build(inputs, outputs):
    def fn(x):
        return x
    return FastDash(callback_fn=fn, inputs=inputs, outputs=outputs)


def test_multiselect_as_input_builds_app():
    app = _build(MultiSelect, Markdown)
    assert app.app.layout is not None


def test_daterange_as_input_builds_app():
    app = _build(DateRange, Markdown)
    assert app.app.layout is not None


def test_switch_as_input_builds_app():
    app = _build(Switch, Markdown)
    assert app.app.layout is not None


def test_passwordinput_as_input_builds_app():
    app = _build(PasswordInput, Markdown)
    assert app.app.layout is not None


def test_markdown_as_output_builds_app():
    app = _build(PasswordInput, Markdown)
    # Component exists on output side
    out_comp = app.outputs_with_ids[0]
    assert out_comp.component.__class__.__name__ == "Markdown"
