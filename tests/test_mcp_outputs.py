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
