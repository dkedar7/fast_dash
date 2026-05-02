"""Lightweight password authentication for Fast Dash apps.

Fast Dash apps default to no auth — anyone with the URL can use them.
This module adds an opt-in password gate so a developer can share an
app behind a tunnel (cloudflared, ngrok, ...) without exposing it to
the public internet.

Usage::

    from fast_dash import fastdash

    @fastdash(auth={"alice": "wonderland", "bob": "builder"})
    def greet(name: str = "world") -> str:
        return f"Hello, {name}!"

The first time a visitor hits any URL on the app, they are redirected
to ``/login``. After a successful login, a session cookie is set and
they can access the app normally. ``/logout`` clears the session.

The current user's name is exposed inside callbacks via
``fast_dash.current_user()``.

Security notes (read these before using in anger):
- The user dict is stored in memory; passwords are compared in constant
  time but **not hashed**. For shared/multi-user environments, hash
  externally (e.g. ``argon2`` / ``bcrypt``) and supply a custom
  ``verify_fn`` instead of a plain dict.
- Sessions are signed with Flask's ``SECRET_KEY``. Fast Dash generates
  a random key per process; restart-stable sessions require the user
  to set ``FASTDASH_SECRET_KEY`` in the environment.
- This is a single-tenant gate, not a full identity provider. For
  Google / GitHub / Microsoft sign-in, a future ``auth="oidc"``
  variant is planned.
"""

from __future__ import annotations

import hmac
import os
import secrets
from typing import Callable, Mapping

from flask import (
    Flask,
    abort,
    g,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)


# ---- public surface --------------------------------------------------


def current_user() -> str | None:
    """Return the username for the active request, or ``None``.

    Safe to call from inside any Fast Dash callback. Returns ``None``
    when auth is disabled or when called outside a request context.
    """
    try:
        return session.get("_fastdash_user")
    except RuntimeError:
        # Outside an app/request context.
        return None


# ---- configuration ---------------------------------------------------


def _normalize_auth_config(auth) -> _AuthConfig | None:
    """Turn whatever the user passed into a typed config object.

    Accepts:
    - ``None`` / ``False`` → auth disabled (returns ``None``).
    - ``{"alice": "secret"}`` → password dict.
    - A callable ``verify_fn(username, password) -> bool`` for custom
      verification (e.g. against a hashed store).
    """
    if not auth:
        return None
    if callable(auth):
        return _AuthConfig(verify=auth)
    if isinstance(auth, Mapping):
        users = dict(auth)
        return _AuthConfig(verify=lambda u, p: _verify_against_dict(users, u, p))
    raise TypeError(
        "auth= must be a dict of {username: password}, a verify function, "
        f"or None. Got {type(auth).__name__}."
    )


class _AuthConfig:
    """Bundle of the verifier callable used by the middleware."""

    def __init__(self, verify: Callable[[str, str], bool]):
        self.verify = verify


def _verify_against_dict(users: dict, username: str, password: str) -> bool:
    """Constant-time check of (username, password) against a user dict."""
    expected = users.get(username)
    if expected is None:
        # Hash comparison still runs against a known-bad value to keep
        # timing constant whether or not the username exists.
        return hmac.compare_digest(b"x", b"y")
    return hmac.compare_digest(
        password.encode("utf-8"), str(expected).encode("utf-8")
    )


# ---- middleware ------------------------------------------------------


_LOGIN_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Sign in{% if title %} — {{ title }}{% endif %}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
           background: #f8f9fa; display: flex; align-items: center;
           justify-content: center; min-height: 100vh; margin: 0; }
    form { background: #fff; padding: 32px 28px; border-radius: 8px;
           box-shadow: 0 2px 12px rgba(0,0,0,.06); width: 320px;
           display: flex; flex-direction: column; gap: 12px; }
    h1 { margin: 0 0 8px 0; font-size: 18px; font-weight: 600; }
    label { font-size: 12px; color: #555; }
    input[type=text], input[type=password] { padding: 8px 10px; font-size: 14px;
           border: 1px solid #ced4da; border-radius: 4px; }
    button { padding: 9px 12px; font-size: 14px; background: #1c7ed6;
             color: #fff; border: 0; border-radius: 4px; cursor: pointer; }
    button:hover { background: #1971c2; }
    .err { color: #c92a2a; font-size: 13px; }
  </style>
</head>
<body>
  <form method="post">
    <h1>{% if title %}{{ title }}{% else %}Fast Dash app{% endif %}</h1>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
    <label for="u">Username</label>
    <input id="u" type="text" name="username" autofocus required>
    <label for="p">Password</label>
    <input id="p" type="password" name="password" required>
    <input type="hidden" name="next" value="{{ next }}">
    <button type="submit">Sign in</button>
  </form>
</body>
</html>
"""


def install_auth(server: Flask, config: _AuthConfig, title: str | None = None) -> None:
    """Wire login / logout routes and a ``before_request`` gate onto the app."""

    # Random per-process key. Users who restart frequently and want
    # session continuity should set FASTDASH_SECRET_KEY.
    if not server.secret_key:
        server.secret_key = os.environ.get(
            "FASTDASH_SECRET_KEY", secrets.token_hex(32)
        )

    open_paths = {"/login", "/logout"}

    @server.before_request
    def _require_login():
        if request.path in open_paths:
            return None
        if request.path.startswith("/_dash") and "_fastdash_user" not in session:
            # Dash's internal endpoints (callback updates, asset bundles)
            # would otherwise leak app state to unauthenticated callers.
            abort(401)
        if "_fastdash_user" not in session:
            return redirect(url_for("_fastdash_login", next=request.path))
        g.fastdash_user = session["_fastdash_user"]
        return None

    @server.route("/login", methods=["GET", "POST"])
    def _fastdash_login():
        next_url = request.values.get("next") or "/"
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            if config.verify(username, password):
                session.clear()
                session["_fastdash_user"] = username
                session.permanent = False
                return redirect(next_url)
            return (
                render_template_string(
                    _LOGIN_TEMPLATE,
                    error="Invalid username or password.",
                    next=next_url,
                    title=title,
                ),
                401,
            )
        return render_template_string(
            _LOGIN_TEMPLATE, error=None, next=next_url, title=title
        )

    @server.route("/logout")
    def _fastdash_logout():
        session.clear()
        return redirect(url_for("_fastdash_login"))
