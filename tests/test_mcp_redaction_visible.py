"""#380: when a secret is masked out of an output, the agent is told."""

from fast_dash import FastDash, PasswordInput


def report(pin: PasswordInput = "x", note: str = "n") -> str:
    """Reports."""
    return f"Result 42 apples, temperature 42F, note={note}"


def two(pin: PasswordInput = "x") -> (str, str):
    """One output echoes the pin, one does not."""
    return f"pin was {pin}", "nothing secret"


def test_a_masked_output_is_named():
    with FastDash(callback_fn=report, mcp_server=True).mcp_test_client() as app:
        run = app.invoke(inputs={"pin": "42", "note": "x"})
        # Still masked: any 42 could be the PIN. But now the agent knows.
        assert "42" not in run["outputs"]["output_output_1"]
        assert run["redacted"] == ["output_output_1"]
        again = app.get_invocation(index=run["history_index"])
        assert again["redacted"] == ["output_output_1"]
        (out,) = app.describe_app()["outputs"]
        assert out["redacted"] is True and "42" not in str(out["current_value"])


def test_no_flag_when_nothing_was_masked():
    with FastDash(callback_fn=report, mcp_server=True).mcp_test_client() as app:
        run = app.invoke(inputs={"pin": "Zq9_Longrandomsecret_7", "note": "ok"})
        assert "redacted" not in run
        assert run["outputs"]["output_output_1"].startswith("Result 42 apples")
        assert "redacted" not in app.get_invocation(index=run["history_index"])
        assert "redacted" not in app.describe_app()["outputs"][0]


def test_only_the_outputs_that_held_the_secret_are_named():
    with FastDash(callback_fn=two, mcp_server=True).mcp_test_client() as app:
        run = app.invoke(inputs={"pin": "hunter2-secret"})
        assert len(run["redacted"]) == 1
        (masked,) = run["redacted"]
        assert run["outputs"][masked] == "pin was ********"
        others = [v for k, v in run["outputs"].items() if k != masked]
        assert others == ["nothing secret"]
