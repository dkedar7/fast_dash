#!/usr/bin/env python
"""Callbacks receive the type their hint promises (#181, #182), and update_live
apps render on every page load (#183)."""
from __future__ import annotations

import datetime
import enum
import json

import pytest

from fast_dash import FastDash
from fast_dash.utils import _transform_inputs


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


class Qty(enum.IntEnum):
    ONE = 1
    TWO = 2


def _app(fn):
    return FastDash(callback_fn=fn)


def _coerce(app, index, value, tag):
    return _transform_inputs([value], [tag], [app.inputs_with_ids[index]])[0]


# --- #181: Enum ------------------------------------------------------------ #

def test_enum_option_string_becomes_the_member():
    def fn(c: Color = Color.RED) -> str:
        """Echo."""
        return str(c)

    got = _coerce(_app(fn), 0, "blue", "Enum")
    assert got is Color.BLUE          # `is` comparisons in user code now match
    assert got.value == "blue"        # .value/.name no longer AttributeError
    assert got.name == "BLUE"


def test_enum_default_also_arrives_as_the_member():
    # Even with nothing set, the stored default is the option *string*, so the
    # untouched path needs coercing too.
    def fn(c: Color = Color.RED) -> str:
        """Echo."""
        return str(c)

    assert _coerce(_app(fn), 0, "red", "Enum") is Color.RED


def test_int_enum_maps_through_its_stringified_value():
    def fn(q: Qty = Qty.ONE) -> str:
        """Echo."""
        return str(q)

    assert _coerce(_app(fn), 0, "2", "Enum") is Qty.TWO


def test_enum_member_passes_through_untouched():
    def fn(c: Color = Color.RED) -> str:
        """Echo."""
        return str(c)

    assert _coerce(_app(fn), 0, Color.BLUE, "Enum") is Color.BLUE


def test_unknown_enum_option_is_left_alone():
    def fn(c: Color = Color.RED) -> str:
        """Echo."""
        return str(c)

    assert _coerce(_app(fn), 0, "chartreuse", "Enum") == "chartreuse"


# --- #182: date / datetime -------------------------------------------------- #

def test_iso_string_becomes_a_date():
    def fn(d: datetime.date = datetime.date(2024, 1, 15)) -> str:
        """Echo."""
        return str(d)

    got = _coerce(_app(fn), 0, "2025-12-25", "Date")
    assert got == datetime.date(2025, 12, 25)
    assert got.isoformat() == "2025-12-25"     # used to AttributeError
    assert got.year == 2025


def test_iso_string_becomes_a_datetime():
    def fn(t: datetime.datetime = datetime.datetime(2024, 1, 15, 10, 30)) -> str:
        """Echo."""
        return str(t)

    got = _coerce(_app(fn), 0, "2024-01-15T10:30:00", "Timestamp")
    assert got == datetime.datetime(2024, 1, 15, 10, 30)


def test_date_picker_returning_a_full_timestamp_still_yields_a_date():
    def fn(d: datetime.date = datetime.date(2024, 1, 15)) -> str:
        """Echo."""
        return str(d)

    assert _coerce(_app(fn), 0, "2025-12-25T00:00:00", "Date") == datetime.date(2025, 12, 25)


def test_real_date_passes_through_untouched():
    # The untouched-default path already handed over a real date; keep it.
    def fn(d: datetime.date = datetime.date(2024, 1, 15)) -> str:
        """Echo."""
        return str(d)

    value = datetime.date(2024, 1, 15)
    assert _coerce(_app(fn), 0, value, "Date") is value


@pytest.mark.parametrize("junk", ["", "not-a-date", "2025-13-45"])
def test_unparseable_date_is_not_mangled(junk):
    def fn(d: datetime.date = datetime.date(2024, 1, 15)) -> str:
        """Echo."""
        return str(d)

    assert _coerce(_app(fn), 0, junk, "Date") == junk


def test_none_stays_none():
    def fn(d: datetime.date = datetime.date(2024, 1, 15)) -> str:
        """Echo."""
        return str(d)

    assert _coerce(_app(fn), 0, None, "Date") is None


# --- #183: update_live renders on every page load --------------------------- #

def _page_load(app, client, proc_key, proc, outs):
    payload = {
        "output": proc_key,
        "outputs": [{"id": o.component_id, "property": o.component_property}
                    for o in outs],
        "inputs": [{"id": i["id"], "property": i["property"], "value": None}
                   for i in proc["inputs"]],
        "state": [{"id": s["id"], "property": s["property"], "value": None}
                  for s in proc.get("state", [])],
        "changedPropIds": [],
    }
    r = client.post("/_dash-update-component", data=json.dumps(payload),
                    headers={"Content-Type": "application/json"})
    return (r.get_json() or {}).get("response", {})


def test_update_live_app_renders_on_every_page_load():
    # Regression: _initial_render_done was instance state, so the page-load
    # render happened once per worker *process*. The first visitor got a
    # dashboard and every later visitor (or reload) got a silent blank one.
    calls = []

    def dashboard() -> str:
        """Parameterless dashboard -- update_live is auto-enabled."""
        calls.append(1)
        return f"render {len(calls)}"

    app = _app(dashboard)
    assert app.update_live is True
    client = app.app.server.test_client()
    proc_key, proc = next(
        (k, cb) for k, cb in app.app.callback_map.items()
        if any(i.get("id") == "submit_inputs" for i in cb.get("inputs", []))
        and any(i.get("id") == "reset_inputs" for i in cb.get("inputs", []))
    )
    out = proc["output"]
    outs = out if isinstance(out, (list, tuple)) else [out]

    for expected in (1, 2, 3):
        response = _page_load(app, client, proc_key, proc, outs)
        assert response, f"page load {expected} returned no outputs (blank page)"
        rendered = " ".join(str(v) for v in response.values())
        assert f"render {expected}" in rendered, rendered
