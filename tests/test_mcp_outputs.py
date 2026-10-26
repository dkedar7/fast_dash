"""MCP output values and single-select validation.

#261 an agent reads an output's value, not the 80-char history preview:
     text whole, a table's rows, a figure's data; only past a size cap is it
     clipped (and marked ``truncated``).
#194 an output derived from a PasswordInput stays masked on every read
     surface, describe_app included.
#267 a single-select (str list default, Literal, Enum) rejects a JSON array.
"""
import enum
import json
import typing

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from fast_dash import FastDash, PasswordInput
from fast_dash.utils import _output_for_mcp

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


# --- #261 ------------------------------------------------------------------ #

@pytest.mark.parametrize("n", [200, 201, 532])
def test_long_text_output_comes_back_whole_everywhere(n):
    def echo(n: int = 1) -> str:
        return "x" * n
    call = _mcp(FastDash(callback_fn=echo, mcp_server=True))
    assert call("invoke", {"inputs": {"n": n}})["outputs"]["output_output_1"] == "x" * n
    assert call("describe_app")["outputs"][0]["current_value"] == "x" * n
    inv = call("get_invocation", {"index": 0})
    assert inv["outputs"]["output_output_1"] == "x" * n
    assert "outputs_summary" in inv                       # compact form kept


def test_table_output_carries_its_rows():
    def table(k: int = 2) -> pd.DataFrame:
        return pd.DataFrame({"city": ["NYC", "Austin"][:k], "pop": np.array([8.3, 0.97])[:k],
                             "when": pd.date_range("2024-01-01", periods=k)})
    out = _mcp(FastDash(callback_fn=table, mcp_server=True))("invoke")["outputs"]["output_output_1"]
    assert out["shape"] == [2, 3] and out["truncated"] is False
    assert out["records"][0]["city"] == "NYC" and out["records"][0]["pop"] == 8.3
    assert out["records"][0]["when"].startswith("2024-01-01")


def test_figure_output_carries_plain_arrays():
    def fig(n: int = 3) -> go.Figure:
        return go.Figure(go.Scatter(x=np.arange(n), y=np.array([1.5, 2.0, 3.0])[:n]))
    data = _mcp(FastDash(callback_fn=fig, mcp_server=True))("invoke")["outputs"]["output_output_1"]["data"][0]
    assert data["x"] == [0, 1, 2] and data["y"] == [1.5, 2.0, 3.0]   # not base64 "bdata"


def test_huge_output_is_clipped_and_marked():
    out = _output_for_mcp("y" * 600, cap=100)
    assert out == {"type": "str", "len": 600, "text": "y" * 100, "truncated": True}
    df = pd.DataFrame({"a": range(500)})
    assert _output_for_mcp(df)["truncated"] is True and len(_output_for_mcp(df)["records"]) == 100


def test_images_and_data_urls_stay_summarized():
    out = _output_for_mcp("data:image/png;base64," + "A" * 5000)
    assert out["type"] == "data_url" and "A" * 100 not in json.dumps(out)


# --- #194 on describe_app -------------------------------------------------- #

def test_secret_derived_output_masked_on_every_surface():
    def login(key: PasswordInput = "hunter2-secret") -> str:
        return f"using {key}"
    call = _mcp(FastDash(callback_fn=login, mcp_server=True))
    payloads = [call("invoke"), call("describe_app"), call("get_invocation", {"index": 0})]
    for p in payloads:
        assert "hunter2" not in json.dumps(p)


# --- #267 ------------------------------------------------------------------ #

class Color(enum.Enum):
    RED = "red"
    GREEN = "green"


def _pick(flavor: str = ["vanilla", "choco", "mint"], lit: typing.Literal["p", "q"] = "p",
          col: Color = Color.RED, many: list = ["a", "b"]) -> str:
    return f"{flavor!r}|{lit!r}|{col!r}|{many!r}"


@pytest.mark.parametrize("key, value", [
    ("flavor", ["choco", "mint"]), ("flavor", ["choco"]), ("lit", ["p", "q"]), ("col", ["red"]),
])
def test_single_select_rejects_an_array(key, value):
    call = _mcp(FastDash(callback_fn=_pick, mcp_server=True))
    res = call("invoke", {"inputs": {key: value}})
    assert res["ok"] is False and "single value" in res["errors"][key]
    assert call("set_input", {"component_id": key, "value": value})["ok"] is False


def test_scalars_and_multiselect_lists_still_accepted():
    call = _mcp(FastDash(callback_fn=_pick, mcp_server=True))
    out = call("invoke", {"inputs": {"flavor": "choco", "col": "green", "many": ["a"]}})
    assert out["ok"] is True
    assert out["outputs"]["output_output_1"] == "'choco'|'p'|<Color.GREEN: 'green'>|['a']"


