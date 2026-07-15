"""Tests for the native-Dash MCP app surface (v0.4+).

fast_dash mounts Dash's native MCP server (``dash.mcp.enable_mcp_server``) on
the same Flask app and registers its stateful "drive the app" tools via
``dash.mcp.mcp_enabled``. These tests drive the mounted ``/mcp`` endpoint with
Flask's test client.

Note: Dash's ``mcp_enabled`` registry is process-global and keyed by tool name,
so fast_dash supports one MCP-enabled app per process. The ``clear_mcp_registry``
fixture enforces that here by resetting the registry before each test.
"""

from __future__ import annotations

import datetime  # module-level so get_type_hints resolves date/datetime hints (#134)
import enum
import importlib.util
import json
import warnings
from typing import Annotated, Literal, Optional, Tuple  # module-level for get_type_hints (#119, #132)

import pandas as pd  # noqa: F401  (module-level for any -> pd.DataFrame hints)
import plotly.graph_objects as go
import pytest

from fast_dash import DynamicDash, FastDash, Graph, Markdown, PasswordInput
from fast_dash.mcp import MCPState, enable_mcp


# Module-level so get_type_hints resolves them under this file's future
# annotations (used by the #126 Enum-contract test).
class Flavor(enum.Enum):
    VANILLA = "vanilla"
    CHOCO = "choco"


class Qty(enum.IntEnum):
    ONE = 1
    TWO = 2

_HAS_DASH_MCP = importlib.util.find_spec("dash.mcp") is not None
requires_dash_mcp = pytest.mark.skipif(
    not _HAS_DASH_MCP, reason="Dash native MCP (dash>=4.3) not installed"
)
_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None
requires_fastapi = pytest.mark.skipif(
    not _HAS_FASTAPI, reason="fastapi backend extra not installed"
)
_HAS_LANGSTAGE = importlib.util.find_spec("langstage_core") is not None
requires_langstage = pytest.mark.skipif(
    not _HAS_LANGSTAGE, reason="langstage extra not installed"
)


def _layout_ids(comp, out=None):
    out = set() if out is None else out
    cid = getattr(comp, "id", None)
    if isinstance(cid, str):
        out.add(cid)
    ch = getattr(comp, "children", None)
    if ch is not None:
        for c in (ch if isinstance(ch, (list, tuple)) else [ch]):
            if c is not None:
                _layout_ids(c, out)
    return out


@pytest.fixture(autouse=True)
def clear_mcp_registry():
    """Reset Dash's global MCP tool registry before each test (one app/process)."""
    try:
        from dash.mcp import _decorator
        _decorator.MCP_DECORATED_FUNCTIONS.clear()
    except Exception:
        pass
    yield


# --- helpers --------------------------------------------------------------- #

def _client_for(app):
    """enable_mcp on a fast_dash app and return (flask_test_client, call helpers)."""
    enable_mcp(app)
    client = app.app.server.test_client()
    _rpc(client, "initialize")
    return client


def _rpc(client, method, params=None, _id=1):
    r = client.post(
        "/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": _id,
                         "method": method, "params": params or {}}),
        headers={"Content-Type": "application/json"},
    )
    return r.get_json()


def _tools(client):
    res = _rpc(client, "tools/list")
    return [t["name"] for t in res.get("result", {}).get("tools", [])]


def _resources(client):
    res = _rpc(client, "resources/list")
    return [r["uri"] for r in res.get("result", {}).get("resources", [])]


def _call(client, name, args=None):
    res = _rpc(client, "tools/call", {"name": name, "arguments": args or {}})
    r = res.get("result", res)
    if isinstance(r, dict) and "structuredContent" in r:
        return r["structuredContent"].get("result", r["structuredContent"])
    return r


