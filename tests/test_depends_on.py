#!/usr/bin/env python
"""Tests for the ``depends_on`` reactive-input helper.

``depends_on`` wires a dependent input's options / value to a parent input's
value. Resolver return-type semantics:

- **list**   → sets the component's ``data`` (dropdown options), clears value
- **dict**   → sets ``data`` / ``value`` from the dict
- **scalar** → sets the component's ``value``
- **None parent value** → no update
- **resolver raises** → no update (silently swallowed)
"""
import warnings

import dash

from fast_dash import FastDash, depends_on
from fast_dash.Components import _infer_input_components


# --- class contract ---


def test_depends_on_stores_parent_and_resolver():
    resolver = lambda v: [v, v.upper()]
    d = depends_on("country", resolver)
    assert d.parent == "country"
    assert d.resolver is resolver


# --- _infer_input_components picks it up ---


def test_depends_on_default_produces_select_with_metadata():
    resolver = lambda v: ["a", "b"]

    def pick(
        country: str = ["USA"],
        state: str = depends_on("country", resolver),
    ) -> str:
        return state

    comps = _infer_input_components(pick)
    state_comp = comps[1]
    assert state_comp.component.__class__.__name__ == "Select"
    assert state_comp._depends_on_parent == "country"
    assert state_comp._depends_on_resolver is resolver


def test_depends_on_does_not_affect_non_dependent_inputs():
    def pick(
        country: str = ["USA"],
        state: str = depends_on("country", lambda v: ["a"]),
    ) -> str:
        return state

    comps = _infer_input_components(pick)
    country_comp = comps[0]
    assert not hasattr(country_comp, "_depends_on_parent")


# --- FastDash app integration ---


def _countries():
    return {
        "USA": ["California", "Texas", "New York"],
        "India": ["Maharashtra", "Karnataka", "Delhi"],
    }


def test_app_builds_with_depends_on():
    countries = _countries()

    def pick(
        country: str = list(countries.keys()),
        state: str = depends_on("country", lambda v: countries[v]),
    ) -> str:
        return f"{state}, {country}"

    app = FastDash(callback_fn=pick)
    assert app.app.layout is not None


def test_app_registers_extra_callback_for_dependency():
    """Registering a depends_on input should add a callback beyond the baseline."""
    def baseline(country: str = ["USA"]) -> str:
        return country

    baseline_count = len(FastDash(callback_fn=baseline).app.callback_map)

    def with_dep(
        country: str = ["USA"],
        state: str = depends_on("country", lambda v: [v, v.upper()]),
    ) -> str:
        return state

    dep_count = len(FastDash(callback_fn=with_dep).app.callback_map)
    assert dep_count > baseline_count


def test_depends_on_unknown_parent_emits_warning():
    """Invalid parent reference should warn but still build a working app."""
    def pick(
        country: str = ["USA"],
        state: str = depends_on("nonexistent_param", lambda v: [v]),
    ) -> str:
        return state

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app = FastDash(callback_fn=pick)
        messages = [str(w.message) for w in caught]

    assert any("nonexistent_param" in m for m in messages)
    assert app.app.layout is not None


# --- resolver-return-type semantics ---
# We test the pure helper _apply_dependency_resolver since Dash's registered
# callback is wrapped in a request-context decorator that we can't invoke
# from a unit test.


def test_resolver_list_sets_data_and_clears_value():
    data, value = FastDash._apply_dependency_resolver(lambda v: ["a", "b", "c"], "USA")
    assert data == ["a", "b", "c"]
    assert value is None


def test_resolver_dict_sets_data_and_value():
    data, value = FastDash._apply_dependency_resolver(
        lambda v: {"data": ["x", "y"], "value": "x"}, "USA"
    )
    assert data == ["x", "y"]
    assert value == "x"


def test_resolver_dict_partial_only_sets_provided_keys():
    data, value = FastDash._apply_dependency_resolver(
        lambda v: {"value": "only-value"}, "USA"
    )
    assert data is dash.no_update
    assert value == "only-value"


def test_resolver_scalar_sets_value_only():
    data, value = FastDash._apply_dependency_resolver(
        lambda v: f"Capital of {v}", "USA"
    )
    assert data is dash.no_update
    assert value == "Capital of USA"


def test_resolver_exception_is_swallowed():
    def bad(v):
        raise RuntimeError("kaboom")
    data, value = FastDash._apply_dependency_resolver(bad, "USA")
    assert data is dash.no_update
    assert value is dash.no_update


def test_resolver_none_parent_returns_no_update():
    data, value = FastDash._apply_dependency_resolver(lambda v: [v], None)
    assert data is dash.no_update
    assert value is dash.no_update


def test_resolver_receives_parent_value():
    """The resolver should be called with the parent's current value."""
    received = []

    def spy(v):
        received.append(v)
        return [v]

    FastDash._apply_dependency_resolver(spy, "India")
    assert received == ["India"]


def test_nested_depends_on_chain_builds():
    """A → B → C: three-level chain should still build a working app."""
    def pick(
        continent: str = ["Asia", "Americas"],
        country: str = depends_on("continent", lambda v: ["India"] if v == "Asia" else ["USA"]),
        state: str = depends_on("country", lambda v: ["Karnataka"] if v == "India" else ["California"]),
    ) -> str:
        return f"{state}, {country}, {continent}"

    app = FastDash(callback_fn=pick)
    assert app.app.layout is not None
    # Two dependency callbacks registered (one each for country and state)
    dep_ids = {c.id for c in app.inputs_with_ids if hasattr(c, "_depends_on_parent")}
    assert dep_ids == {"country", "state"}
