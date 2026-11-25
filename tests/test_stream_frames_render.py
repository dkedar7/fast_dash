"""stream=True frames must render live in the browser, not only at the end (#386).

Two gates hid them: on Flask, outputs never had ``stream=True``, so no
socket.io listener or apply callback existed and every frame was dropped in
the browser; on both backends, the run's ``.fd-loading`` skeleton hid the
output content until the callback returned.
"""

import json
import time

import pandas as pd
import pytest

from fast_dash import FastDash, Markdown, Text
from fast_dash import fast_dash as fd_mod


def slow_count(n: int = 10) -> str:
    out = ""
    for i in range(1, n + 1):
        out += f"tick {i} "
        time.sleep(0.4)
        yield out


def _layout_component(layout, cid):
    stack = [layout]
    while stack:
        c = stack.pop()
        if getattr(c, "id", None) == cid:
            return c
        ch = getattr(c, "children", None)
        stack.extend(x for x in (ch if isinstance(ch, list) else [ch])
                     if hasattr(x, "to_plotly_json"))
    return None


def _socket_callbacks(app):
    return {k: v for k, v in app.callback_map.items()
            if any(i.get("id") == "socketio" for i in v.get("inputs", []))}


def test_stream_app_marks_outputs_and_listens_for_them():
    fd = FastDash(callback_fn=slow_count, stream=True)
    out = fd.outputs_with_ids[0]
    assert out.stream is True
    sio = _layout_component(fd.app.layout, "socketio")
    assert out.id in sio.eventNames
    cbs = _socket_callbacks(fd.app)
    assert any(k.startswith(f"{out.id}.") for k in cbs), list(cbs)


def test_non_stream_app_is_unchanged():
    fd = FastDash(callback_fn=lambda n=1: n)
    assert fd.outputs_with_ids[0].stream is False
    out_id = fd.outputs_with_ids[0].id
    sio = _layout_component(fd.app.layout, "socketio")
    assert sio is None or out_id not in (sio.eventNames or [])
    assert not any(k.startswith(f"{out_id}.") for k in _socket_callbacks(fd.app))


def test_multiple_outputs_all_stream():
    def two(n: int = 2):
        yield "a", "b"

    fd = FastDash(callback_fn=two, stream=True, outputs=[Text, Markdown])
    assert [o.stream for o in fd.outputs_with_ids] == [True, True]


def test_output_apply_callback_lifts_the_skeleton():
    fd = FastDash(callback_fn=slow_count, stream=True)
    out_id = fd.outputs_with_ids[0].id
    funcs = fd.app._inline_scripts if hasattr(fd.app, "_inline_scripts") else []
    script = "\n".join(funcs)
    assert "set_props('output-loading-wrap', {className: ''})" in script
    # Notifications reuse the plain function: they must not reveal the pane.
    cbs = _socket_callbacks(fd.app)
    assert any(k.startswith("notification-container.") for k in cbs)
    assert any(k.startswith(f"{out_id}.") for k in cbs)


def test_flask_frame_is_sent_in_the_outputs_shape(monkeypatch):
    def table(n: int = 1) -> pd.DataFrame:
        yield pd.DataFrame({"a": [n]})

    fd = FastDash(callback_fn=table, stream=True)
    sent = []
    monkeypatch.setattr(fd_mod, "emit", lambda event, payload, **kw: sent.append((event, payload)))
    out = fd.outputs_with_ids[0]
    fd.stream_handler(out.id, pd.DataFrame({"a": [7]}), socket_id="sid", notification=False)
    (event, payload), = sent
    assert event == out.id
    json.dumps(payload)                          # JSON, not a raw DataFrame
    assert payload["append"] is False and "7" in json.dumps(payload["value"])


def test_native_frame_lifts_the_skeleton(monkeypatch):
    import dash

    fd = FastDash(callback_fn=slow_count, stream=True)
    calls = []
    monkeypatch.setattr(dash, "set_props", lambda cid, props: calls.append((cid, props)))
    out = fd.outputs_with_ids[0]
    fd.stream_handler_native(out.id, "tick 1 ", notification=False)
    assert (out.id, {out.component_property: "tick 1 "}) in calls
    assert ("output-loading-wrap", {"className": ""}) in calls


def test_partial_frame_is_visible_mid_run(dash_duo):
    """Real browser: a frame shows while the run is still going (Flask)."""
    from tests._browser import click_run

    app = FastDash(callback_fn=slow_count, stream=True, title="Stream Live").app
    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#title8888928", "Stream Live", timeout=20)
    click_run(dash_duo)

    out = "#output_output_1"
    seen = None
    deadline = time.time() + 20
    while time.time() < deadline:
        text = dash_duo.find_element(out).text      # .text is "" while hidden
        if "tick" in text:
            seen = text
            break
        time.sleep(0.1)
    assert seen and "tick 10" not in seen, f"no live frame before the end: {seen!r}"
    dash_duo.wait_for_contains_text(out, "tick 10", timeout=20)