def _exposure_warnings(fn):
    """The MCP no-auth warnings raised by ``fn`` (ignoring library noise)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fn()
    return [w for w in caught if "no authentication" in str(w.message)]


def _plain_app():
    def plot_bars(n: int = 6, color: str = "#1c7ed6") -> go.Figure:
        """Bar chart with n bars."""
        return go.Figure(go.Bar(x=list(range(n)), y=list(range(n))))
    return FastDash(callback_fn=plot_bars, mcp_server=True)


def _dynamic_app(**kw):
    def score(**fields):
        """Radar of submitted fields."""
        return go.Figure(), "ok"
    kw.setdefault("placeholder", "hi")
    return DynamicDash(callback_fn=score, output_components=[Graph, Markdown],
                       mcp_server=True, **kw)


# --- MCPState -------------------------------------------------------------- #

class TestBackendOptIn:
    """Opt-in ASGI backend: real-time WebSocket push instead of the Interval."""

    def _fig_app(self, **kw):
        def fig(n: int = 3) -> go.Figure:
            return go.Figure(go.Bar(x=list(range(n)), y=list(range(n))))
        return FastDash(callback_fn=fig, mcp_server=True, **kw)

    def test_flask_default_uses_polling_interval(self):
        app = self._fig_app()
        assert app._backend is None
        assert type(app.server).__name__ == "Flask"
        assert "_mcp_poll" in _layout_ids(app.app.layout)

    @requires_fastapi
    def test_fastapi_backend_drops_interval_for_websocket(self):
        app = self._fig_app(backend="fastapi")
        assert app._backend == "fastapi"
        assert type(app.server).__name__ == "FastAPI"
        # No client-side Interval: push is via the persistent WebSocket drain.
        assert "_mcp_poll" not in _layout_ids(app.app.layout)
        assert "_mcp_mirror_store" in _layout_ids(app.app.layout)

    @requires_fastapi
    @requires_dash_mcp
    def test_fastapi_mcp_installs_request_context_middleware(self):
        # #99: the native /mcp route needs the request context set on the ASGI
        # backend (DashMiddleware skips non-/_dash- routes). enable_mcp installs
        # a middleware to do that, or /mcp 500s.
        from fast_dash.mcp import enable_mcp

        app = self._fig_app(backend="fastapi")
        enable_mcp(app)
        names = [getattr(m.cls, "__name__", "") for m in app.app.server.user_middleware]
        assert any("MCPRequestContext" in n for n in names)

    def test_run_routes_to_asgi_on_backend(self, monkeypatch):
        # #99: run() must serve the ASGI app via uvicorn, not Dash's
        # frame-walking main-thread path.
        app = self._fig_app(backend="fastapi") if _HAS_FASTAPI else None
        if app is None:
            import pytest as _pytest
            _pytest.skip("fastapi not installed")
        called = {}
        monkeypatch.setattr(app, "_run_asgi", lambda: called.setdefault("asgi", True))
        monkeypatch.setattr(app, "_start_mcp_server", lambda: None)
        app.run()
        assert called.get("asgi") is True

    @requires_fastapi
    def test_stream_with_backend_uses_native_websocket(self):
        def fig(n: int = 3) -> go.Figure:
            return go.Figure()
        # stream + ASGI backend now builds the native-WebSocket streaming path
        # (set_props) instead of raising; legacy flask-socketio stays on Flask.
        app = FastDash(callback_fn=fig, stream=True, backend="fastapi")
        assert app._native_stream is True
        assert type(app.server).__name__ == "FastAPI"
        assert hasattr(app, "stream_handler_native")

    def test_stream_on_flask_stays_legacy(self):
        def fig(n: int = 3) -> go.Figure:
            return go.Figure()
        app = FastDash(callback_fn=fig, stream=True)
        assert app._native_stream is False
        assert type(app.server).__name__ == "Flask"


class TestMCPState:
    def test_history_roundtrip_and_index(self):
        s = MCPState(history_size=2)
        i0 = s.append_history({"a": 1}, {"a": 1, "full": True})
        i1 = s.append_history({"a": 2}, {"a": 2})
        assert (i0, i1) == (0, 1)
        assert s.full_history[0]["full"] is True

    def test_history_evicts_oldest(self):
        s = MCPState(history_size=2)
        for k in range(3):
            s.append_history({"k": k}, {"k": k})
        assert len(s.history) == 2 and len(s.full_history) == 2
        assert 0 not in s.full_history  # evicted

    def test_pop_pending_inputs_atomic_swap(self):
        s = MCPState()
        s.pending_inputs["x"] = 1
        out = s.pop_pending_inputs()
        assert out == {"x": 1} and s.pending_inputs == {}

    def test_pop_pending_specs_and_outputs(self):
        s = MCPState()
        s.pending_specs = [{"name": "x", "type": "Text"}]
        s.pending_outputs["o"] = 5
        assert s.pop_pending_specs() == [{"name": "x", "type": "Text"}]
        assert s.pending_specs is None
        assert s.pop_pending_outputs() == {"o": 5}


# --- seeding --------------------------------------------------------------- #

class TestSeed:
    def test_input_mirror_seeded_from_defaults(self):
        from fast_dash.mcp import _seed_input_mirror

        def greet(name: str = "world", count: int = 3) -> str:
            return name * count
        app = FastDash(callback_fn=greet, mcp_server=True)
        _seed_input_mirror(app)
        assert app._mcp_state.inputs.get("name") == "world"
        assert app._mcp_state.inputs.get("count") == 3

    def test_dropdown_default_seeds_none_not_options(self):
        # #110: a str dropdown (list default) is options-as-default; its browser
        # value is None, so the mirror must seed None, not the options list.
        from fast_dash.mcp import _seed_input_mirror

        def pick(fruit: str = ["a", "b", "c"], tags: list = ["x"], n: int = 6) -> str:
            return str(fruit)
        app = FastDash(callback_fn=pick, mcp_server=True)
        _seed_input_mirror(app)
        assert app._mcp_state.inputs["fruit"] is None    # not ["a","b","c"]
        assert app._mcp_state.inputs["tags"] is None      # multiselect too
        assert app._mcp_state.inputs["n"] == 6            # scalar still seeded


# --- native mount + delegation --------------------------------------------- #

@requires_dash_mcp
class TestNativeMount:
    def test_mounts_and_lists_our_tools_plus_native(self):
        c = _client_for(_plain_app())
        tools = _tools(c)
        for t in ["set_input", "set_inputs", "invoke",
                  "get_invocation", "list_component_types"]:
            assert t in tools
        assert "get_dash_component" in tools  # native tool

    def test_internal_dash_callbacks_are_hidden(self):
        c = _client_for(_plain_app())
        tools = _tools(c)
        assert "process_input" not in tools
        assert "process_ack_outputs" not in tools

    def test_native_resources_present(self):
        c = _client_for(_plain_app())
        uris = _resources(c)
        assert "dash://layout" in uris
        assert "dash://components" in uris


# --- tools ----------------------------------------------------------------- #

@requires_dash_mcp
class TestTools:
    def test_set_input_updates_mirror_and_queue(self):
        app = _plain_app()
        c = _client_for(app)
        out = _call(c, "set_input", {"component_id": "n", "value": 9})
        assert out["ok"] is True
        assert app._mcp_state.inputs["n"] == 9
        assert app._mcp_state.pending_inputs == {"n": 9}

    def test_set_input_rejects_unknown_id(self):
        c = _client_for(_plain_app())
        out = _call(c, "set_input", {"component_id": "nope", "value": 1})
        assert out["ok"] is False
        assert "known_ids" in out

    def test_set_inputs_bulk(self):
        app = _plain_app()
        c = _client_for(app)
        out = _call(c, "set_inputs", {"inputs": {"n": 4, "color": "#fff"}})
        assert out["ok"] is True
        assert app._mcp_state.pending_inputs == {"n": 4, "color": "#fff"}

    def test_invoke_one_shot_runs_callback(self):
        app = _plain_app()
        c = _client_for(app)
        out = _call(c, "invoke", {"inputs": {"n": 4}})
        assert out["ok"] is True
        assert out["outputs"]  # produced an output summary
        assert app._mcp_state.inputs["n"] == 4

    def test_describe_app_typed_contract_and_readback(self):
        # #102: typed contract from the callback signature; #100: read back the
        # value an agent set (headless), which dash://components can't show.
        app = _plain_app()  # plot_bars(n: int = 6, color: str = "#1c7ed6")
        c = _client_for(app)
        _call(c, "set_input", {"component_id": "n", "value": 9})
        out = _call(c, "describe_app")
        by_id = {i["id"]: i for i in out["inputs"]}
        assert set(by_id) == {"n", "color"}            # contract names the params
        assert by_id["n"]["type"] == "integer"
        assert by_id["n"]["default"] == 6
        assert by_id["n"]["current_value"] == 9        # reflects set_input
        assert by_id["color"]["type"] == "string"
        assert by_id["color"]["current_value"] == "#1c7ed6"  # seeded default

    def test_dropdown_contract_consistent_and_invoke_parity(self):
        # #110: describe_app current_value is type-consistent (None, not a list),
        # and invoke() with defaults passes None (the browser's value), not the
        # options list — so a str param never silently receives a list.
        def pick(fruit: str = ["a", "b", "c"]) -> str:
            """Echo the type."""
            return type(fruit).__name__
        app = FastDash(callback_fn=pick, mcp_server=True)
        c = _client_for(app)
        fruit = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}["fruit"]
        assert fruit["type"] == "string"
        assert fruit["current_value"] is None           # not the options list
        assert fruit["options"] == ["a", "b", "c"]
        out = _call(c, "invoke")
        assert "NoneType" in json.dumps(out["outputs"])  # callback got None

    def test_depends_on_contract_no_repr_leak_and_resolved_options(self):
        # #116: a depends_on (cascading) input must report a clean contract — no
        # leaked "<...object at 0x...>" default — and the dependent dropdown's
        # options must resolve from the current parent value.
        from fast_dash import depends_on
        countries = {"USA": ["California", "Texas"], "India": ["Delhi", "Goa"]}

        def pick_state(
            country: str = list(countries),
            state: str = depends_on("country", lambda c: countries[c]),
        ) -> str:
            """Pick a state in a country."""
            return f"{state}, {country}"

        app = FastDash(callback_fn=pick_state, mcp_server=True)
        c = _client_for(app)

        st = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}["state"]
        # default is clean JSON (None), never an object repr string.
        assert st["default"] is None
        assert "object at 0x" not in json.dumps(st)
        assert st["options"] is None          # parent unset -> not yet discoverable

        # set the parent; the dependent dropdown's options now resolve.
        _call(c, "set_input", {"component_id": "country", "value": "India"})
        st = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}["state"]
        assert st["options"] == ["Delhi", "Goa"]

    def test_dict_default_surfaces_multiselect_keys(self):
        # #116 (note): a dict default renders a MultiSelect of keys; describe_app
        # must surface those keys as options (previously reported null). Options
        # derive from the signature default, so this holds regardless of how the
        # annotation is spelled.
        def shop(items: dict = {"apples": 1, "pears": 2, "figs": 3}) -> str:
            """Echo selection."""
            return str(items)
        app = FastDash(callback_fn=shop, mcp_server=True)
        c = _client_for(app)
        items = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}["items"]
        assert items["options"] == ["apples", "pears", "figs"]
        # and no raw object repr leaks into the default contract field.
        assert items["default"] is None
        # #119: now that future annotations no longer degrade inference, the dict
        # builds a real MultiSelect (no value), so current_value is a clean None.
        assert items["current_value"] is None

    def test_future_annotations_do_not_degrade_inference(self):
        # #119: this module uses `from __future__ import annotations`, so every
        # annotation below reaches component inference as a *string* ("dict",
        # "list", "Annotated[...]"). Inference must resolve them (get_type_hints)
        # rather than fall through to a Text box — so a dict stays a MultiSelect,
        # a list a Select, and Annotated[int, range] a bounded Slider. (This also
        # restores the #120 slider contract under future annotations.)
        def cfg(
            items: dict = {"a": 1, "b": 2},
            fruit: str = ["x", "y", "z"],
            level: Annotated[int, range(0, 10)] = 3,
            free: str = "hi",
        ) -> str:
            """Echo."""
            return "ok"

        app = FastDash(callback_fn=cfg, mcp_server=True)
        c = _client_for(app)
        by_id = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}

        assert by_id["items"]["options"] == ["a", "b"]        # dict -> MultiSelect keys
        assert by_id["items"]["current_value"] is None        # real widget, not a text box
        assert by_id["fruit"]["options"] == ["x", "y", "z"]   # list -> Select dropdown
        assert by_id["level"]["props"] == {"min": 0, "max": 10, "step": 1}  # Slider bounds
        assert "props" not in by_id["free"]                   # plain str stays free text
        assert by_id["free"]["options"] is None
        # the resolved Slider's bounds are enforced too.
        assert _call(c, "set_input", {"component_id": "level", "value": 99})["ok"] is False

    def test_slider_bounds_in_contract_and_range_validation(self):
        # #120: a static Slider must expose its min/max/step in the contract (so
        # an agent can discover the range), and set_input/invoke must reject
        # out-of-range values the UI slider can never produce (parity). The
        # callback lives in a plain module (tests/_slider_app.py) — a faithful
        # copy of the issue's plain-script repro. (Sliders defined inline here
        # also work now that #119 resolves future annotations; the inline test
        # above covers that path.)
        from tests._slider_app import slider_demo
        app = FastDash(callback_fn=slider_demo, mcp_server=True)
        c = _client_for(app)
        by_id = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}

        # bounded sliders expose props; the plain number box does not.
        assert by_id["via_annot"]["props"] == {"min": 0, "max": 100, "step": 1}
        assert by_id["via_range"]["props"] == {"min": 0, "max": 100, "step": 1}
        assert "props" not in by_id["plain_num"]          # genuinely unbounded

        # out-of-range rejected; in-range accepted; unbounded input stays free.
        hi = _call(c, "set_input", {"component_id": "via_annot", "value": 99999})
        assert hi["ok"] is False and "maximum" in hi["error"]
        lo = _call(c, "set_input", {"component_id": "via_annot", "value": -50})
        assert lo["ok"] is False and "minimum" in lo["error"]
        assert _call(c, "set_input", {"component_id": "via_annot", "value": 42})["ok"]
        assert _call(c, "set_input", {"component_id": "plain_num", "value": 99999})["ok"]

        # invoke stays atomic: an out-of-range value rejects without mutating.
        out = _call(c, "invoke", {"inputs": {"via_annot": 99999}})
        assert out["ok"] is False and out["errors"]["via_annot"]
        assert app._mcp_state.inputs["via_annot"] == 42   # unchanged from set_input

    def test_set_input_and_invoke_validate_against_options(self):
        # #116 (note): a value the UI Select can never produce must be rejected,
        # mirroring the unknown-id guard (human<->agent parity). Valid values and
        # inputs with no advertised options stay permissive.
        def order(flavor: str = ["vanilla", "choco"], note: str = "") -> str:
            """Place an order."""
            return f"{flavor}:{note}"
        app = FastDash(callback_fn=order, mcp_server=True)
        c = _client_for(app)

        bad = _call(c, "set_input", {"component_id": "flavor", "value": "strawberry"})
        assert bad["ok"] is False and "allowed options" in bad["error"]
        ok = _call(c, "set_input", {"component_id": "flavor", "value": "choco"})
        assert ok["ok"] is True
        # free-text input (no options) still accepts anything.
        assert _call(c, "set_input", {"component_id": "note", "value": "rush"})["ok"]

        # invoke is atomic: a bad value rejects without mutating the mirror.
        out = _call(c, "invoke", {"inputs": {"flavor": "mango"}})
        assert out["ok"] is False and out["errors"]["flavor"]
        assert app._mcp_state.inputs["flavor"] == "choco"   # unchanged

    def test_enum_defaults_are_type_consistent(self):
        # #126: a plain Enum default was reported as null, and an IntEnum's
        # default/options were ints while current_value was a string. Every field
        # should be str(member.value) — the value the UI Select actually emits.
        def order(flavor: Flavor = Flavor.CHOCO, qty: Qty = Qty.TWO) -> str:
            """Place an order."""
            return f"{qty} {flavor}"
        app = FastDash(callback_fn=order, mcp_server=True)
        c = _client_for(app)
        by_id = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}

        # plain Enum: default is the member's value (was null).
        assert by_id["flavor"]["default"] == "choco"
        assert by_id["flavor"]["options"] == ["vanilla", "choco"]
        assert by_id["flavor"]["current_value"] == "choco"

        # IntEnum: default / options / current_value are type-consistent strings,
        # matching the Select (was default 2 / options [1, 2] vs current "2").
        q = by_id["qty"]
        assert q["default"] == "2"
        assert q["options"] == ["1", "2"]
        assert q["current_value"] == "2"

    def test_optional_annotation_reports_wrapped_type(self):
        # #132: an Optional[T] parameter reported type "string" because the raw
        # Union wrapper isn't in the type map. The wrapper must be unwrapped to
        # its single non-None member so the contract reports the type the input
        # actually accepts (integer/number/boolean), not a blanket string.
        def f(
            count: Optional[int] = 3,
            ratio: Optional[float] = None,
            flag: Optional[bool] = True,
            name: Optional[str] = "x",
        ) -> str:
            """Echo."""
            return "ok"

        app = FastDash(callback_fn=f, mcp_server=True)
        c = _client_for(app)
        by_id = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}
        assert by_id["count"]["type"] == "integer"   # was "string" pre-fix
        assert by_id["ratio"]["type"] == "number"
        assert by_id["flag"]["type"] == "boolean"
        assert by_id["name"]["type"] == "string"
        # a None default still surfaces as null (nothing to seed).
        assert by_id["ratio"]["default"] is None
        assert by_id["count"]["default"] == 3

    def test_datetime_default_surfaces_iso_string(self):
        # #134: a Date/Timestamp input built from a datetime.date / datetime
        # default reported default null (the scalar branch didn't match a date
        # object). It must surface the ISO string the DatePicker emits, keeping
        # the time component for a datetime.
        def sched(
            day: datetime.date = datetime.date(2021, 6, 15),
            at: datetime.datetime = datetime.datetime(2021, 6, 15, 10, 30),
        ) -> str:
            """Echo."""
            return "ok"

        app = FastDash(callback_fn=sched, mcp_server=True)
        c = _client_for(app)
        by_id = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}
        assert by_id["day"]["default"] == "2021-06-15"          # was null pre-fix
        assert by_id["at"]["default"] == "2021-06-15T10:30:00"  # keeps the time
        # dates travel as JSON strings (no native JSON date type).
        assert by_id["day"]["type"] == "string"

    def test_describe_app_reflects_dynamic_form(self):
        # #106: after set_form, describe_app must report the agent-built form's
        # contract (id/type/props), not just the value mirror.
        app = _dynamic_app()
        c = _client_for(app)
        _call(c, "set_form", {"specs": [
            {"name": "communication", "type": "Slider", "props": {"min": 0, "max": 10}},
            {"name": "technical", "type": "Slider", "props": {"min": 0, "max": 10}},
        ]})
        by_id = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}
        assert set(by_id) == {"communication", "technical"}   # both discoverable
        # #131: type is a JSON type (as on a static app), the component name is
        # in tag — so a headless agent reads ``type`` the same way everywhere.
        assert by_id["communication"]["tag"] == "Slider"
        assert by_id["communication"]["type"] == "number"
        assert by_id["communication"]["props"]["max"] == 10   # bounds exposed
        # set one field — both still listed; current_value updated for the set one.
        _call(c, "set_inputs", {"inputs": {"communication": 5}})
        by_id2 = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}
        assert set(by_id2) == {"communication", "technical"}
        assert by_id2["communication"]["current_value"] == 5

    def test_invoke_atomic_rejection(self):
        app = _plain_app()
        c = _client_for(app)
        out = _call(c, "invoke", {"inputs": {"n": 2, "bogus": 1}})
        assert out["ok"] is False
        assert "bogus" not in app._mcp_state.inputs
        assert app._mcp_state.pending_inputs == {}

    def test_get_invocation_roundtrip(self):
        app = _plain_app()
        c = _client_for(app)
        _call(c, "invoke", {"inputs": {"n": 5}})
        out = _call(c, "get_invocation", {"index": 0})
        assert out["ok"] is True
        assert "kwargs_summary" in out

    def test_list_component_types(self):
        c = _client_for(_plain_app())
        out = _call(c, "list_component_types")
        assert "Slider" in out["types"]

    def test_set_form_on_dynamic(self):
        app = _dynamic_app()
        c = _client_for(app)
        out = _call(c, "set_form",
                    {"specs": [{"name": "skill", "type": "Slider",
                                "props": {"min": 0, "max": 10}}]})
        assert out["ok"] is True and out["count"] == 1
        assert app._mcp_state.pending_specs is not None

    def test_set_form_rejected_on_plain_fastdash(self):
        # Single app in the process (registry cleared) -> set_form closes over
        # the plain FastDash and rejects.
        c = _client_for(_plain_app())
        out = _call(c, "set_form", {"specs": []})
        assert out["ok"] is False
        assert "DynamicDash" in out["error"]

    def test_set_form_validates_specs(self):
        c = _client_for(_dynamic_app())
        out = _call(c, "set_form", {"specs": [{"name": "x", "type": "NotReal"}]})
        assert out["ok"] is False
        assert "Unknown component type" in out["error"]

    def test_describe_app_reports_the_output_contract(self):
        # #152: describe_app reported inputs only, so the one way for a headless
        # agent to learn what an app returns was to *call* it — discovery by side
        # effect. Outputs are now part of the contract.
        def report(n: int = 3) -> Tuple[go.Figure, str]:
            """Chart n and summarize it."""
            return go.Figure(go.Bar(x=[n], y=[n])), f"{n} bars"

        app = FastDash(callback_fn=report, mcp_server=True,
                       output_labels=["Chart", "Summary"])
        c = _client_for(app)

        outs = _call(c, "describe_app")["outputs"]
        assert [o["tag"] for o in outs] == ["Graph", "Text"]
        assert [o["label"] for o in outs] == ["Chart", "Summary"]
        assert [o["type"] for o in outs] == ["object", "string"]
        # Nothing has run yet — no values claimed.
        assert all("current_value" not in o for o in outs)

        run = _call(c, "invoke", {"inputs": {"n": 4}})
        assert run["ok"] is True
        after = _call(c, "describe_app")["outputs"]
        assert after[1]["current_value"] == "4 bars"   # live value, still typed

    def test_dynamicdash_output_contract_is_not_empty(self):
        # #160: the #152 output contract read the public `outputs_with_ids`, but
        # DynamicDash stores its prepared outputs under `_outputs_with_ids`, so
        # describe_app reported `outputs: []` for every DynamicDash — pushing an
        # agent right back into discovering outputs by running the app. The
        # contract must match the ids invoke() actually produces.
        app = _dynamic_app()
        c = _client_for(app)

        outs = _call(c, "describe_app")["outputs"]
        assert [(o["id"], o["tag"]) for o in outs] == [
            ("dyn-output-0", "Graph"), ("dyn-output-1", "Markdown")]

        _call(c, "set_form", {"specs": [{"name": "x", "type": "Slider",
                                         "props": {"min": 0, "max": 10}}]})
        _call(c, "set_inputs", {"inputs": {"x": 5}})
        run = _call(c, "invoke", {"inputs": {}})
        # The contract predicted exactly the ids a run produces — no need to run
        # to find out.
        assert set(run["outputs"]) == {o["id"] for o in outs}

    def test_str_hint_widgets_report_the_widget_they_became(self):
        # #147: a colour picker, a textarea and a text box are three different
        # widgets, but all three reported tag "Text" (the `str` hint), so a
        # headless agent reading describe_app could not tell them apart — it had
        # no way to know `color` wants a hex string the UI can actually render.
        def style(color: str = "#1c7ed6",
                  bio: str = "line one\nline two",
                  name: str = "kedar") -> str:
            """Style a profile."""
            return f"{color}{bio}{name}"

        c = _client_for(FastDash(callback_fn=style, mcp_server=True))
        by_id = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}
        assert by_id["color"]["tag"] == "ColorInput"
        assert by_id["bio"]["tag"] == "TextArea"
        assert by_id["name"]["tag"] == "Text"

    def test_every_static_input_tag_is_a_real_widget_type(self):
        # #158: #147 named the widget for the ColorInput/TextArea/Text branches
        # but left the rest reporting the *hint* name. A str-with-list-default
        # renders a Select yet reported "Text" (== a plain text box, the exact
        # #147 failure mode), and int/bool/date/Literal reported internal names
        # ("Numeric"/"Boolean"/"Date"/"Literal") absent from
        # list_component_types(). The invariant: every static input's tag names a
        # real widget an agent could reproduce with set_form.
        # Hints must use module-level names (`datetime`, `Literal`) so
        # get_type_hints resolves them under this file's future annotations —
        # a function-local import would degrade to a text box (#119).
        def demo(plain: str = "hi",
                 choice: str = ["a", "b", "c"],          # -> Select
                 lit: Literal["x", "y"] = "x",           # -> Select
                 n: int = 5,                             # -> NumberInput
                 rng: Annotated[int, range(0, 10)] = 5,  # -> Slider
                 flag: bool = True,                      # -> Switch
                 day: datetime.date = datetime.date(2024, 1, 1),  # -> DateInput
                 tags: list = ["a", "b"]) -> str:        # -> MultiSelect
            """Every widget kind."""
            return "x"

        c = _client_for(FastDash(callback_fn=demo, mcp_server=True))
        legal = set(_call(c, "list_component_types")["types"])
        by_id = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}

        # The headline: a fixed-choice dropdown is no longer indistinguishable
        # from a free-text box.
        assert by_id["choice"]["tag"] == "Select"
        assert by_id["plain"]["tag"] == "Text"
        assert by_id["choice"]["tag"] != by_id["plain"]["tag"]

        expected = {"plain": "Text", "choice": "Select", "lit": "Select",
                    "n": "NumberInput", "rng": "Slider", "flag": "Switch",
                    "day": "DateInput", "tags": "MultiSelect"}
        assert {k: by_id[k]["tag"] for k in expected} == expected
        # ...and every one is a type an agent could name in set_form.
        for i in by_id.values():
            assert i["tag"] in legal, f"{i['id']} tag {i['tag']!r} not in {sorted(legal)}"

    def test_password_value_goes_in_but_never_comes_back(self):
        # #151: the browser masks a PasswordInput; the unauthenticated /mcp route
        # must not undo that by reading the credential back out in plain text.
        # (PasswordInput is imported at module level so get_type_hints can
        # resolve this annotation under the file's future annotations — #119.)
        def login(pwd: PasswordInput = "hunter2", user: str = "kedar") -> str:
            """Log in."""
            return f"{user}:{pwd}"

        app = FastDash(callback_fn=login, mcp_server=True)
        c = _client_for(app)

        by_id = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}
        assert by_id["pwd"]["secret"] is True
        assert by_id["pwd"]["default"] == "********"      # seeded default masked
        assert by_id["user"]["secret"] is False
        assert by_id["user"]["default"] == "kedar"        # non-secrets unchanged

        # The value is settable (an agent must be able to fill it) but the echo
        # is masked, and the mirror really did take the value.
        out = _call(c, "set_input", {"component_id": "pwd", "value": "s3cret"})
        assert out["ok"] is True and out["value"] == "********"
        assert app._mcp_state.inputs["pwd"] == "s3cret"

        cur = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}
        assert cur["pwd"]["current_value"] == "********"

        # ...and it does not leak through invoke's history either.
        run = _call(c, "invoke")
        assert run["ok"] is True
        hist = _call(c, "get_invocation", {"index": run["history_index"]})
        assert hist["kwargs_summary"]["pwd"] == "********"
        assert hist["kwargs_summary"]["user"] == "kedar"

    def test_wrong_type_rejected_so_bounds_cannot_be_bypassed(self):
        # #150: the bounds check only fires for numbers, so a *string* used to
        # sail straight past a Slider's min/max ("9999" is not an int, so nothing
        # compared it to the maximum) and reach the callback as a value no drag
        # of the slider could produce.
        from tests._slider_app import slider_demo

        app = FastDash(callback_fn=slider_demo, mcp_server=True)
        c = _client_for(app)

        bad = _call(c, "set_input", {"component_id": "via_annot", "value": "9999"})
        assert bad["ok"] is False and "expected an integer" in bad["error"]
        assert "via_annot" not in app._mcp_state.pending_inputs
        # ...including the unbounded number box, which has a type but no range.
        bad2 = _call(c, "set_input", {"component_id": "plain_num", "value": "lots"})
        assert bad2["ok"] is False and "expected an integer" in bad2["error"]
        # Numbers still pass.
        assert _call(c, "set_input", {"component_id": "via_annot", "value": 42})["ok"]

    def test_boolean_input_rejects_non_boolean(self):
        # #150: a Switch can only ever emit True/False.
        def flag(on: bool = False, note: str = "") -> str:
            """Toggle."""
            return f"{on}{note}"

        c = _client_for(FastDash(callback_fn=flag, mcp_server=True))
        bad = _call(c, "set_input", {"component_id": "on", "value": "yes"})
        assert bad["ok"] is False and "expected a boolean" in bad["error"]
        assert _call(c, "set_input", {"component_id": "on", "value": True})["ok"]
        # A free-text input stays permissive — nothing is advertised about it.
        assert _call(c, "set_input", {"component_id": "note", "value": "anything"})["ok"]

    def test_agent_built_form_is_validated_against_its_own_specs(self):
        # #144: DynamicDash has no static inputs, so every guard keyed off
        # _enumerate_inputs short-circuited and an agent-built form skipped ALL
        # validation — unknown ids, out-of-options and out-of-range values all
        # landed in the mirror. The specs the agent declared ARE the contract.
        app = _dynamic_app()
        c = _client_for(app)
        _call(c, "set_form", {"specs": [
            {"name": "skill", "type": "Slider", "props": {"min": 0, "max": 10}},
            {"name": "team", "type": "Select",
             "props": {"data": ["red", "blue"]}},
        ]})

        unknown = _call(c, "set_input", {"component_id": "nope", "value": 1})
        assert unknown["ok"] is False and unknown["known_ids"] == ["skill", "team"]

        hi = _call(c, "set_input", {"component_id": "skill", "value": 99})
        assert hi["ok"] is False and "maximum" in hi["error"]

        off = _call(c, "set_input", {"component_id": "team", "value": "green"})
        assert off["ok"] is False and "allowed options" in off["error"]

        # Nothing invalid reached the mirror; valid values still do.
        assert app._mcp_state.inputs.get("skill") is None
        assert _call(c, "set_input", {"component_id": "skill", "value": 7})["ok"]
        assert _call(c, "set_input", {"component_id": "team", "value": "red"})["ok"]
        assert app._mcp_state.inputs["skill"] == 7

    def test_agent_built_select_accepts_label_value_options(self):
        # A DynamicDash Select may declare data as [{label, value}, ...]; only the
        # value half is ever emitted, so that is what membership checks.
        app = _dynamic_app()
        c = _client_for(app)
        _call(c, "set_form", {"specs": [
            {"name": "team", "type": "Select", "props": {
                "data": [{"label": "Red team", "value": "red"},
                         {"label": "Blue team", "value": "blue"}]}},
        ]})
        assert _call(c, "set_input", {"component_id": "team", "value": "red"})["ok"]
        bad = _call(c, "set_input", {"component_id": "team", "value": "Red team"})
        assert bad["ok"] is False and "allowed options" in bad["error"]


class TestSecretsNeverLeave:
    """#151, hardened: the secret must not appear ANYWHERE in a payload.

    Asserting that `current_value` is masked is not the same as asserting the
    credential didn't ride out in a sibling field — `props`, the plain-mirror
    tail of describe_app, an error string. These tests search the serialized
    payload for the string itself, which is the only assertion that can't be
    satisfied by masking the one field the author happened to think of.
    """

    SECRET = "sk-live-DO-NOT-LEAK"

    def _assert_clean(self, payload):
        assert self.SECRET not in json.dumps(payload, default=str)

    def test_app_authored_dynamic_password_is_masked(self):
        # An `initial_specs` form is authored by the app, not the agent — so its
        # PasswordInput was invisible to a secret list built from set_form specs.
        app = _dynamic_app(placeholder=None, initial_specs=[
            {"name": "api_key", "type": "PasswordInput"},
            {"name": "q", "type": "Text"},
        ])
        c = _client_for(app)
        assert _call(c, "set_input", {"component_id": "api_key", "value": self.SECRET})["ok"]

        self._assert_clean(_call(c, "describe_app"))
        run = _call(c, "invoke")
        self._assert_clean(run)
        self._assert_clean(_call(c, "get_invocation", {"index": run["history_index"]}))
        # ...but the callback really did receive it.
        assert app._mcp_state.inputs["api_key"] == self.SECRET

    def test_secret_in_spec_props_is_masked(self):
        # A spec may carry its value in props; props were echoed verbatim, so the
        # credential rode out beside the very entry stamped "secret": true.
        app = _dynamic_app()
        c = _client_for(app)
        _call(c, "set_form", {"specs": [
            {"name": "api_key", "type": "PasswordInput",
             "props": {"value": self.SECRET}},
        ]})
        desc = _call(c, "describe_app")
        entry = desc["inputs"][0]
        assert entry["secret"] is True and entry["current_value"] == "********"
        self._assert_clean(desc)

    def test_secret_survives_a_form_swap(self):
        # Replacing the form must not strand the old password's value in the
        # mirror, where describe_app's plain tail would print it in the clear.
        app = _dynamic_app()
        c = _client_for(app)
        _call(c, "set_form", {"specs": [
            {"name": "api_key", "type": "PasswordInput"},
            {"name": "q", "type": "Text"},
        ]})
        _call(c, "set_input", {"component_id": "api_key", "value": self.SECRET})

        _call(c, "set_form", {"specs": [{"name": "q", "type": "Text"}]})
        self._assert_clean(_call(c, "describe_app"))
        # The field is gone from the form, so its value is gone from the mirror —
        # invoke must not keep passing it to the callback either.
        assert "api_key" not in app._mcp_state.inputs


class TestDynamicFormContract:
    """#144, hardened: the contract follows the form on screen, whoever built it."""

    def test_app_authored_form_is_validated(self):
        # initial_specs never touched current_specs, so an app-authored form had
        # no contract at all: unknown ids, out-of-range and wrong-typed values
        # were all accepted in silence.
        app = _dynamic_app(placeholder=None, initial_specs=[
            {"name": "n", "type": "Slider", "props": {"min": 1, "max": 10}},
        ])
        c = _client_for(app)

        assert _call(c, "set_input", {"component_id": "n", "value": 9999})["ok"] is False
        assert _call(c, "set_input", {"component_id": "n", "value": "lots"})["ok"] is False
        assert _call(c, "set_input", {"component_id": "bogus", "value": 1})["ok"] is False
        assert _call(c, "set_input", {"component_id": "n", "value": 4})["ok"] is True

    def test_parent_cascade_form_replaces_the_contract(self):
        # A parent_control app's form is built server-side by the resolver. One
        # set_form used to pin the contract forever: describe_app kept reporting
        # the agent's form while the browser showed the cascade's, and set_input
        # rejected the ids that were actually on screen.
        app = _dynamic_app(
            placeholder=None,
            parent_control={"name": "dataset", "type": "Select",
                            "props": {"data": ["sales", "traffic"]}},
            spec_resolver=lambda v: [{"name": f"{v}_col", "type": "Text"}],
        )
        c = _client_for(app)

        # The parent control is itself part of the contract — the UI passes it to
        # the callback, so an agent must be able to discover and drive it.
        by_id = {i["id"]: i for i in _call(c, "describe_app")["inputs"]}
        assert by_id["dataset"]["options"] == ["sales", "traffic"]
        assert _call(c, "set_input", {"component_id": "dataset", "value": "nope"})["ok"] is False

        _call(c, "set_form", {"specs": [{"name": "agent_field", "type": "Text"}]})
        # The human now picks a dataset; the cascade rebuilds the form (this is
        # what the reshape_from_parent callback does on every parent change).
        app._sync_form_contract(app.spec_resolver("sales"), "sales")
        ids = {i["id"] for i in _call(c, "describe_app")["inputs"]}
        assert ids == {"dataset", "sales_col"}      # not the stale agent_field
        assert _call(c, "set_input", {"component_id": "sales_col", "value": "x"})["ok"]


