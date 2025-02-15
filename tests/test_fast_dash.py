#!/usr/bin/env python
"""Tests for `fast_dash` package."""
# pylint: disable=redefined-outer-name

from fast_dash import FastDash
from fast_dash.Components import Text
import matplotlib.pyplot as plt

import time

import pytest
from selenium.common.exceptions import NoSuchElementException


## Define callback functions
def simple_text_to_text_function(input_text):
    "Converts text to text"
    return input_text


def simple_text_to_multiple_text_function(input_text):
    return input_text, input_text


def simple_text_to_multiple_outputs(
    input_text: str,
) -> (plt.Figure, str):
    "Something"

    fig, ax = plt.subplots(1, 1)
    ax.plot([1, 2, 3], [1, 2, 3])

    return fig, "Return some text"


def test_fdfd001_set_title(dash_duo):
    "Test title element"
    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        title="App title",
    ).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#title8888928", "App title", timeout=4)

    assert dash_duo.find_element("#title8888928").text == "App title"
    assert dash_duo.get_logs() in [[], None], "browser console should contain no error"


def test_fdfd002_set_default_title(dash_duo):
    "Test default title"
    app = FastDash(
        callback_fn=simple_text_to_text_function, inputs=Text, outputs=Text
    ).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal(
        "#title8888928", "Simple Text To Text Function", timeout=4
    )

    assert dash_duo.find_element("#title8888928").text == "Simple Text To Text Function"
    assert dash_duo.get_logs() in [[], None], "browser console should contain no error"


def test_fdfd003_output_is_none(dash_duo):
    "Test if the output is set to Text if none is specified"
    app = FastDash(callback_fn=simple_text_to_text_function, inputs=Text).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal(
        "#title8888928", "Simple Text To Text Function", timeout=4
    )

    assert dash_duo.get_logs() in [[], None], "browser console should contain no error"


def test_fdfd004_click_submit(dash_duo):
    "Test clicking the submit button"
    app = FastDash(callback_fn=simple_text_to_text_function, inputs=Text).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal(
        "#title8888928", "Simple Text To Text Function", timeout=4
    )

    # Enter some text
    form_textfield = dash_duo.find_element("#input_text")
    form_textfield.send_keys("Sample text")

    # Click submit
    dash_duo.multiple_click("#submit_inputs", 1)
    dash_duo.wait_for_text_to_equal("#output-1", "Sample text", timeout=4)
    time.sleep(4)

    # Click clear
    dash_duo.multiple_click("#reset_inputs", 1)
    dash_duo.wait_for_text_to_equal("#output-1", "", timeout=4)


def test_fdfd005_multiple_outputs(dash_duo):
    "Test what happens when a function returns a tuple as the output"
    app = FastDash(
        callback_fn=simple_text_to_multiple_text_function,
        inputs=Text,
        outputs=[Text, Text],
    ).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal(
        "#title8888928", "Simple Text To Multiple Text Function", timeout=4
    )

    # Enter some text
    form_textfield = dash_duo.find_element("#input_text")
    form_textfield.send_keys("Sample text")

    # Click submit
    dash_duo.multiple_click("#submit_inputs", 1)
    dash_duo.wait_for_text_to_equal("#output-1", "Sample text", timeout=4)
    dash_duo.wait_for_text_to_equal("#output-2", "Sample text", timeout=4)
    time.sleep(4)

    # Click clear
    dash_duo.multiple_click("#reset_inputs", 1)
    dash_duo.wait_for_text_to_equal("#output-1", "", timeout=4)
    dash_duo.wait_for_text_to_equal("#output-2", "", timeout=4)


def test_fdfd006_live_update(dash_duo):
    "Test live update functionality"
    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        title="App title",
        update_live=True,
    ).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#title8888928", "App title", timeout=4)

    assert dash_duo.find_element("#title8888928").text == "App title"
    assert dash_duo.get_logs() in [[], None], "browser console should contain no error"

    dash_duo.percy_snapshot("fdfd006-layout")


def test_fdfd007_subheader_docstring(dash_duo):
    "Test if subheader is function doc string if set to None"
    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        title="App title",
        update_live=True,
    ).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#title8888928", "App title", timeout=4)

    assert dash_duo.find_element("#subheader6904007").text == "Converts text to text"
    assert dash_duo.get_logs() in [[], None], "browser console should contain no error"

    dash_duo.percy_snapshot("fdfd007-layout")