# --- #270: the mirror of #267 ---------------------------------------------- #

def _many(items: list = ["apple", "banana", "cherry"], cfg: dict = {"a": 1, "b": 2}) -> str:
    return f"{type(items).__name__}:{items!r}|{type(cfg).__name__}:{cfg!r}"


@pytest.mark.parametrize("key, value", [("items", "apple"), ("cfg", "a")])
def test_multiselect_rejects_a_bare_option(key, value):
    call = _mcp(FastDash(callback_fn=_many, mcp_server=True))
    res = call("invoke", {"inputs": {key: value}})
    assert res["ok"] is False and "expected an array" in res["errors"][key]
    assert call("set_input", {"component_id": key, "value": value})["ok"] is False


def test_multiselect_still_takes_a_list():
    out = _mcp(FastDash(callback_fn=_many, mcp_server=True))(
        "invoke", {"inputs": {"items": ["apple"], "cfg": ["b"]}})
    assert out["outputs"]["output_output_1"] == "list:['apple']|dict:{'b': 2}"


def test_dynamic_multiselect_rejects_a_bare_option():
    from fast_dash import DynamicDash, Markdown

    def echo(**fields):
        return repr(fields)
    call = _mcp(DynamicDash(callback_fn=echo, output_components=[Markdown], mcp_server=True))
    call("set_form", {"specs": [{"name": "tags", "type": "MultiSelect",
                                 "props": {"data": ["x", "y"]}}]})
    assert call("set_input", {"component_id": "tags", "value": "x"})["ok"] is False
    assert call("set_input", {"component_id": "tags", "value": ["x"]})["ok"] is True


# --- #275: GET /mcp is the readiness signal the docs promise --------------- #

def test_get_mcp_is_a_readiness_signal():
    def f(n: int = 1) -> str:
        return str(n)
    r = FastDash(callback_fn=f, mcp_server=True).app.server.test_client().get("/mcp")
    assert r.status_code == 200 and r.mimetype == "text/event-stream"
    assert "mcp stream open" in r.get_data(as_text=True)


def test_get_mcp_without_mcp_server_is_the_web_page():
    def f(n: int = 1) -> str:
        return str(n)
    r = FastDash(callback_fn=f).app.server.test_client().get("/mcp")
    assert r.mimetype == "text/html" and "mcp stream open" not in r.get_data(as_text=True)


# --- #279: a depends_on child re-runs when the parent changes over MCP ------ #

def test_scalar_dependent_reruns_on_parent_change():
    from fast_dash import depends_on

    def calc(base: int = 10, derived: int = depends_on("base", lambda b: b * 2)) -> str:
        return f"base={base} derived={derived}"
    call = _mcp(FastDash(callback_fn=calc, mcp_server=True))
    assert call("set_input", {"component_id": "base", "value": 7})["updated"] == ["derived"]
    assert call("invoke")["outputs"]["output_output_1"] == "base=7 derived=14"
    assert call("invoke", {"inputs": {"base": 3}})["outputs"]["output_output_1"] == "base=3 derived=6"
    # a child the agent sets in the same call keeps the agent's value
    out = call("invoke", {"inputs": {"base": 5, "derived": 99}})
    assert out["outputs"]["output_output_1"] == "base=5 derived=99"


# --- #280: chat artifacts are resolved, not "pending", over MCP ------------- #

def test_chat_artifacts_resolve_over_mcp():
    def analyst(query: str, history: list):
        yield "Here: "
        yield {"type": "artifact", "content": go.Figure(go.Scatter(x=[1, 2, 3], y=[1, 4, 9]))}
        yield {"type": "artifact", "content": pd.DataFrame({"a": [1, 2]})}
    res = _mcp(FastDash(callback_fn=analyst, chat=True, mcp_server=True))("invoke", {"query": "go"})
    arts = [f for f in res["frames"] if f["type"] == "artifact"]
    assert len(arts) == 2 and not any("pending" in f for f in arts)
    assert arts[0]["content"]["data"][0]["y"] == [1, 4, 9]
    assert arts[1]["content"]["records"] == [{"a": 1}, {"a": 2}]


# --- #282: set_form counts inputs; display-only types are named ------------- #

def test_set_form_count_matches_inputs_and_display_only_is_named():
    from fast_dash import DynamicDash, Markdown

    def score(**kw):
        return repr(kw)
    call = _mcp(DynamicDash(callback_fn=score, output_components=[Markdown], mcp_server=True))
    res = call("set_form", {"specs": [{"name": "a", "type": "Text"},
                                      {"name": "note", "type": "Markdown", "props": {"children": "hi"}}]})
    assert res == {"ok": True, "count": 1, "display_only": 1}
    assert len(call("describe_app")["inputs"]) == 1
    types = call("list_component_types")
    assert types["display_only"] == ["Markdown"] and "Markdown" in types["types"]