class TestMcpExposureWarning:
    """#149: warn about the host we actually bind, not the defunct mcp_host."""

    def test_warns_when_bound_to_all_interfaces(self, monkeypatch):
        app = _plain_app()
        monkeypatch.setattr(app.app, "run", lambda **kw: None)
        app.run_kwargs["host"] = "0.0.0.0"
        with pytest.warns(UserWarning, match="no authentication"):
            app.run()

    def test_silent_on_loopback(self, monkeypatch):
        app = _plain_app()
        monkeypatch.setattr(app.app, "run", lambda **kw: None)
        assert not _exposure_warnings(app.run)

    def test_no_warning_when_no_mcp_route_is_mounted(self, monkeypatch):
        # Multi-function mode ignores mcp_server=True, so there is no
        # unauthenticated endpoint to warn about — warning anyway is the kind of
        # false alarm that teaches people to ignore the real one.
        def f(n: int = 1) -> str:
            """f."""
            return str(n)

        def g(n: int = 2) -> str:
            """g."""
            return str(n)

        app = FastDash(callback_fn=[f, g], mcp_server=True,
                       run_kwargs={"host": "0.0.0.0"})
        monkeypatch.setattr(app.app, "run", lambda **kw: None)
        assert not _exposure_warnings(app.run)

    def test_mcp_host_alone_does_not_warn(self):
        # The legacy kwarg binds nothing now that MCP shares the app's port, so
        # warning on it was a false alarm — and worse, its silence on a
        # 0.0.0.0 run_kwargs host was a false all-clear.
        def f(n: int = 1) -> str:
            """f."""
            return str(n)

        warned = _exposure_warnings(
            lambda: FastDash(callback_fn=f, mcp_server=True, mcp_host="0.0.0.0")
        )
        assert not warned


