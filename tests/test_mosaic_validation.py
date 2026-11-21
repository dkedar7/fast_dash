"""#296, #374: a mosaic must have exactly one cell per output."""
import pytest

from fast_dash import FastDash, Graph


def _three(rows: int = 2) -> (Graph, Graph, Graph):
    return None, None, None


def test_too_few_cells_fails_at_construction():
    with pytest.raises(ValueError, match="has 2 cell.*3 output.*'ABC'"):
        FastDash(callback_fn=_three, mosaic="AB")


def _two(rows: int = 2) -> (Graph, Graph):
    return None, None


@pytest.mark.parametrize("mosaic", ["ABC", "AB\nCC", "ABCD"])
def test_too_many_cells_fails_at_construction(mosaic):
    # A letter with no output used to render as its own literal text (#374).
    with pytest.raises(ValueError, match="cell.*but the function has 2 output.*'AB'") as e:
        FastDash(callback_fn=_two, mosaic=mosaic)
    assert str(e.value).isascii()


def test_single_output_with_two_cells_fails():
    def one(rows: int = 2) -> Graph:
        return None
    with pytest.raises(ValueError, match="2 cell.*1 output.*'A'"):
        FastDash(callback_fn=one, mosaic="AB")


@pytest.mark.parametrize("mosaic", [None, "ABC", "AAB\nCCB"])
def test_enough_cells_builds(mosaic):
    FastDash(callback_fn=_three, mosaic=mosaic)
