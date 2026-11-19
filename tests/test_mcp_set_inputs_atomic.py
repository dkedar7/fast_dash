"""#368: set_inputs is all or nothing, like invoke."""

from fast_dash import FastDash, depends_on


def _add_app():
    def add(a: int = 1, b: int = 2) -> int:
        """sum a and b"""
        return a + b
    return FastDash(callback_fn=add, mcp_server=True)


def _current(app):
    return {i["id"]: i["current_value"] for i in app.describe_app()["inputs"]}


def test_one_bad_value_changes_nothing():
    with _add_app().mcp_test_client() as app:
        r = app.set_inputs(inputs={"a": 99, "b": "oops"})
        assert r["ok"] is False and r["applied"] == {}
        assert set(r["errors"]) == {"b"}
        assert _current(app) == {"a": 1, "b": 2}
        assert app.invoke()["outputs"] == {"output_output_1": 3}    # not 101


def test_unknown_id_changes_nothing():
    with _add_app().mcp_test_client() as app:
        r = app.set_inputs(inputs={"a": 5, "nope": 1})
        assert r["ok"] is False and r["errors"] == {"nope": "unknown id"}
        assert _current(app) == {"a": 1, "b": 2}


def test_all_valid_applies_all():
    with _add_app().mcp_test_client() as app:
        r = app.set_inputs(inputs={"a": 10, "b": 20})
        assert r == {"ok": True, "applied": {"a": 10, "b": 20}, "errors": {}}
        assert app.invoke()["outputs"] == {"output_output_1": 30}


def test_parent_and_child_in_one_call_still_validate_together():
    countries = {"USA": ["California", "Texas"], "India": ["Delhi", "Goa"]}

    def pick(country: str = list(countries),
             state: str = depends_on("country", lambda c: countries[c])) -> str:
        """Pick a state."""
        return f"{state}, {country}"

    with FastDash(callback_fn=pick, mcp_server=True).mcp_test_client() as app:
        # Goa is valid only once India is set earlier in the same call.
        assert app.set_inputs(inputs={"country": "India", "state": "Goa"})["ok"] is True
        assert _current(app) == {"country": "India", "state": "Goa"}
        # A bad child rejects the parent change too.
        r = app.set_inputs(inputs={"country": "USA", "state": "Delhi"})
        assert r["ok"] is False and set(r["errors"]) == {"state"}
        assert _current(app) == {"country": "India", "state": "Goa"}