# --- chat-mode MCP contract (RFC #133 Phase 3) ----------------------------- #

def _chat_app(**kw):
    def bot(query: str, tone: str = "neutral"):
        """A tiny streaming assistant."""
        yield {"type": "tool_start", "name": "lookup", "id": "1", "args": {"q": query}}
        yield {"type": "tool_end", "name": "lookup", "id": "1", "result": "ok"}
        yield f"[{tone}] you said: {query}"
    return FastDash(callback_fn=bot, chat=True, mcp_server=True, **kw)


class TestChatMcp:
    """A chat app exposes describe_app (composer contract) + headless invoke."""

    def test_chat_registers_only_chat_tools(self):
        c = _client_for(_chat_app())
        tools = _tools(c)
        assert "describe_app" in tools and "invoke" in tools
        # The input-mirror tools are for static apps, not chat.
        assert "set_input" not in tools and "set_form" not in tools

    def test_describe_app_reports_composer_and_settings(self):
        c = _client_for(_chat_app())
        desc = _call(c, "describe_app")
        assert desc["mode"] == "chat"
        assert desc["composer"]["query"]["type"] == "string"
        assert desc["composer"]["query"]["required"] is True
        names = {s["name"]: s for s in desc["settings"]}
        assert "tone" in names
        assert names["tone"]["type"] == "string"      # type-consistent contract

    def test_invoke_runs_a_turn_and_returns_json_safe_frames(self):
        c = _client_for(_chat_app())
        out = _call(c, "invoke", {"query": "hello", "settings": {"tone": "excited"}})
        assert out["ok"] is True
        assert out["content"] == "[excited] you said: hello"
        types = [f["type"] for f in out["frames"]]
        assert types == ["tool_start", "tool_end", "content", "complete"]
        # Frames must be JSON round-trippable (nothing non-serializable leaks).
        json.dumps(out["frames"])

    def test_invoke_advances_history_across_calls(self):
        c = _client_for(_chat_app())
        _call(c, "invoke", {"query": "first"})
        out = _call(c, "invoke", {"query": "second"})
        assert out["ok"] is True and "second" in out["content"]

    def test_invoke_rejects_empty_query_and_unknown_setting(self):
        c = _client_for(_chat_app())
        assert _call(c, "invoke", {"query": "   "})["ok"] is False
        bad = _call(c, "invoke", {"query": "x", "settings": {"nope": 1}})
        assert bad["ok"] is False and "unknown setting" in bad["error"]

    def test_invoke_artifact_frame_is_wire_safe_placeholder(self):
        # An artifact (a Figure) must never cross the MCP boundary raw; it is a
        # JSON-safe placeholder, like on the socket wire.
        def bot(query: str):
            yield {"type": "artifact", "content": go.Figure(go.Bar(x=[1], y=[1]))}
            yield "done"
        c = _client_for(FastDash(callback_fn=bot, chat=True, mcp_server=True))
        out = _call(c, "invoke", {"query": "plot"})
        art = [f for f in out["frames"] if f["type"] == "artifact"]
        assert art and art[0].get("pending") is True
        json.dumps(out["frames"])

    @requires_langstage
    def test_invoke_drives_a_langstage_agent(self):
        app = FastDash(callback_fn="langstage_core.demo.stub:graph",
                       chat=True, mcp_server=True)
        c = _client_for(app)
        desc = _call(c, "describe_app")
        assert desc["mode"] == "chat" and desc["settings"] == []
        out = _call(c, "invoke", {"query": "hello there"})
        assert out["ok"] is True and "hello there" in out["content"]


class TestSidecarMcp:
    """A normal app can carry BOTH an MCP surface and a chat= agent sidecar."""

    def test_mcp_and_chat_agent_coexist_and_mirror_syncs(self):
        from unittest import mock

        def dashboard(revenue: int = 100) -> str:
            """A dashboard."""
            return f"rev {revenue}"

        def agent(query, ctx):
            yield {"type": "set_input", "name": "revenue", "value": 500}
            yield {"type": "run_app"}

        app = FastDash(callback_fn=dashboard, chat=agent, mcp_server=True)
        assert app.has_chat_sidecar and app.mcp_server_enabled
        c = _client_for(app)
        # Both surfaces build; describe_app still reports the app contract.
        assert "inputs" in _call(c, "describe_app")
        # After the sidecar drives, describe_app reflects it (A2 mirror sync).
        with mock.patch("flask_socketio.emit"):
            app._run_chat_turn("go", "s1", "sock", (), app_inputs={"revenue": 100})
        rev = [i for i in _call(c, "describe_app")["inputs"] if i["id"] == "revenue"]
        assert rev and rev[0]["current_value"] == 500
