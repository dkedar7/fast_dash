#!/usr/bin/env python
"""Tests for `fast_dash` package."""
# pylint: disable=redefined-outer-name

from .examples import (
    example_1_simple_text_to_text,
    example_2_text_with_slider,
    example_3_image_to_image,
    example_4_image_slider_to_image_text,
    example_5_uploadimage_to_image,
)


def test_example_1(dash_duo):
    "Test example_1_simple_text_to_text"

    app = example_1_simple_text_to_text().app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#app_title", "Fast Dash example 1", timeout=4)

    assert dash_duo.find_element("#app_title").text == "Fast Dash example 1"
    assert dash_duo.get_logs() == [], "browser console should contain no error"


def test_example_2(dash_duo):
    "Test example_2_text_with_slider"

    app = example_2_text_with_slider().app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#app_title", "Fast Dash example 2", timeout=4)

    assert dash_duo.find_element("#app_title").text == "Fast Dash example 2"
    assert dash_duo.get_logs() == [], "browser console should contain no error"


def test_example_3(dash_duo):
    "Test example_3_image_to_image"

    app = example_3_image_to_image().app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#app_title", "Fast Dash example 3", timeout=4)

    assert dash_duo.find_element("#app_title").text == "Fast Dash example 3"
    assert dash_duo.get_logs() == [], "browser console should contain no error"


def test_example_4(dash_duo):
    "Test example_4_image_slider_to_image_text"

    app = example_4_image_slider_to_image_text().app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#app_title", "Fast Dash example 4", timeout=4)

    assert dash_duo.find_element("#app_title").text == "Fast Dash example 4"
    assert dash_duo.get_logs() == [], "browser console should contain no error"


def test_example_5(dash_duo):
    "Test example_5_uploadimage_to_image"

    app = example_5_uploadimage_to_image().app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#app_title", "Fast Dash example 5", timeout=4)

    assert dash_duo.find_element("#app_title").text == "Fast Dash example 5"
    assert dash_duo.get_logs() == [], "browser console should contain no error"