#!/usr/bin/env python
"""Tests for ``_friendly_error_message`` — the error string mapper.

When a user's callback raises, Fast Dash maps the raw Python exception
text to a friendlier message shown in the notification component.
This test exercises each branch end to end so that adding a new
error category doesn't silently break the existing ones.
"""
from fast_dash.utils import _friendly_error_message


def test_none_return_unpack():
    msg = _friendly_error_message(
        "'NoneType' object is not subscriptable"
    )
    assert "returned None" in msg


def test_too_many_values():
    msg = _friendly_error_message("too many values to unpack (expected 2)")
    assert "different number of values" in msg


def test_argument_mismatch():
    msg = _friendly_error_message(
        "my_func() takes 2 positional arguments but 3 were given"
    )
    assert "argument mismatch" in msg.lower()


def test_typeerror_unsupported_operand():
    msg = _friendly_error_message(
        "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
    )
    assert "Type mismatch" in msg


def test_keyerror():
    msg = _friendly_error_message("KeyError: 'missing_key'")
    assert "dictionary key" in msg.lower()


def test_value_conversion_error():
    msg = _friendly_error_message("ValueError: could not convert string to float: 'abc'")
    assert "couldn't be converted" in msg.lower()


def test_division_by_zero():
    msg = _friendly_error_message("ZeroDivisionError: division by zero")
    assert "Division by zero" in msg


def test_index_error():
    msg = _friendly_error_message("IndexError: list index out of range")
    assert "out of range" in msg.lower()


def test_json_serialization():
    msg = _friendly_error_message("Object of type set is not JSON serializable")
    assert "standard Python types" in msg


def test_timeout():
    msg = _friendly_error_message("TimeoutError: The read operation timed out")
    assert "timed out" in msg.lower()


def test_attribute_error():
    msg = _friendly_error_message("AttributeError: 'NoneType' object has no attribute 'x'")
    assert "missing an expected attribute" in msg


def test_file_not_found():
    msg = _friendly_error_message("FileNotFoundError: [Errno 2] No such file or directory: 'foo.csv'")
    assert "file could not be found" in msg


def test_permission_denied():
    msg = _friendly_error_message("PermissionError: [Errno 13] Permission denied: '/etc/secret'")
    assert "Permission denied" in msg


def test_no_module():
    msg = _friendly_error_message("ModuleNotFoundError: No module named 'pandas'")
    assert "Missing dependency" in msg
    assert "pandas" in msg


def test_connection_refused():
    msg = _friendly_error_message("ConnectionRefusedError: [Errno 61] Connection refused")
    assert "network connection failed" in msg.lower()


def test_memory_error():
    msg = _friendly_error_message("MemoryError")
    assert "out of memory" in msg.lower()


def test_chat_passthrough():
    """Chat-component formatting errors are already friendly; pass through verbatim."""
    msg = _friendly_error_message("Chat component requires a dict with 'query' and 'response'.")
    assert msg == "Chat component requires a dict with 'query' and 'response'."


def test_unknown_error_capitalized_fallback():
    msg = _friendly_error_message("some random new error")
    assert msg == "Some random new error"


def test_empty_error_fallback():
    msg = _friendly_error_message("")
    assert "unexpected error" in msg.lower()
