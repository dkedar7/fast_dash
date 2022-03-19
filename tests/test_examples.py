#!/usr/bin/env python
"""Tests for `fast_dash` package."""
# pylint: disable=redefined-outer-name

from .examples import example_1_simple_text_to_text, example_2_text_with_slider


def test_example_1(dash_duo):
    "Test example_1_simple_text_to_text"

    app = example_1_simple_text_to_text().app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#app_title", "App title", timeout=4)

    assert dash_duo.find_element("#app_title").text == "App title"
    assert dash_duo.get_logs() == [], "browser console should contain no error"


def test_example_2(dash_duo):
    "Test example_2_text_with_slider"

    app = example_2_text_with_slider().app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#app_title", "App title", timeout=4)

    assert dash_duo.find_element("#app_title").text == "App title"
    assert dash_duo.get_logs() == [], "browser console should contain no error"