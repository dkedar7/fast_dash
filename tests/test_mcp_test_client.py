"""app.mcp_test_client(): the agent surface in-process, without a server (#325)."""

import importlib.util
import json

import pytest

from fast_dash import DynamicDash, FastDash, Text
from fast_dash.mcp import MCPError, MCPTestClient

requires_fastapi = pytest.mark.skipif(
    importlib.util.find_spec("fastapi") is None,
    reason="fastapi backend extra not installed",
)


def bars(n: int = 3, color: str = "#ff0000") -> int:
    """Double n."""
    return n * 2


def _wire(app, name, args):
    """The same call as a raw JSON-RPC POST, as an agent would send it."""
    client = app.app.server.test_client()
    rpc = lambda method, params: client.post(
        "/mcp", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
        headers={"Content-Type": "application/json"}).get_json()
    rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "0"}})
    return rpc("tools/call", {"name": name, "arguments": args})["result"]["structuredContent"]["result"]


def test_tools_are_methods_returning_json():
    client = FastDash(callback_fn=bars, mcp_server=True).mcp_test_client()
    assert isinstance(client, MCPTestClient)
    assert {"describe_app", "invoke", "set_input", "get_invocation"} <= set(client.tools)
    assert [i["id"] for i in client.describe_app()["inputs"]] == ["n", "color"]

    assert client.set_input("n", 5) == {"ok": True, "id": "n", "value": 5}   # positional
    result = client.invoke()
    assert result["ok"] and result["outputs"] == {"output_output_1": 10}
    assert client.get_invocation(index=0)["outputs"] == {"output_output_1": 10}


def test_errors_are_the_agents_errors():
    app = FastDash(callback_fn=bars, mcp_server=True)
    client = app.mcp_test_client()
    bad = client.invoke(inputs={"n": "x"})
    assert bad == _wire(app, "invoke", {"inputs": {"n": "x"}})
    assert bad["ok"] is False and bad["errors"]["n"].startswith("expected an integer")


def test_unknown_tool_and_too_many_arguments():
    client = FastDash(callback_fn=bars, mcp_server=True).mcp_test_client()
    with pytest.raises(AttributeError):
        client.not_a_tool
    with pytest.raises(MCPError, match="no tool named"):
        client.call("not_a_tool")
    with pytest.raises(TypeError):
        client.set_input("n", 5, "extra")


def test_needs_mcp_server():
    with pytest.raises(RuntimeError, match="mcp_server=True"):
        FastDash(callback_fn=bars).mcp_test_client()


def test_image_outputs_come_back_as_bytes():
    import PIL.Image

    def draw(w: int = 4) -> PIL.Image.Image:
        return PIL.Image.new("RGB", (w, 2), "red")

    with FastDash(callback_fn=draw, mcp_server=True).mcp_test_client() as client:
        result = client.invoke(inputs={"w": 6})
    assert result["ok"]
    assert len(result.images) == 1 and result.images[0].startswith(b"\x89PNG")


def test_dynamic_dash_set_form():
    def echo(**kw):
        return repr(kw)

    client = DynamicDash(callback_fn=echo, output_components=[Text], mcp_server=True).mcp_test_client()
    assert client.set_form(specs=[{"name": "x", "type": "NumberInput"}])["ok"]
    assert [i["id"] for i in client.describe_app()["inputs"]] == ["x"]


@requires_fastapi
def test_fastapi_backend():
    client = FastDash(callback_fn=bars, mcp_server=True, backend="fastapi").mcp_test_client()
    assert client.invoke(inputs={"n": 4})["outputs"] == {"output_output_1": 8}
    assert client.invoke(inputs={"n": "x"})["ok"] is False
