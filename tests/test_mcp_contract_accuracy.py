"""Regression tests for MCP contract accuracy (0.7.0 batch 5).

#198 component-class hints (``level: Slider = 3``) advertise and enforce the
     widget's JSON type, not "string".
#218 a DateRange input is an array of two ISO dates, and enforced as one.
#238 describe_app marks inputs with no default as required; invoke names them.
#242 a datetime input keeps its time on both surfaces.
#237 a single output's list return stays whole over MCP.
#199 a DynamicDash field left at its default is passed to the callback.
#220 DynamicDash Markdown blocks are not inputs.
"""
import datetime
import json
from typing import Optional

import pytest

from fast_dash import (
    DateRange, DynamicDash, FastDash, Graph, Markdown, NumberInput, Slider, Switch,
)

pytest.importorskip("dash.mcp")


def _mcp(app):
    client = app.app.server.test_client()

    def rpc(method, params=None):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        return client.post("/mcp", data=json.dumps(body),
                           headers={"Content-Type": "application/json"}).get_json()

    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}})

    def call(name, args=None):
        res = rpc("tools/call", {"name": name, "arguments": args or {}})["result"]
        return res["structuredContent"]["result"]
    return call


def _inputs(call):
    return {i["id"]: i for i in call("describe_app")["inputs"]}


# --- #198 ------------------------------------------------------------------ #

def test_component_class_hints_advertise_widget_type():
    def rate(level: Slider = 3, num: NumberInput = 5, flag: Switch = True) -> str:
        return f"{level * 2}"
    call = _mcp(FastDash(callback_fn=rate, mcp_server=True))
    ins = _inputs(call)
    assert (ins["level"]["type"], ins["num"]["type"], ins["flag"]["type"]) == (
        "number", "number", "boolean")
    assert call("set_input", {"component_id": "level", "value": "abc"})["ok"] is False
    assert call("set_input", {"component_id": "flag", "value": "yes"})["ok"] is False
    assert call("invoke", {"inputs": {"level": 4}})["outputs"] == {"output_output_1": "8"}


def test_builtin_hints_unchanged():
    def f(a: int = 1, b: str = "x", c: float = 1.5) -> str:
        return "ok"
    ins = _inputs(_mcp(FastDash(callback_fn=f, mcp_server=True)))
    assert [ins[k]["type"] for k in "abc"] == ["integer", "string", "number"]


# --- #218 ------------------------------------------------------------------ #

def test_date_range_is_an_enforced_array():
    def span(rng) -> str:
        return f"{type(rng).__name__}"
    call = _mcp(FastDash(callback_fn=span, inputs=[DateRange], mcp_server=True))
    (cid, entry), = _inputs(call).items()
    assert entry["type"] == "array"
    bad = call("invoke", {"inputs": {cid: "2025-01-01"}})
    assert bad["ok"] is False
    assert call("invoke", {"inputs": {cid: ["2025-01-01", "nope"]}})["ok"] is False
    good = call("invoke", {"inputs": {cid: ["2025-01-01", "2025-01-31"]}})
    assert good["outputs"] == {"output_output_1": "list"}


# --- #238 ------------------------------------------------------------------ #

def test_required_inputs_are_marked_and_named():
    def f(req: int, opt: Optional[int] = None) -> str:
        return f"req={req} opt={opt}"
    call = _mcp(FastDash(callback_fn=f, mcp_server=True))
    ins = _inputs(call)
    assert ins["req"]["required"] is True and ins["opt"]["required"] is False
    out = call("invoke")
    assert out["ok"] is False and out["missing"] == ["req"]
    assert call("invoke", {"inputs": {"req": 3}})["outputs"] == {
        "output_output_1": "req=3 opt=None"}


# --- #242 ------------------------------------------------------------------ #

def test_datetime_keeps_its_time_on_both_surfaces():
    from fast_dash.utils import _transform_inputs

    def meeting(when: datetime.datetime = datetime.datetime(2024, 1, 1, 12, 30, 45)) -> str:
        return f"{when.hour:02d}:{when.minute:02d}:{when.second:02d} {type(when).__name__}"
    app = FastDash(callback_fn=meeting, mcp_server=True)
    call = _mcp(app)
    entry = _inputs(call)["when"]
    assert entry["default"] == entry["current_value"] == "2024-01-01 12:30:45"
    assert call("invoke")["outputs"] == {"output_output_1": "12:30:45 datetime"}
    comp = app.inputs_with_ids[0]
    ui = app.callback_fn(*_transform_inputs([comp.value], app.input_tags, app.inputs_with_ids))
    assert ui == "12:30:45 datetime"


# --- #237 ------------------------------------------------------------------ #

def test_single_output_list_return_stays_whole():
    def list_tags(prefix: str = "tag") -> list:
        return [f"{prefix}-{i}" for i in range(3)]
    call = _mcp(FastDash(callback_fn=list_tags, mcp_server=True))
    assert call("invoke")["outputs"] == {"output_output_1": ["tag-0", "tag-1", "tag-2"]}


def test_tuple_return_still_fans_out():
    def two(n: int = 1):
        return n, n + 1
    call = _mcp(FastDash(callback_fn=two, outputs=["Text", "Text"], mcp_server=True))
    assert list(call("invoke")["outputs"].values()) == [1, 2]


# --- #199 / #220 ----------------------------------------------------------- #

def _score(**fields):
    return None, ", ".join(f"{k}={v}" for k, v in fields.items())


def test_dynamic_placeholder_is_not_an_input():
    app = DynamicDash(callback_fn=_score, placeholder="Ask the agent.",
                      output_components=[Graph, Markdown], mcp_server=True)
    call = _mcp(app)
    assert _inputs(call) == {}
    out = call("set_input", {"component_id": "_hint", "value": "x"})
    assert out["ok"] is False and "set_form" in out["error"]


def test_dynamic_defaults_reach_the_callback_and_markdown_does_not():
    app = DynamicDash(callback_fn=_score, placeholder="Ask the agent.",
                      output_components=[Graph, Markdown], mcp_server=True)
    call = _mcp(app)
    call("set_form", {"specs": [
        {"name": "a", "type": "Slider", "props": {"min": 0, "max": 10}, "default": 4},
        {"name": "b", "type": "NumberInput", "value": 7},
        {"name": "note", "type": "Markdown", "props": {"children": "hi"}},
    ]})
    assert set(_inputs(call)) == {"a", "b"}
    assert call("invoke")["outputs"]["dyn-output-1"] == "a=4, b=7"
    call("set_input", {"component_id": "b", "value": 9})
    assert call("invoke")["outputs"]["dyn-output-1"] == "a=4, b=9"
    assert call("set_input", {"component_id": "note", "value": "x"})["ok"] is False
