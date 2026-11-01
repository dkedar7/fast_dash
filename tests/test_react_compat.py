"""The DMC / served-React mismatch that renders a blank page (#318, #320)."""

import sys
import warnings

import pytest
from dash import _dash_renderer

from fast_dash import FastDash
from fast_dash import cli, utils
from fast_dash.dynamic import DynamicDash


def _echo(text: str = "hi") -> str:
    return text.upper()


def _serve(monkeypatch, react):
    deps = [{"prod": [f"deps/react@{react}.min.js", f"deps/react-dom@{react}.min.js"]}]
    monkeypatch.setattr(_dash_renderer, "_js_dist_dependencies", deps)


@pytest.fixture
def dmc3(monkeypatch):
    monkeypatch.setattr(utils.dmc, "__version__", "3.0.0")
    _serve(monkeypatch, "18.3.1")


def _react_warnings(build):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        build()
    return [x for x in w if "needs React" in str(x.message)]


def test_dmc3_on_react18_is_named(dmc3):
    msg = utils.react_mismatch()
    assert "dash-mantine-components 3.0.0 needs React 19" in msg
    assert "serves React 18.3.1" in msg
    assert "dash-mantine-components<3" in msg
    assert msg.isascii()


def test_fix_offers_react19_only_when_dash_serves_it(dmc3, monkeypatch):
    monkeypatch.setattr(_dash_renderer, "_available_react_versions", {"18.3.1", "19.2.4"})
    assert "_set_react_version('19.2.4')" in utils.react_mismatch()
    monkeypatch.setattr(_dash_renderer, "_available_react_versions", {"18.3.1", "18.2.0"})
    msg = utils.react_mismatch()
    assert "_set_react_version" not in msg
    assert "upgrade to a Dash that can serve React 19" in msg


@pytest.mark.parametrize("dmc_version, react", [
    ("2.8.1", "18.3.1"),       # the supported pair
    ("3.0.0", "19.2.4"),       # DMC 3 with React 19 opted in
    ("1.3.0", "18.2.0"),
])
def test_compatible_pairs_pass(monkeypatch, dmc_version, react):
    monkeypatch.setattr(utils.dmc, "__version__", dmc_version)
    _serve(monkeypatch, react)
    assert utils.react_mismatch() is None


def test_unreadable_versions_stay_quiet(monkeypatch):
    monkeypatch.setattr(utils.dmc, "__version__", "3.0.0")
    monkeypatch.setattr(_dash_renderer, "_js_dist_dependencies", [])
    assert utils.react_mismatch() is None


def test_building_an_app_warns_at_the_callers_line(dmc3):
    for build in (lambda: FastDash(_echo), lambda: DynamicDash(_echo)):
        found = _react_warnings(build)
        assert len(found) == 1
        assert found[0].filename == __file__


def test_supported_install_builds_without_warning():
    assert _react_warnings(lambda: FastDash(_echo)) == []


def test_doctor_reports_the_mismatch(dmc3, capsys):
    assert cli.doctor() == 1
    out = capsys.readouterr().out
    assert "React (served by Dash)       18.3.1" in out
    assert "Problem: dash-mantine-components 3.0.0 needs React 19" in out


def test_doctor_from_the_cli(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["fastdash", "doctor"])
    assert cli.main() == 0
    assert "No known version conflicts." in capsys.readouterr().out


def test_bare_cli_prints_help_instead_of_crashing(monkeypatch, capsys):
    # The port prompt used to run for every command: no command -> AttributeError.
    monkeypatch.setattr(sys, "argv", ["fastdash"])
    assert cli.main() == 1
    assert "doctor" in capsys.readouterr().out
