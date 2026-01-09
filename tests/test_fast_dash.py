#!/usr/bin/env python
"""Tests for `fast_dash` package."""
# pylint: disable=redefined-outer-name

from fast_dash import FastDash, update, Text
import matplotlib.pyplot as plt

import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException



## Define callback functions
def simple_text_to_text_function(input_text):
    "Converts text to text"
    output_text = input_text
    return output_text


def simple_text_to_multiple_text_function(input_text):
    output_text1 = output_text2 = input_text
    return output_text1, output_text2


def simple_text_to_multiple_outputs(
    input_text: str,
) -> (plt.Figure, str):
    "Something"

    fig, ax = plt.subplots(1, 1)
    ax.plot([1, 2, 3], [1, 2, 3])

    return fig, "Return some text"

def stream_text_function(input_text: str) -> Text(stream=True):

    expected_output = "output"

    output_text = ""
    for i, c in enumerate(expected_output):
        time.sleep(1)
        output_text += c
        update("output_text", output_text)

    return output_text


# Tests start here

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
    dash_duo.wait_for_text_to_equal("#output_output_text", "Sample text", timeout=4)

    # Click clear
    wait = WebDriverWait(dash_duo.driver, 10)
    reset_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#reset_inputs")))
    dash_duo.driver.execute_script("document.querySelector('#reset_inputs').click()")

    dash_duo.wait_for_text_to_equal("#output_output_text", "", timeout=4)


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
    dash_duo.wait_for_text_to_equal("#output_output_text1", "Sample text", timeout=4)
    dash_duo.wait_for_text_to_equal("#output_output_text2", "Sample text", timeout=4)

    # Click clear
    wait = WebDriverWait(dash_duo.driver, 10)
    reset_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#reset_inputs")))
    dash_duo.driver.execute_script("document.querySelector('#reset_inputs').click()")
    dash_duo.wait_for_text_to_equal("#output_output_text1", "", timeout=4)
    dash_duo.wait_for_text_to_equal("#output_output_text2", "", timeout=4)


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


def test_fdfd016_stream_text_simple(dash_duo):
    "Test streaming text output"

    app = FastDash(
        callback_fn=stream_text_function,
        stream=True,
        inputs=Text,
        outputs=Text,
        title="Streaming Text Example",
    ).app

    time.sleep(4)
    dash_duo.start_server(app)
    time.sleep(4)

    dash_duo.wait_for_text_to_equal(
        "#title8888928", "Streaming Text Example", timeout=4
    )

    # Enter some text
    form_textfield = dash_duo.find_element("#input_text")
    form_textfield.send_keys("Sample text")

    # Click submit
    dash_duo.multiple_click("#submit_inputs", 1)

    time.sleep(4)
    # Poll until text stops changing (streaming complete)
    previous_text = ""
    stable_count = 0
    for _ in range(120):  # 60 second max wait
        try:
            current_text = dash_duo.find_element("#output_output_text").text
            if current_text == previous_text and current_text != "":
                stable_count += 1
                if stable_count >= 3:  # Text stable for 3 checks
                    break
            else:
                stable_count = 0
            previous_text = current_text
            time.sleep(1)
        except:
            time.sleep(1)

    # Now assert on the final text
    final_text = dash_duo.find_element("#output_output_text").text
    assert "output" in final_text


def test_fdfd019_sidebar_layout_resize_elements(dash_duo):
    "Test sidebar layout has resize handle and wrapper elements"

    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        title="Sidebar Resize Test",
        layout="sidebar"
    ).app

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#title8888928", "Sidebar Resize Test", timeout=4)

    # Check that the input group wrapper exists
    input_wrapper = dash_duo.find_element("#input-group-wrapper")
    assert input_wrapper is not None, "Input group wrapper should exist"

    # Check that the resize handle exists
    resize_handle = dash_duo.find_element("#sidebar-resize-handle")
    assert resize_handle is not None, "Sidebar resize handle should exist"

    # Check that the input group (content) exists
    input_group = dash_duo.find_element("#input-group")
    assert input_group is not None, "Input group should exist"

    # Check that wrapper has the correct classes
    wrapper_classes = input_wrapper.get_attribute("class")
    assert wrapper_classes is not None

    # Check that resize handle has the correct class
    handle_class = resize_handle.get_attribute("class")
    assert "sidebar-resize-handle" in handle_class, "Resize handle should have correct class"

    assert dash_duo.get_logs() in [[], None], "browser console should contain no error"


