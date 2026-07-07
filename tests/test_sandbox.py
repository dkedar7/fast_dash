"""The sandbox: captures figures/tables/output/errors, and stays locked down.

Ported from DataChat's suite (which passes on Windows) and generalized to
fast_dash's data-agnostic ``run_code(code, inject=...)`` engine. The security
tests (secrets scrubbed, network blocked, timeout kills) are the load-bearing
ones and are preserved.
"""

import pandas as pd

from fast_dash.sandbox import run_code


def _df():
    return pd.DataFrame({"g": ["a", "b", "a"], "v": [1, 2, 3]})


# --- capture: figure / table / stdout / result / error --------------------- #

def test_produces_figure_from_fig_var():
    r = run_code("fig = px.bar(df, x='g', y='v')", inject={"df": _df()})
    assert r["figure"] and r["error"] is None


def test_bare_expression_figure_is_captured():
    r = run_code("px.histogram(df, x='v')", inject={"df": _df()})
    assert r["figure"]


def test_figure_is_json_string():
    r = run_code("px.bar(df, x='g', y='v')", inject={"df": _df()})
    import json
    parsed = json.loads(r["figure"])           # plotly JSON -> dict
    assert "data" in parsed


def test_table_and_stdout():
    r = run_code(
        "print('n', len(df)); result = df.groupby('g')['v'].sum().reset_index()",
        inject={"df": _df()},
    )
    assert r["table"]["shape"][0] == 2
    assert "n 3" in r["stdout"]


def test_last_expression_scalar_result():
    r = run_code("21 * 2", inject={})
    assert r["result"] == 42 and r["error"] is None


def test_error_is_captured_not_raised():
    r = run_code("df.this_does_not_exist()", inject={"df": _df()})
    assert r["error"] and "this_does_not_exist" in r["error"]


def test_inject_roundtrip():
    # An injected value must arrive intact (pickle handoff), including a DataFrame.
    r = run_code("print(sum(nums)); df.shape[0]",
                 inject={"nums": [1, 2, 3, 4], "df": _df()})
    assert "10" in r["stdout"]
    assert r["result"] == 3                     # df has 3 rows


# --- security: scrubbing / network / timeout ------------------------------- #

def test_network_is_blocked():
    r = run_code(
        "import urllib.request; urllib.request.urlopen('http://example.com')",
        inject={},
    )
    assert r["error"] and (
        "disabled" in r["error"].lower() or "OSError" in r["error"]
    )


def test_secrets_are_scrubbed(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-SECRET-value")
    monkeypatch.setenv("MY_ANTHROPIC_TOKEN", "sk-ant-SECRET")
    r = run_code(
        "import os; print(os.environ.get('OPENROUTER_API_KEY'), "
        "os.environ.get('MY_ANTHROPIC_TOKEN'))",
        inject={},
    )
    assert "sk-SECRET" not in (r["stdout"] or "")
    assert "sk-ant-SECRET" not in (r["stdout"] or "")


def test_timeout_is_enforced():
    r = run_code("while True:\n    pass", inject={}, timeout=3)
    assert r["error"] and "longer than" in r["error"]