def test_fdfd008_minimal_mode(dash_duo):
    "Test Fast Dash's minimal mode"
    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        minimal=True,
    ).app

    dash_duo.start_server(app)
    time.sleep(4)

    with pytest.raises(NoSuchElementException):
        dash_duo.find_element("title8888928")

    with pytest.raises(NoSuchElementException):
        dash_duo.find_element("subheader6904007")

    with pytest.raises(NoSuchElementException):
        dash_duo.find_element("navbar3260780")

    with pytest.raises(NoSuchElementException):
        dash_duo.find_element("header1162572")

    with pytest.raises(NoSuchElementException):
        dash_duo.find_element("footer5265971")

    assert dash_duo.get_logs() in [[], None], "browser console should contain no error"

    dash_duo.percy_snapshot("fdfd008-layout")


def test_fdfd009_jupyter_dash(dash_duo):
    "Test Fast Dash's mode argument"

    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        mode="inline",
    ).app

    dash_duo.start_server(app)
    time.sleep(4)


def test_fdfd010_output_labels(dash_duo):
    "Test the auto-infer variable name feature"

    app = FastDash(callback_fn=simple_text_to_multiple_outputs)
    assert app.output_labels == ["FIG", "RETURN_SOME_TEXT"]


def test_fdfd011_base_layout(dash_duo):
    "Test base layout"

    app = FastDash(callback_fn=simple_text_to_multiple_outputs, layout="base")
    assert app.output_labels == ["FIG", "RETURN_SOME_TEXT"]


def test_fdfd012_about_button_true(dash_duo):
    "Test the about button auto-documentation generation"

    def example_function(param1, param2=42):
        """
        An example function for demonstration.

        Args:
            param1 (str): Description for parameter 1.
            param2 (int, optional): Description for parameter 2. Defaults to 42.

        Returns:
            bool: Description for return value.
        """
        return True

    app = FastDash(callback_fn=example_function, inputs=Text, outputs=Text).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#title8888928", "Example Function", timeout=4)

    # Click About
    dash_duo.multiple_click("#about-navlink", 1)
    time.sleep(2)

    # Grab the generated markdown text
    displayed_markdown = dash_duo.find_element("#about-modal-body").text

    assert "Example Function" in displayed_markdown, "Docstring absent in about (1)"
    assert (
        "Description for parameter 1." in displayed_markdown
    ), "Docstring absent in about (2)"


def test_fdfd013_about_button_false(dash_duo):
    "Test if about button is False"

    def example_function(param1, param2=42):
        """
        An example function for demonstration.

        Args:
            param1 (str): Description for parameter 1.
            param2 (int, optional): Description for parameter 2. Defaults to 42.

        Returns:
            bool: Description for return value.
        """
        return True

    app = FastDash(
        callback_fn=example_function, inputs=Text, outputs=Text, about=False
    ).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#title8888928", "Example Function", timeout=4)

    # Click About
    assert not dash_duo.find_elements(f"#about-navlink")


def test_fdfd014_about_button_custom(dash_duo):
    "Test the about button custom documentation"

    def example_function(param1, param2=42):
        """
        An example function for demonstration.

        Args:
            param1 (str): Description for parameter 1.
            param2 (int, optional): Description for parameter 2. Defaults to 42.

        Returns:
            bool: Description for return value.
        """
        return True

    # When about argument is custom text
    app = FastDash(
        callback_fn=example_function,
        inputs=Text,
        outputs=Text,
        about="Custom about section",
    ).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#title8888928", "Example Function", timeout=4)

    # Click About
    dash_duo.multiple_click("#about-navlink", 1)
    time.sleep(2)

    # Grab the generated markdown text
    displayed_markdown = dash_duo.find_element("#about-modal-body").text

    assert (
        "Custom about section" in displayed_markdown
    ), "Docstring mismatch in about (3)"


def test_fdfd015_close_sidebar(dash_duo):
    "Test closing the sidebar"

    app = FastDash(
        callback_fn=simple_text_to_text_function, inputs=Text, outputs=Text
    ).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal(
        "#title8888928", "Simple Text To Text Function", timeout=4
    )

    # Click sidebar toggle
    dash_duo.multiple_click("#sidebar-button", 1)
    time.sleep(2)

    # Find the style of the sidebar
    sidebar_style = dash_duo.find_element("#input-group").get_attribute("style")
    sidebar_style = dict(
        item.split(":") for item in sidebar_style.strip(";").split("; ") if item
    )
    assert sidebar_style["display"].strip() == "none", "Sidebar did not close"
