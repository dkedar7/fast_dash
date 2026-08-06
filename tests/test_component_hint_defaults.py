#!/usr/bin/env python
"""A Fast Dash component used as a type hint honours the signature default (#188).

Deliberately WITHOUT ``from __future__ import annotations``: under string
annotations ``level: Slider`` never resolves to the component object, so these
would silently exercise a text input instead and pass for the wrong reason.
"""
from fast_dash import FastDash, Slider


def _value(app):
    component = app.inputs_with_ids[0]
    return getattr(component, component.component_property, "<missing>")


def test_component_hint_honours_the_signature_default():
    # The exported Slider ships value=10 baked in and was used as-is, so
    # `level: Slider = 3` silently ran the callback with 10 while the UI handle
    # rendered at 10 too -- the documented "component used directly" pattern
    # quietly ignoring the declared default.
    def fn(level: Slider = 3) -> str:
        """Echo."""
        return f"got {level}"

    assert _value(FastDash(callback_fn=fn)) == 3


def test_component_hint_without_a_default_keeps_the_builtin_value():
    def fn(level: Slider) -> str:
        """Echo."""
        return f"got {level}"

    assert _value(FastDash(callback_fn=fn)) == 10


def test_component_hint_default_does_not_leak_across_apps():
    # The exported components are shared module-level singletons, so applying a
    # default must copy rather than rebind them for every later app.
    def first(level: Slider = 3) -> str:
        """A."""
        return str(level)

    def second(level: Slider) -> str:
        """B."""
        return str(level)

    assert _value(FastDash(callback_fn=first)) == 3
    assert _value(FastDash(callback_fn=second)) == 10
    assert Slider.value == 10           # the shared export is untouched
