#!/usr/bin/env python
"""Unit tests for the dynamic-UI surface (`fast_dash.dynamic`).

Form-driven path only. LLM/chat tests live on the
`feature/dynamic-ui-prototype` branch and are intentionally not ported
here — the agent is external in the MCP-based design.
"""

import json

import pytest

from fast_dash import (
    COMPONENT_REGISTRY,
    DynamicDash,
    Graph,
    Markdown,
    render_spec,
)
from fast_dash.dynamic import _spec_to_component


# --- COMPONENT_REGISTRY shape ------------------------------------------------


def test_registry_includes_expected_types():
    expected = {
        "Text", "TextArea", "NumberInput", "Slider", "Select", "MultiSelect",
        "Switch", "DateInput", "DateRange", "ColorInput", "PasswordInput",
        "Markdown", "Upload", "UploadImage",
    }
    assert expected <= set(COMPONENT_REGISTRY.keys())


# --- _spec_to_component ------------------------------------------------------


def test_spec_to_component_assigns_pattern_id_with_prop_axis():
    comp = _spec_to_component({"name": "rate", "type": "Slider"})
    assert comp.id == {"role": "dyn-input", "name": "rate", "prop": "value"}


def test_spec_to_component_switch_uses_checked_in_id():
    comp = _spec_to_component({"name": "advanced", "type": "Switch"})
    assert comp.id == {"role": "dyn-input", "name": "advanced", "prop": "checked"}


def test_spec_to_component_upload_uses_contents_in_id():
    comp = _spec_to_component({"name": "file", "type": "Upload"})
    assert comp.id == {"role": "dyn-input", "name": "file", "prop": "contents"}


def test_spec_to_component_applies_value():
    comp = _spec_to_component({"name": "temp", "type": "Slider", "value": 0.7})
    assert comp.value == 0.7


def test_spec_to_component_applies_props():
    comp = _spec_to_component(
        {"name": "rate", "type": "Slider", "props": {"min": 0, "max": 1, "step": 0.05}}
    )
    assert comp.min == 0
    assert comp.max == 1
    assert comp.step == 0.05


def test_spec_to_component_humanizes_label():
    comp = _spec_to_component({"name": "learning_rate", "type": "Slider"})
    assert comp.label_ == "Learning Rate"


def test_spec_to_component_uses_explicit_label():
    comp = _spec_to_component({"name": "x", "type": "Slider", "label": "Custom"})
    assert comp.label_ == "Custom"


def test_spec_to_component_rejects_missing_name():
    with pytest.raises(ValueError, match="missing required 'name'"):
        _spec_to_component({"type": "Slider"})


def test_spec_to_component_rejects_unknown_type():
    with pytest.raises(ValueError, match="Unknown component type"):
        _spec_to_component({"name": "x", "type": "NotAComponent"})


# --- render_spec -------------------------------------------------------------


def test_render_spec_default_container_id():
    out = render_spec([{"name": "x", "type": "Text"}])
    assert out.id == "dyn-form"


def test_render_spec_custom_container_id():
    out = render_spec([{"name": "x", "type": "Text"}], container_id="foo")
    assert out.id == "foo"


def test_render_spec_empty_list_renders_empty_container():
    out = render_spec([])
    assert out.id == "dyn-form"
    assert list(out.children) == []


def test_render_spec_one_stack_per_spec():
    out = render_spec(
        [{"name": "a", "type": "Text"}, {"name": "b", "type": "Slider"}]
    )
    assert len(out.children) == 2


def test_specs_round_trip_through_json():
    spec = [
        {"name": "rate", "type": "Slider", "value": 0.5, "props": {"min": 0, "max": 1}},
        {"name": "mode", "type": "Select", "props": {"data": ["a", "b"]}},
    ]
    round_tripped = json.loads(json.dumps(spec))
    out = render_spec(round_tripped)
    assert len(out.children) == 2


# --- DynamicDash construction ------------------------------------------------


def _collect_ids(component):
    out = set()
    cid = getattr(component, "id", None)
    if isinstance(cid, str):
        out.add(cid)
    children = getattr(component, "children", None)
    if children is None:
        return out
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        out.update(_collect_ids(child))
    return out


def test_dynamicdash_form_only_construction():
    app = DynamicDash(
        callback_fn=lambda n_categories=5: f"got {n_categories}",
        parent_control={
            "name": "chart_type",
            "type": "Select",
            "props": {"data": ["bar", "scatter"]},
            "value": "bar",
        },
        spec_resolver=lambda v: [{"name": "n_categories", "type": "Slider"}],
        output_components=[Markdown],
    )
    ids = _collect_ids(app.app.layout)
    assert "dyn-parent" in ids
    assert "dyn-form" in ids
    assert "dyn-run" in ids
    assert "dyn-output-0" in ids


def test_dynamicdash_no_mcp_wiring_by_default():
    """When mcp_server=False (default), no Interval is in the layout."""
    app = DynamicDash(
        callback_fn=lambda x=1: x,
        initial_specs=[{"name": "x", "type": "Text"}],
        output_components=[Markdown],
    )
    ids = _collect_ids(app.app.layout)
    assert "_mcp_poll" not in ids
    assert app._mcp_state is None


def test_dynamicdash_mcp_server_true_adds_poll_interval():
    """With mcp_server=True, the drain Interval and MCPState are wired."""
    app = DynamicDash(
        callback_fn=lambda x=1: x,
        initial_specs=[{"name": "x", "type": "Text"}],
        output_components=[Markdown],
        mcp_server=True,
    )
    ids = _collect_ids(app.app.layout)
    assert "_mcp_poll" in ids
    assert app._mcp_state is not None


def test_dynamicdash_rejects_parent_without_resolver():
    with pytest.raises(ValueError, match="parent_control was given"):
        DynamicDash(
            callback_fn=lambda: None,
            parent_control={"name": "x", "type": "Select"},
            spec_resolver=None,
            output_components=[Markdown],
        )


def test_dynamicdash_captures_param_names():
    def fn(a, b=1, c=2):
        return a

    app = DynamicDash(callback_fn=fn, output_components=[Markdown])
    assert app._callback_param_names == {"a", "b", "c"}
    assert app._has_var_kw is False


def test_dynamicdash_detects_var_kw():
    def fn(**fields):
        return fields

    app = DynamicDash(callback_fn=fn, output_components=[Markdown])
    assert app._callback_param_names == set()
    assert app._has_var_kw is True


def test_dynamicdash_var_kw_with_positional_named_params():
    def fn(a, b=1, **rest):
        return a, b, rest

    app = DynamicDash(callback_fn=fn, output_components=[Markdown])
    assert app._callback_param_names == {"a", "b"}
    assert app._has_var_kw is True
