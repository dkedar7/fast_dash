"""Regression tests for run()/config crashes (0.7.0 batch 4).

#205 run() takes debug / port / host / Dash run() kwargs.
#203 run_kwargs["port"] is not clobbered by the 8080 default.
#213 the sidebar toggle works on a steps= app (no `inputs` attribute).
#227 the sidebar toggle works without a Flask request (ASGI backend).
#234 an unknown accent= falls back to blue instead of blanking the page.
"""
import json
import warnings

import pandas as pd
import pytest

from fast_dash import FastDash, from_step
from fast_dash.Components import _mantine_accent


def greet(name: str = "world") -> str:
    return f"Hi {name}"


def _run_kwargs(app, **run_args):
    seen = {}
    app.app.run = lambda **kw: seen.update(kw)
    app.run(**run_args)
    return seen


# --- #205 ------------------------------------------------------------------ #

def test_run_accepts_dash_run_kwargs():
    seen = _run_kwargs(FastDash(callback_fn=greet), debug=True, port=8099,
                       host="127.0.0.1", use_reloader=False)
    assert seen == {"port": 8099, "debug": True, "host": "127.0.0.1",
                    "use_reloader": False}


def test_run_port_override_updates_app_port():
    app = FastDash(callback_fn=greet)
    _run_kwargs(app, port=8123)
    assert app.port == 8123


# --- #203 ------------------------------------------------------------------ #

def test_run_kwargs_port_is_used():
    assert _run_kwargs(FastDash(callback_fn=greet, run_kwargs={"port": 8195}))["port"] == 8195


def test_default_port_is_still_8080():
    app = FastDash(callback_fn=greet)
    assert app.port == 8080 and _run_kwargs(app)["port"] == 8080


def test_conflicting_ports_warn_and_port_arg_wins():
    with pytest.warns(UserWarning, match="disagree"):
        app = FastDash(callback_fn=greet, port=9000, run_kwargs={"port": 9001})
    assert app.run_kwargs["port"] == 9000


# --- #213 / #227 ----------------------------------------------------------- #

def _toggle_sidebar(app):
    cb = app.app.callback_map["appshell.navbar"]["callback"]
    return getattr(cb, "__wrapped__", cb)


def _load(rows: int = 10) -> pd.DataFrame:
    return pd.DataFrame({"x": range(rows)})


def _summarise(data=from_step(_load), prefix: str = "Result:") -> str:
    return f"{prefix} {len(data)}"


def test_sidebar_toggle_on_steps_app():
    app = FastDash(steps=[_load, _summarise])
    # called outside any Flask request too -- the ASGI condition (#227)
    out = _toggle_sidebar(app)(True, None)
    assert out["collapsed"] == {"desktop": False, "mobile": False}
    assert _toggle_sidebar(app)(False, None)["collapsed"] == {"desktop": True, "mobile": True}


def test_sidebar_toggle_without_request_context():
    out = _toggle_sidebar(FastDash(callback_fn=greet))(True, 360)
    assert out == {"width": 360, "breakpoint": "sm",
                   "collapsed": {"desktop": False, "mobile": False}}


# --- #234 ------------------------------------------------------------------ #

@pytest.mark.parametrize("accent, expected", [
    ("indigo", "indigo"), (" Teal ", "teal"), (None, "blue"), ("", "blue"),
])
def test_valid_accents(accent, expected):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _mantine_accent(accent) == expected


@pytest.mark.parametrize("accent", ["indgo", "#1c7ed6", "purple"])
def test_unknown_accent_falls_back_to_blue(accent):
    with pytest.warns(UserWarning, match="not a Mantine color"):
        assert _mantine_accent(accent) == "blue"


def test_unknown_accent_app_uses_blue_theme():
    with pytest.warns(UserWarning, match="not a Mantine color"):
        app = FastDash(callback_fn=greet, accent="indgo")
    layout = app.app.layout() if callable(app.app.layout) else app.app.layout
    served = json.dumps(layout.to_plotly_json(), default=str)
    assert '"primaryColor": "blue"' in served
    assert "indgo" not in served
