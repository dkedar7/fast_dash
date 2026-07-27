#!/usr/bin/env python
"""Draggable input sidebar (issue #80).

The drag itself is clientside (assets/fd_sidebar_resize.js writes Mantine's
AppShell CSS vars), so these cover the parts Python owns: the handle and store
are in the layout, and the width a user dragged to survives the collapse/expand
callback that re-renders the shell.
"""
import json

from fast_dash import FastDash


def _ids(component, out=None):
    out = set() if out is None else out
    cid = getattr(component, "id", None)
    if isinstance(cid, str):
        out.add(cid)
    children = getattr(component, "children", None)
    for child in (
        children if isinstance(children, (list, tuple))
        else [children] if children is not None else []
    ):
        if child is not None:
            _ids(child, out)
    return out


def _app():
    def f(x: str = "hi") -> str:
        """Echo."""
        return x

    return FastDash(callback_fn=f)


def _toggle(app, opened, width):
    """Drive the real toggle_sidebar callback over Dash's update wire."""
    client = app.app.server.test_client()
    payload = {
        "output": "appshell.navbar",
        "outputs": {"id": "appshell", "property": "navbar"},
        "inputs": [{"id": "sidebar-button", "property": "opened", "value": opened}],
        "state": [{"id": "fd-sidebar-width", "property": "data", "value": width}],
        "changedPropIds": ["sidebar-button.opened"],
    }
    r = client.post(
        "/_dash-update-component",
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    return (r.get_json() or {})["response"]["appshell"]["navbar"]


def test_sidebar_layout_has_resize_handle_and_store():
    ids = _ids(_app().app.layout)
    assert "fd-sidebar-resizer" in ids
    assert "fd-sidebar-width" in ids


def test_chat_layout_has_resize_handle():
    from fast_dash import Chat

    def chat_fn(query: str, temperature: float = 0.5) -> Chat:
        """Chat."""
        return {"query": query, "response": "hi"}

    ids = _ids(FastDash(callback_fn=chat_fn, chat=True).app.layout)
    assert "fd-sidebar-resizer" in ids
    assert "fd-sidebar-width" in ids


def test_toggle_keeps_the_default_width_when_never_dragged():
    assert _toggle(_app(), True, None)["width"] == 300


def test_toggle_preserves_a_dragged_width():
    # Regression: toggle_sidebar re-renders the shell from the navbar prop, so
    # returning the hardcoded default snapped a resized sidebar back to 300 on
    # the next collapse/expand.
    assert _toggle(_app(), True, 640)["width"] == 640


def test_dragged_width_survives_a_collapse_expand_cycle():
    app = _app()
    assert _toggle(app, False, 640)["width"] == 640     # collapsed
    assert _toggle(app, True, 640)["width"] == 640      # re-expanded


def test_bogus_stored_width_falls_back_to_the_default():
    for junk in ("wide", 0, -50, None):
        assert _toggle(_app(), True, junk)["width"] == 300


def test_resizer_handle_is_keyboard_reachable():
    handle = next(
        c for c in _walk(_app().app.layout)
        if getattr(c, "id", None) == "fd-sidebar-resizer"
    )
    assert handle.tabIndex == 0
    assert handle.role == "separator"


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    for child in (
        children if isinstance(children, (list, tuple))
        else [children] if children is not None else []
    ):
        if child is not None:
            yield from _walk(child)


def test_drag_script_caps_width_at_half_the_viewport():
    """Issue #80 asks for 'up to 50% of the width of the screen'."""
    js = (
        __import__("pathlib").Path("fast_dash/assets/fd_sidebar_resize.js")
        .read_text(encoding="utf-8")
    )
    assert "MAX_FRACTION = 0.5" in js
    # Both vars must move together or the output pane stays put while the
    # sidebar grows, leaving the content shifted under it.
    assert "--app-shell-navbar-width" in js
    assert "--app-shell-navbar-offset" in js
