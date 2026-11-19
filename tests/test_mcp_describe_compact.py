"""#366: describe_app stays small after a run that produced a large output."""

import json

import numpy as np
import pandas as pd

from fast_dash import FastDash


def _table_app():
    def report(rows: int = 100, cols: int = 12) -> pd.DataFrame:
        """Return a wide-ish table."""
        return pd.DataFrame(np.round(np.random.rand(rows, cols), 4),
                            columns=[f"metric_{c}" for c in range(cols)])
    return FastDash(callback_fn=report, mcp_server=True)


def _text_app():
    def echo(n: int = 10) -> str:
        """n x's."""
        return "x" * n
    return FastDash(callback_fn=echo, mcp_server=True)


def test_large_table_is_summarized_and_fetchable_in_full():
    with _table_app().mcp_test_client() as app:
        before = len(json.dumps(app.describe_app()))
        run = app.invoke(inputs={"rows": 100, "cols": 12})
        d = app.describe_app()
        assert len(json.dumps(d)) < before + 600      # was ~55x before #366
        out = d["outputs"][0]
        assert out["current_value_summarized"] is True
        assert out["current_value"]["type"] == "DataFrame"
        assert out["current_value"]["shape"] == [100, 12]
        assert out["history_index"] == run["history_index"]
        full = app.get_invocation(index=out["history_index"])["outputs"]
        assert full == run["outputs"]
        assert len(next(iter(full.values()))["records"]) == 100


def test_small_value_is_whole_and_unflagged():
    with _table_app().mcp_test_client() as app:
        run = app.invoke(inputs={"rows": 2, "cols": 2})
        out = app.describe_app()["outputs"][0]
        assert out["current_value"] == next(iter(run["outputs"].values()))
        assert "current_value_summarized" not in out and "history_index" not in out


def test_text_keeps_whole_up_to_the_limit_then_summarizes():
    with _text_app().mcp_test_client() as app:
        app.invoke(inputs={"n": 1500})      # well past the old 200-char preview (#261)
        out = app.describe_app()["outputs"][0]
        assert out["current_value"] == "x" * 1500
        app.invoke(inputs={"n": 5000})
        out = app.describe_app()["outputs"][0]
        assert out["current_value_summarized"] is True
        assert out["current_value"]["len"] == 5000
        assert app.get_invocation(index=out["history_index"])["outputs"] == {
            out["id"]: "x" * 5000}


def test_no_run_no_value():
    with _table_app().mcp_test_client() as app:
        out = app.describe_app()["outputs"][0]
        assert "current_value" not in out and "history_index" not in out