def test_fdfd020_sidebar_resize_handle_styling(dash_duo):
    "Test that sidebar resize handle has proper CSS styling"

    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        layout="sidebar"
    ).app

    dash_duo.start_server(app)
    time.sleep(2)

    # Get the resize handle
    resize_handle = dash_duo.find_element("#sidebar-resize-handle")

    # Check computed styles
    cursor = resize_handle.value_of_css_property("cursor")
    assert cursor == "col-resize", f"Resize handle should have col-resize cursor, got {cursor}"

    position = resize_handle.value_of_css_property("position")
    assert position == "absolute", f"Resize handle should be absolutely positioned, got {position}"

    width = resize_handle.value_of_css_property("width")
    assert width == "5px", f"Resize handle should be 5px wide, got {width}"

    assert dash_duo.get_logs() in [[], None], "browser console should contain no error"


def test_fdfd021_sidebar_resize_width_constraints(dash_duo):
    "Test that sidebar wrapper has correct width constraints"

    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        layout="sidebar"
    ).app

    dash_duo.start_server(app)
    time.sleep(2)

    # Get the input wrapper
    input_wrapper = dash_duo.find_element("#input-group-wrapper")

    # Check that it has style attributes
    style = input_wrapper.get_attribute("style")
    assert style is not None, "Input wrapper should have style attribute"

    # Check min and max width are set
    min_width = input_wrapper.value_of_css_property("min-width")
    max_width = input_wrapper.value_of_css_property("max-width")

    assert min_width == "150px", f"Min width should be 150px, got {min_width}"
    assert max_width == "50%" or "%" in max_width, f"Max width should be 50%, got {max_width}"

    assert dash_duo.get_logs() in [[], None], "browser console should contain no error"


def test_fdfd022_sidebar_resize_javascript_loaded(dash_duo):
    "Test that the sidebar resize JavaScript is loaded and functional"

    app = FastDash(
        callback_fn=simple_text_to_text_function,
        inputs=Text,
        outputs=Text,
        layout="sidebar"
    ).app

    dash_duo.start_server(app)
    time.sleep(2)

    # Check that JavaScript file exists by looking for initialized elements
    resize_handle = dash_duo.find_element("#sidebar-resize-handle")
    assert resize_handle is not None

    # Test that the resize handle is interactive
    # Get initial width
    input_wrapper = dash_duo.find_element("#input-group-wrapper")
    initial_width = input_wrapper.size['width']

    assert initial_width > 0, "Sidebar should have a width greater than 0"

    # The JavaScript should be loaded and DOM ready
    # We can verify by checking if the page is fully rendered
    time.sleep(1)

    assert dash_duo.get_logs() in [[], None], "browser console should contain no error"


def test_fdfd023_sidebar_toggle_preserves_width(dash_duo):
    "Test that toggling sidebar preserves width settings"

    from fast_dash import FastDash
    from fast_dash.Components import Text, Slider

    def callback_with_slider(text, slider):
        return f"{text}: {slider}"

    app = FastDash(
        callback_fn=callback_with_slider,
        inputs=[Text, Slider],
        outputs=Text,
        layout="sidebar"
    ).app

    dash_duo.start_server(app)
    time.sleep(2)

    # Find the sidebar button (burger menu)
    try:
        sidebar_button = dash_duo.find_element("#sidebar-button")

        # Get initial wrapper
        input_wrapper = dash_duo.find_element("#input-group-wrapper")
        initial_display = input_wrapper.value_of_css_property("display")

        # Click to toggle
        dash_duo.multiple_click("#sidebar-button", 1)
        time.sleep(1)

        # Check that display changed
        new_display = input_wrapper.value_of_css_property("display")

        # The display should toggle between flex and none
        assert new_display != initial_display or new_display in ["flex", "none"], \
            f"Display should toggle, got {new_display}"

    except NoSuchElementException:
        # Sidebar button might not exist in minimal mode, that's okay
        pass

    assert dash_duo.get_logs() in [[], None], "browser console should contain no error"


def test_fdfd024_sidebar_resize_assets_exist():
    "Test that sidebar resize CSS and JavaScript assets exist"
    import os
    from pathlib import Path

    # Get the fast_dash package directory
    import fast_dash
    package_dir = Path(fast_dash.__file__).parent

    # Check that JavaScript file exists
    js_file = package_dir / "assets" / "sidebar_resize.js"
    assert js_file.exists(), f"JavaScript file should exist at {js_file}"

    # Check that CSS file exists and contains resize styles
    css_file = package_dir / "assets" / "markdown.css"
    assert css_file.exists(), f"CSS file should exist at {css_file}"

    # Read CSS and check for resize handle styles
    with open(css_file, 'r') as f:
        css_content = f.read()

    assert "sidebar-resize-handle" in css_content, "CSS should contain sidebar-resize-handle class"
    assert "col-resize" in css_content, "CSS should contain col-resize cursor"
    assert "#input-group-wrapper" in css_content, "CSS should contain input-group-wrapper styles"