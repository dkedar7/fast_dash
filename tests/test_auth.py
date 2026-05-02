"""Tests for the password-auth gate added in v0.2.17.

These tests use Flask's built-in test client so we can exercise the
middleware without a browser. Each test builds a small FastDash app
with ``auth={...}`` or ``auth=callable`` and walks through the login
flow.
"""

import pytest

from fast_dash import FastDash, current_user


def _make_app(auth=None, callback=None):
    """Helper: build a tiny FastDash app with optional auth."""
    if callback is None:
        def callback(name: str = "world") -> str:
            return f"Hello, {name}!"
    return FastDash(callback_fn=callback, auth=auth)


# --- baseline: no auth ----------------------------------------------------


class TestAuthDisabled:
    def test_default_app_has_no_auth(self):
        app = _make_app()
        assert app._auth_config is None

    def test_app_root_is_reachable_without_login_when_auth_off(self):
        app = _make_app()
        client = app.server.test_client()
        resp = client.get("/")
        assert resp.status_code == 200

    def test_no_login_form_when_auth_disabled(self):
        app = _make_app()
        client = app.server.test_client()
        # When auth is off, /login isn't claimed by the auth blueprint —
        # it falls through to Dash's catch-all (which serves the SPA),
        # so the login form is never rendered.
        resp = client.get("/login")
        assert b"Sign in" not in resp.data

    def test_current_user_returns_none_outside_request_context(self):
        # No exception, no login — just None.
        assert current_user() is None


# --- dict-based auth ------------------------------------------------------


class TestDictAuth:
    def test_unauthenticated_root_redirects_to_login(self):
        app = _make_app(auth={"alice": "wonderland"})
        client = app.server.test_client()
        resp = client.get("/")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_login_page_renders(self):
        app = _make_app(auth={"alice": "wonderland"})
        client = app.server.test_client()
        resp = client.get("/login")
        assert resp.status_code == 200
        assert b"Sign in" in resp.data

    def test_correct_credentials_grant_access(self):
        app = _make_app(auth={"alice": "wonderland"})
        client = app.server.test_client()
        resp = client.post(
            "/login",
            data={"username": "alice", "password": "wonderland", "next": "/"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        # Now the root should be reachable on the authenticated session.
        with client.session_transaction() as s:
            assert s["_fastdash_user"] == "alice"
        resp = client.get("/")
        assert resp.status_code == 200

    def test_wrong_password_returns_401_with_error(self):
        app = _make_app(auth={"alice": "wonderland"})
        client = app.server.test_client()
        resp = client.post(
            "/login",
            data={"username": "alice", "password": "WRONG", "next": "/"},
        )
        assert resp.status_code == 401
        assert b"Invalid username or password" in resp.data

    def test_unknown_user_returns_401(self):
        app = _make_app(auth={"alice": "wonderland"})
        client = app.server.test_client()
        resp = client.post(
            "/login",
            data={"username": "mallory", "password": "anything", "next": "/"},
        )
        assert resp.status_code == 401

    def test_logout_clears_session(self):
        app = _make_app(auth={"alice": "wonderland"})
        client = app.server.test_client()
        client.post(
            "/login",
            data={"username": "alice", "password": "wonderland", "next": "/"},
        )
        resp = client.get("/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
        with client.session_transaction() as s:
            assert "_fastdash_user" not in s

    def test_dash_internal_endpoints_blocked_when_unauthenticated(self):
        """Dash's _dash-* endpoints would otherwise leak callback state."""
        app = _make_app(auth={"alice": "wonderland"})
        client = app.server.test_client()
        # Pick a Dash endpoint that exists by default.
        resp = client.get("/_dash-layout")
        assert resp.status_code == 401

    def test_login_preserves_next_url(self):
        app = _make_app(auth={"alice": "wonderland"})
        client = app.server.test_client()
        resp = client.get("/some/path")
        assert resp.status_code == 302
        # The redirect should embed /some/path as the `next` query arg
        # so a successful login bounces the user back where they came from.
        location = resp.headers["Location"]
        assert "/some/path" in location and "next=" in location


# --- callable verifier ---------------------------------------------------


class TestCallableAuth:
    def test_custom_verify_fn_is_called(self):
        calls = []

        def verify(u, p):
            calls.append((u, p))
            return u == "carol" and p == "topsecret"

        app = _make_app(auth=verify)
        client = app.server.test_client()
        resp = client.post(
            "/login",
            data={"username": "carol", "password": "topsecret", "next": "/"},
        )
        assert resp.status_code == 302
        assert ("carol", "topsecret") in calls

    def test_custom_verify_fn_can_reject(self):
        app = _make_app(auth=lambda u, p: False)
        client = app.server.test_client()
        resp = client.post(
            "/login",
            data={"username": "anyone", "password": "anything", "next": "/"},
        )
        assert resp.status_code == 401


# --- input validation ----------------------------------------------------


class TestAuthConfigValidation:
    def test_invalid_auth_type_raises(self):
        with pytest.raises(TypeError, match="auth="):
            _make_app(auth=12345)

    def test_falsy_values_disable_auth(self):
        for falsy in (None, False, {}):
            app = _make_app(auth=falsy)
            assert app._auth_config is None


# --- header logout button -----------------------------------------------


class TestLogoutButton:
    def test_logout_button_in_header_when_auth_enabled(self):
        app = _make_app(auth={"alice": "wonderland"})
        layout_str = str(app.app.layout)
        assert "logout-button" in layout_str
        assert "Sign out" in layout_str

    def test_no_logout_button_when_auth_disabled(self):
        app = _make_app()
        layout_str = str(app.app.layout)
        assert "logout-button" not in layout_str
        assert "Sign out" not in layout_str

    def test_logout_button_links_to_logout_route(self):
        app = _make_app(auth={"alice": "wonderland"})
        layout_str = str(app.app.layout)
        # The button is wrapped in an <html.A href="/logout">.
        assert "/logout" in layout_str


# --- current_user inside a request --------------------------------------


class TestCurrentUserBinding:
    def test_current_user_is_accessible_inside_a_request(self):
        app = _make_app(auth={"alice": "wonderland"})

        # Register the probe route *before* the first request lands —
        # Flask freezes the route table after that.
        @app.server.route("/_whoami")
        def _whoami():
            return current_user() or "anonymous"

        client = app.server.test_client()
        client.post(
            "/login",
            data={"username": "alice", "password": "wonderland", "next": "/"},
        )

        resp = client.get("/_whoami")
        assert resp.status_code == 200
        assert resp.data == b"alice"
