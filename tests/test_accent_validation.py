#!/usr/bin/env python
"""An invalid ``accent`` must degrade gracefully, never brick the app (#234).

``accent`` lands in Mantine's ``theme.primaryColor`` unvalidated. Mantine v7
(dmc 2.8.0) *throws* on a key that is not in ``theme.colors`` and unmounts the
whole tree — the user sees a blank page with HTTP 200 and no server-side error.
An invalid accent must instead warn and fall back to the documented default.
"""

import warnings

import pytest

from fast_dash import FastDash


def _echo(name: str = "world") -> str:
    return f"Hi {name}"


def _primary_color(app):
    return app.app.layout.theme["primaryColor"]


def test_valid_mantine_accent_passes_through():
    app = FastDash(callback_fn=_echo, accent="indigo")
    assert _primary_color(app) == "indigo"


def test_default_accent_is_blue_without_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app = FastDash(callback_fn=_echo)
    leaked = [w for w in caught if "accent" in str(w.message)]
    assert not leaked, f"unexpected accent warning: {leaked}"
    assert _primary_color(app) == "blue"


def test_typo_accent_warns_and_falls_back_to_blue():
    with pytest.warns(UserWarning, match="indgo"):
        app = FastDash(callback_fn=_echo, accent="indgo")
    assert _primary_color(app) == "blue"


def test_hex_accent_warns_and_falls_back_to_blue():
    with pytest.warns(UserWarning, match="#1c7ed6"):
        app = FastDash(callback_fn=_echo, accent="#1c7ed6")
    assert _primary_color(app) == "blue"


def test_css_color_name_warns_and_falls_back_to_blue():
    # "purple" is a real CSS colour but not a Mantine palette key.
    with pytest.warns(UserWarning, match="purple"):
        app = FastDash(callback_fn=_echo, accent="purple")
    assert _primary_color(app) == "blue"


def test_non_string_accent_warns_and_falls_back_to_blue():
    with pytest.warns(UserWarning, match="accent"):
        app = FastDash(callback_fn=_echo, accent=123)
    assert _primary_color(app) == "blue"


def test_accent_case_and_whitespace_are_normalised():
    app = FastDash(callback_fn=_echo, accent="  Indigo ")
    assert _primary_color(app) == "indigo"


def test_warning_names_a_valid_choice():
    # The message is only actionable if it tells the user what to pass.
    with pytest.warns(UserWarning, match="indigo"):
        FastDash(callback_fn=_echo, accent="indgo")
