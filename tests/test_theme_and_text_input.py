"""#281: an unknown theme= warns and uses the documented default.
#284: a str parameter with no default is a single-line text box, silently."""
import typing
import warnings

import pytest

from fast_dash import FastDash, dmc
from fast_dash.utils import _bootswatch_name, theme_mapper


def _f(name: str = "x") -> str:
    return name


@pytest.mark.parametrize("given, expected", [
    (None, "JOURNAL"), ("darkly", "DARKLY"), (" Cyborg ", "CYBORG"), ("JOURNAL", "JOURNAL"),
])
def test_known_themes_resolve_without_warning(given, expected):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _bootswatch_name(given, warn=True) == expected


@pytest.mark.parametrize("typo", ["DARKY", "solarized"])
def test_unknown_theme_warns_and_uses_journal(typo):
    with pytest.warns(UserWarning, match="not a Bootswatch theme"):
        app = FastDash(callback_fn=_f, theme=typo)
    assert app.theme == "JOURNAL"
    assert "journal" in theme_mapper(app.theme)


def test_padded_dark_theme_still_flips_dark_mode():
    app = FastDash(callback_fn=_f, theme=" darkly ")
    assert app.theme == "DARKLY" and "darkly" in theme_mapper(app.theme)


@pytest.mark.parametrize("hint_default", ["required", "optional_none"])
def test_str_without_default_is_single_line_without_warning(hint_default):
    if hint_default == "required":
        def f(name: str) -> str:
            return name
    else:
        def f(name: typing.Optional[str] = None) -> str:
            return str(name)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        comp = FastDash(callback_fn=f).inputs_with_ids[0]
    assert comp.__doc__ == dmc.TextInput().__doc__
    assert not [x for x in w if "Unknown or unsupported" in str(x.message)]
