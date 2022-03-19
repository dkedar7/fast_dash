#!/usr/bin/env python
"""Tests for `fast_dash` package."""
# pylint: disable=redefined-outer-name

from fast_dash import FastDash
from fast_dash.Components import Text


## Define callback functions
def simple_text_to_text_function(input_text):
    return input_text


def test_fdfd001_set_title(dash_duo):
    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        title="App title",
    ).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#app_title", "App title", timeout=4)

    assert dash_duo.find_element("#app_title").text == "App title"
    assert dash_duo.get_logs() == [], "browser console should contain no error"

    dash_duo.percy_snapshot("bsly001-layout")
