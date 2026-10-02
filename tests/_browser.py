"""Selenium helpers shared by the browser tests.

The Run button is disabled while a callback is in flight (``running=`` on the
main callback), and on a slow runner the page-load callbacks are still in flight
when a test clicks Run -- the click lands on a disabled button and is silently
dropped, so no request ever reaches the server and the output stays empty
(issue #250: a different browser test failed on macOS CI almost every run).
Click only once the page is idle and the typed value has landed.
"""
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


def click_run(dash_duo, typed=None, input_selector=None, timeout=20):
    """Click Run once the app is ready to accept it.

    Pass ``typed`` / ``input_selector`` after ``send_keys`` so the click also
    waits for the value to reach the input.
    """
    wait = WebDriverWait(dash_duo.driver, timeout)
    if typed is not None and input_selector is not None:
        wait.until(
            lambda d: d.find_element(By.CSS_SELECTOR, input_selector)
            .get_attribute("value") == typed
        )
    wait.until(lambda d: dash_duo._wait_for_callbacks())
    wait.until(
        lambda d: d.find_element(By.CSS_SELECTOR, "#submit_inputs").is_enabled()
    )
    dash_duo.find_element("#submit_inputs").click()


def wait_for_text_in(dash_duo, selector, text, timeout=20):
    """Wait until ``text`` appears anywhere inside ``selector``."""
    WebDriverWait(dash_duo.driver, timeout).until(
        lambda d: text in d.find_element(By.CSS_SELECTOR, selector).text
    )
