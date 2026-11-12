"""inputs= / outputs= must match the callback (#348)."""

import warnings
from typing import Iterator, Tuple

import pytest

from fast_dash import FastDash, Slider, Text


def three(a: int = 1, b: int = 2, c: str = "x") -> str:
    """Needs a, b and c."""
    return f"{a}{b}{c}"


def two_required(a: int, b: int) -> str:
    return "x"


def _build(**kw):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app = FastDash(**kw)
    return app, [str(w.message) for w in caught if issubclass(w.category, UserWarning)
                 and ("inputs=" in str(w.message) or "outputs=" in str(w.message))]


def test_short_inputs_with_defaults_warns_and_names_the_stranded_params():
    app, msgs = _build(callback_fn=three, inputs=[Slider])
    assert [i.id for i in app.inputs_with_ids] == ["a"]
    assert len(msgs) == 1
    assert "has 1 component(s)" in msgs[0] and "b, c get no input" in msgs[0]


def test_short_inputs_leaving_a_required_param_raises():
    with pytest.raises(ValueError, match=r"b would have no input and no default"):
        FastDash(callback_fn=two_required, inputs=[Slider])


def test_long_inputs_warns_that_extras_are_ignored():
    _, msgs = _build(callback_fn=three, inputs=[Slider, Slider, Text, Text])
    assert len(msgs) == 1 and "the last 1 are ignored" in msgs[0]


def test_matching_and_inferred_inputs_are_silent():
    assert _build(callback_fn=three, inputs=[Slider, Slider, Text])[1] == []
    assert _build(callback_fn=three)[1] == []


def test_variadic_callback_is_not_counted():
    def kw(**fields) -> str:
        return "x"
    assert _build(callback_fn=kw, inputs=[Text, Text])[1] == []


def test_outputs_count_checked_against_a_fixed_return_annotation():
    def g(x: int = 1) -> str:
        return "hi"
    _, msgs = _build(callback_fn=g, outputs=[Text, Text, Text])
    assert len(msgs) == 1 and "annotated to return 1 value(s)" in msgs[0]

    def pair(x: int = 1) -> Tuple[str, str]:
        return "a", "b"
    assert _build(callback_fn=pair, outputs=[Text, Text])[1] == []
    assert "return 2 value(s)" in _build(callback_fn=pair, outputs=[Text])[1][0]


def test_outputs_unchecked_when_the_annotation_gives_no_count():
    def bare(x: int = 1):
        return "a", "b"

    def stream(x: int = 1) -> Iterator[str]:
        yield "a"

    assert _build(callback_fn=bare, outputs=[Text, Text])[1] == []
    assert _build(callback_fn=stream, outputs=[Text, Text])[1] == []
