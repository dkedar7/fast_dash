from selenium.webdriver.chrome.options import Options
import os

def pytest_setup_options():
    options = Options()
    
    # Essential for GitHub Actions
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    
    # Window and display settings
    options.add_argument("--window-size=1280x1024")
    options.add_argument("--disable-web-security")
    options.add_argument("--allow-running-insecure-content")
    
    # WebSocket and network optimizations for CI
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-client-side-phishing-detection")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-features=TranslateUI")
    options.add_argument("--disable-hang-monitor")
    options.add_argument("--disable-ipc-flooding-protection")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-prompt-on-repost")
    options.add_argument("--disable-sync")
    options.add_argument("--force-color-profile=srgb")
    options.add_argument("--metrics-recording-only")
    options.add_argument("--no-first-run")
    options.add_argument("--safebrowsing-disable-auto-update")
    options.add_argument("--use-mock-keychain")
    
    # Specifically for WebSocket connections in CI
    options.add_argument("--enable-logging")
    options.add_argument("--log-level=0")
    options.add_argument("--remote-debugging-port=9222")
    
    # Remove the invalid pytest flag
    # options.add_argument("--disable-pytest-warnings")  # This was invalid
    
    return options

import pytest


@pytest.fixture(autouse=True)
def _reset_mcp_ownership():
    """Start every test with no MCP-enabled app owning the process.

    ``mcp_server=True`` mounts ``/mcp`` at construction (#244), and only one
    MCP-enabled app may own a process (#171) because Dash's tool registry is
    global. Without a reset, an app built by an earlier test -- kept alive by a
    reference cycle -- would own the process and make the next test's
    construction raise.
    """
    try:
        from dash.mcp import _decorator
        _decorator.MCP_DECORATED_FUNCTIONS.clear()
    except Exception:
        pass
    try:
        import fast_dash.mcp as _fd_mcp
        _fd_mcp._mcp_owner = None
    except Exception:
        pass
    yield
