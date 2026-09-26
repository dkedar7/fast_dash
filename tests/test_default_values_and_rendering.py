"""Regression tests for the 0.7.0 default-value / rendering batch.

#204 option-list defaults start on a real value (UI + MCP), and depends_on
     cascades to its first option on load (#246).
#219 ``int = range(...)`` Slider starts on the range start, never None.
#231 a ``dict`` param receives a dict, not a list of key strings.
#217 an unannotated Figure / DataFrame return renders as a component.
#201 output labels come from the returned variable names only.
"""
import json
import warnings

import pandas as pd
import plotly.express as px
import pytest

from fast_dash import FastDash, depends_on
from fast_dash.utils import _transform_inputs, _transform_outputs

warnings.filterwarnings("ignore")


def _ui_default_run(app):
    """What a browser Run with untouched inputs submits to the callback."""
    vals = [getattr(c, c.component_property, None) for c in app.inputs_with_ids]
    return app.callback_fn(*_transform_inputs(vals, app.input_tags, app.inputs_with_ids))


def _invoke(app, arguments=None):
    client = app.app.server.test_client()

    def rpc(method, params=None):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        return client.post("/mcp", data=json.dumps(body),
                           headers={"Content-Type": "application/json"}).get_json()

    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}})
    res = rpc("tools/call", {"name": "invoke", "arguments": arguments or {}})
    return res["result"]["structuredContent"]["result"]["outputs"]


dash_mcp = pytest.importorskip("dash.mcp")


# --- #204 ------------------------------------------------------------------ #

def test_str_options_default_starts_on_first_option():
    def pick(mode: str = ["fast", "slow"]) -> str:
        return f"mode={mode!r}"
    app = FastDash(callback_fn=pick, mcp_server=True)
    assert _ui_default_run(app) == "mode='fast'"
    assert _invoke(app) == {"output_output_1": "mode='fast'"}


def test_list_multiselect_default_is_empty_list_not_none():
    def join(tags: list = ["x", "y"]) -> str:
        return ",".join(tags)                     # crashed on None before
    app = FastDash(callback_fn=join)
    assert _ui_default_run(app) == ""


def test_unannotated_list_default_is_a_working_select():
    def pick(fruit=["apple", "pear"]):
        return fruit
    app = FastDash(callback_fn=pick)
    comp = app.inputs_with_ids[0]
    assert comp.component_property == "value"
    assert comp.value == "apple"


def test_depends_on_cascades_to_first_option_on_load():
    countries = {"USA": ["California", "Texas"], "India": ["Delhi", "Goa"]}

    def pick_state(country: str = list(countries),
                   state: str = depends_on("country", lambda c: countries[c])) -> str:
        return f"{state}, {country}"
    app = FastDash(callback_fn=pick_state, mcp_server=True)
    # browser: parent starts on "USA", the cascade picks the first state
    assert FastDash._apply_dependency_resolver(lambda c: countries[c], "USA") == (
        ["California", "Texas"], "California")
    # agent: invoke with no inputs gives the same answer
    assert _invoke(app) == {"output_output_1": "California, USA"}
    # changing the parent resets the stale dependent to the new first option
    assert _invoke(app, {"inputs": {"country": "India"}}) == {
        "output_output_1": "Delhi, India"}


def test_depends_on_scalar_resolver_seeds_mcp():
    def f(x: str = ["a", "b"], y: str = depends_on("x", lambda v: v.upper())) -> str:
        return f"{x}{y}"
    app = FastDash(callback_fn=f, mcp_server=True)
    assert _invoke(app) == {"output_output_1": "aA"}


# --- #219 ------------------------------------------------------------------ #

def test_range_slider_starts_on_range_start():
    def double(level: int = range(3, 10)) -> int:
        return level * 2
    app = FastDash(callback_fn=double, mcp_server=True)
    assert app.inputs_with_ids[0].value == 3
    assert _ui_default_run(app) == 6
    assert _invoke(app) == {"output_output_1": 6}


# --- #231 ------------------------------------------------------------------ #

def test_dict_param_receives_a_dict():
    def summarize(config: dict = {"lr": 1, "epochs": 2, 3: 4}) -> str:
        return f"{type(config).__name__}:{sorted(map(str, config))}:{sum(config.values())}"
    app = FastDash(callback_fn=summarize, mcp_server=True)
    full = "dict:['3', 'epochs', 'lr']:7"
    assert _ui_default_run(app) == full
    assert _invoke(app) == {"output_output_1": full}
    # a subset of keys maps back to the original (non-str) keys and values
    assert _invoke(app, {"inputs": {"config": ["lr", "3"]}}) == {
        "output_output_1": "dict:['3', 'lr']:5"}


# --- #217 ------------------------------------------------------------------ #

@pytest.mark.parametrize("make, expected", [
    (lambda: px.scatter(x=[1, 2], y=[3, 4]), "Graph"),
    (lambda: pd.DataFrame({"a": [1, 2]}), "DataTable"),
])
def test_unannotated_rich_return_renders_as_component(make, expected):
    def fn(n: int = 1):
        return make()
    app = FastDash(callback_fn=fn)
    out = _transform_outputs([fn()], app.output_tags, app.outputs_with_ids, 0)[0]
    assert type(out).__name__ == expected


def test_unannotated_scalar_return_still_plain_text():
    def fn(n: int = 1):
        return n + 1
    app = FastDash(callback_fn=fn)
    assert _transform_outputs([2], app.output_tags, app.outputs_with_ids, 0)[0] == 2


# --- #201 ------------------------------------------------------------------ #

def test_expression_return_gets_generic_label():
    def greet(name: str = "world") -> str:
        return f"Hello, {name}!"
    app = FastDash(callback_fn=greet)
    assert app.output_labels == ["OUTPUT_1"]


def test_variable_return_names_the_output():
    def clean(x: int = 1) -> str:
        answer = str(x)
        return answer
    app = FastDash(callback_fn=clean)
    assert app.output_labels == ["ANSWER"]


def test_nested_function_return_and_string_commas_ignored():
    from fast_dash.utils import _names_from_return
    src = '''
def pair(x):
    label = "a, b"
    def helper():
        return "nested, ignored"
    return x, label
'''
    assert _names_from_return(src) == ["x", "label"]


def test_string_literal_return_is_its_own_label():
    from fast_dash.utils import _names_from_return
    src = 'def f(x):\n    return x, "Return some text", "!!!"\n'
    assert _names_from_return(src, upper_case=True) == ["X", "RETURN_SOME_TEXT", "OUTPUT_3"]
