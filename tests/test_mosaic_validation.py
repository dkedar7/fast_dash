"""#296: a mosaic must give every output a cell."""
import pytest

from fast_dash import FastDash, Graph


def _three(rows: int = 2) -> (Graph, Graph, Graph):
    return None, None, None


def test_too_few_cells_fails_at_construction():
    with pytest.raises(ValueError, match="has 2 cell.*3 outputs.*'ABC'"):
        FastDash(callback_fn=_three, mosaic="AB")


@pytest.mark.parametrize("mosaic", [None, "ABC", "AAB\nCCB"])
def test_enough_cells_builds(mosaic):
    FastDash(callback_fn=_three, mosaic=mosaic)