# --- #283: an unannotated rich return is described by what it returned ------ #

@pytest.mark.parametrize("make, kind", [
    (lambda: pd.DataFrame({"x": [1, 2]}), ("Table", "array")),
    (lambda: go.Figure(go.Bar(y=[1, 2])), ("Graph", "object")),
    (lambda: "plain text", ("Text", "string")),
])
def test_unannotated_output_kind_after_a_run(make, kind):
    def fn(n: int = 1):
        return make()
    call = _mcp(FastDash(callback_fn=fn, mcp_server=True))
    call("invoke")
    out = call("describe_app")["outputs"][0]
    assert (out["tag"], out["type"]) == kind


# --- #295: text widgets take strings ---------------------------------------- #

def test_str_input_rejects_a_number():
    def greet(name: str = "x") -> str:
        return name.upper()
    call = _mcp(FastDash(callback_fn=greet, mcp_server=True))
    assert call("invoke", {"inputs": {"name": 99}})["errors"]["name"].startswith("expected a string")
    assert call("set_input", {"component_id": "name", "value": True})["ok"] is False
    assert call("invoke", {"inputs": {"name": "ok"}})["outputs"]["output_output_1"] == "OK"


# --- #288: date vs date-and-time ------------------------------------------- #

def test_date_and_datetime_inputs_are_distinct_and_enforced():
    import datetime as dt

    def book(d: dt.date = dt.date(2026, 1, 1), t: dt.datetime = dt.datetime(2026, 1, 1, 9, 30)) -> str:
        return f"{type(d).__name__} {type(t).__name__}"
    call = _mcp(FastDash(callback_fn=book, mcp_server=True))
    ins = {i["id"]: i for i in call("describe_app")["inputs"]}
    assert (ins["d"]["tag"], ins["d"]["props"]["format"]) == ("DateInput", "YYYY-MM-DD")
    assert (ins["t"]["tag"], ins["t"]["props"]["format"]) == ("DateTimeInput", "YYYY-MM-DD HH:mm:ss")
    assert call("set_input", {"component_id": "d", "value": "2026-03-04 17:45:00"})["ok"] is False
    out = call("invoke", {"inputs": {"d": "2026-03-04", "t": "2026-03-04 17:45:00"}})
    assert out["outputs"]["output_output_1"] == "date datetime"


# --- #294: chat settings are held to their contract ------------------------ #

def test_chat_settings_are_type_checked():
    def assistant(query: str, temperature: float = 0.7, verbose: bool = False):
        yield f"t={temperature!r} v={verbose!r}"
    call = _mcp(FastDash(callback_fn=assistant, chat=True, mcp_server=True))
    bad = call("invoke", {"query": "hi", "settings": {"temperature": "x", "verbose": "maybe"}})
    assert bad["ok"] is False and set(bad["errors"]) == {"temperature", "verbose"}
    good = call("invoke", {"query": "hi", "settings": {"temperature": 0.2, "verbose": True}})
    assert good["content"] == "t=0.2 v=True"


# --- #297: get_dash_component works on Fast Dash's containers -------------- #

@pytest.mark.parametrize("cid", ["submit_inputs", "appshell"])
def test_get_dash_component_serializes_containers(cid):
    def f(n: int = 1) -> str:
        return str(n)
    client = FastDash(callback_fn=f, mcp_server=True).app.server.test_client()

    def rpc(method, params=None):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        return client.post("/mcp", data=json.dumps(body),
                           headers={"Content-Type": "application/json"}).get_json()
    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}})
    res = rpc("tools/call", {"name": "get_dash_component", "arguments": {"component_id": cid}})
    assert "error" not in res
    assert res["result"]["structuredContent"]["component_id"] == cid
    assert "children" in res["result"]["structuredContent"]["properties"]


# --- #305 ------------------------------------------------------------------ #

def test_figure_template_is_named_not_inlined():
    def plot_bars(n: int = 3) -> go.Figure:
        return go.Figure(go.Bar(y=list(range(n))), layout={"title": "Bars"})
    call = _mcp(FastDash(callback_fn=plot_bars, mcp_server=True))
    fig = next(iter(call("invoke", {"inputs": {"n": 3}})["outputs"].values()))
    assert fig["layout"]["template"] == "plotly"
    assert fig["layout"]["title"] == {"text": "Bars"}
    assert fig["data"][0]["y"] == [0, 1, 2]
    assert len(json.dumps(fig)) < 500


def test_figure_custom_template_is_dropped():
    fig = go.Figure(layout={"template": {"layout": {"font": {"size": 30}}}})
    assert "template" not in _output_for_mcp(fig)["layout"]
    assert _output_for_mcp(go.Figure(layout={"template": "plotly_dark"}))["layout"]["template"] == "plotly_dark"
