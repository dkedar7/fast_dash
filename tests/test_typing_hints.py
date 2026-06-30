#!/usr/bin/env python
"""Tests for modern Python typing hints support in fast_dash."""

from typing import Optional, Literal, Annotated, Union
from enum import Enum

from fast_dash import FastDash, dcc, dbc, dmc, html
from fast_dash.Components import Text


class Color(Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class Priority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


########### Literal type hints ###########


def test_literal_input():
    "Literal type hint should produce a Select dropdown"

    def func(choice: Literal["apple", "banana", "cherry"]) -> str:
        return choice

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.Select().__doc__, "Literal input should be a dmc.Select"
    assert comp.data == ["apple", "banana", "cherry"], "Literal options mismatch"
    assert comp.value == "apple", "Literal default should be first option"


def test_literal_with_numbers():
    "Literal with numeric values should stringify them"

    def func(level: Literal[1, 2, 3]) -> str:
        return str(level)

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.Select().__doc__, "Numeric Literal should be a dmc.Select"
    assert comp.data == ["1", "2", "3"], "Numeric Literal options should be strings"


def test_literal_output():
    "Literal return type should produce a text output, not a Select"

    def func(text: str) -> Literal["yes", "no"]:
        return "yes"

    app = FastDash(callback_fn=func)
    output_comp = app.outputs[0]
    assert output_comp.__doc__ == html.H1().__doc__, "Literal output should be text display"


########### Enum type hints ###########


def test_enum_input():
    "Enum type hint should produce a Select dropdown with member values"

    def func(color: Color) -> str:
        return color.value

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.Select().__doc__, "Enum input should be a dmc.Select"
    assert comp.data == ["red", "green", "blue"], "Enum options should be member values"


def test_enum_with_int_values():
    "Enum with integer values should stringify them"

    def func(priority: Priority) -> str:
        return priority.name

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.Select().__doc__, "Int Enum should be a dmc.Select"
    assert comp.data == ["1", "2", "3"], "Int Enum values should be strings"


def test_enum_output():
    "Enum return type should produce a text output"

    def func(text: str) -> Color:
        return Color.RED

    app = FastDash(callback_fn=func)
    output_comp = app.outputs[0]
    assert output_comp.__doc__ == html.H1().__doc__, "Enum output should be text display"


########### Optional type hints ###########


def test_optional_str_input():
    "Optional[str] should resolve to the same component as str"

    def func(text: Optional[str] = "hello") -> str:
        return text or ""

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.TextInput().__doc__, "Optional[str] should resolve to a TextInput"
    assert comp.value == "hello", "Optional[str] default value should be preserved"


def test_optional_int_input():
    "Optional[int] should resolve to the same component as int"

    def func(num: Optional[int] = 5) -> int:
        return num or 0

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.NumberInput().__doc__, "Optional[int] should resolve to a NumberInput"
    assert comp.value == 5, "Optional[int] default should be preserved"


def test_optional_output():
    "Optional[str] output should resolve the same as str"

    def func(text: str) -> Optional[str]:
        return text

    app = FastDash(callback_fn=func)
    output_comp = app.outputs[0]
    assert output_comp.__doc__ == html.H1().__doc__, "Optional[str] output should be text display"


########### Parameterized generic type hints ###########


def test_list_str_input():
    "list[str] should resolve to MultiSelect (same as list)"

    def func(items: list[str]) -> str:
        result = str(items)
        return result

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.MultiSelect().__doc__, "list[str] should be MultiSelect"


def test_list_str_with_default():
    "list[str] with a list default should populate options"

    def func(items: list[str] = ["a", "b", "c"]) -> str:
        result = str(items)
        return result

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.MultiSelect().__doc__, "list[str] with default should be MultiSelect"
    assert comp.data == ["a", "b", "c"], "list[str] default should populate data"


########### Annotated type hints ###########


def test_annotated_range_input():
    "Annotated[int, range(0, 100)] should produce a Slider"

    def func(value: Annotated[int, range(0, 100)]) -> int:
        return value

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.Slider().__doc__, "Annotated[int, range] should be a Slider"
    assert comp.min == 0, "Slider min should be 0"
    assert comp.max == 100, "Slider max should be 100"


def test_annotated_range_with_step():
    "Annotated[int, range(0, 100, 5)] should produce a Slider with step"

    def func(value: Annotated[int, range(0, 100, 5)]) -> int:
        return value

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.Slider().__doc__, "Annotated range with step should be Slider"
    assert comp.step == 5, "Slider step should be 5"


def test_annotated_list_options_input():
    "Annotated[str, ['opt1', 'opt2']] should produce a Select"

    def func(choice: Annotated[str, ["opt1", "opt2", "opt3"]]) -> str:
        return choice

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.Select().__doc__, "Annotated[str, list] should be a Select"
    assert comp.data == ["opt1", "opt2", "opt3"], "Annotated list options mismatch"


########### Union type hints ###########


def test_union_str_int_input():
    "Union[str, int] should resolve to the first non-None type (str)"

    def func(value: Union[str, int]) -> str:
        return str(value)

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.Textarea().__doc__ or comp.__doc__ == Text.__doc__, \
        "Union[str, int] should resolve to text component"


########### Backward compatibility ###########


def test_plain_str_still_works():
    "Plain str hint should still work as before"

    def func(text: str = "hello") -> str:
        return text

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.TextInput().__doc__, "Plain str should produce a TextInput"
    assert comp.value == "hello", "Plain str default should be preserved"


def test_plain_int_still_works():
    "Plain int hint should still work as before"

    def func(num: int = 5) -> int:
        return num

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.NumberInput().__doc__, "Plain int should produce a NumberInput"
    assert comp.value == 5, "Plain int default should be preserved"


def test_plain_bool_still_works():
    "Plain bool hint should still work as before"

    def func(flag: bool = True) -> str:
        return str(flag)

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    assert comp.__doc__ == dmc.Checkbox().__doc__, "Plain bool should produce a Checkbox"
    assert comp.checked is True, "Plain bool default should be preserved"


def test_no_type_hint_still_works():
    "Functions without type hints should still work"

    def func(text="hello"):
        return text

    app = FastDash(callback_fn=func)
    comp = app.inputs_with_ids[0]
    # No hint with str default falls through to default-value inference,
    # which produces a single-line TextInput.
    assert comp.__doc__ == dmc.TextInput().__doc__, "No hint with str default should produce a TextInput"


########### Combined / complex scenarios ###########


def test_mixed_modern_hints():
    "Function with multiple modern type hints should work together"

    def func(
        model: Literal["gpt-4", "claude", "gemini"],
        temperature: Annotated[float, range(0, 100)],
        text: Optional[str] = "Hello",
    ) -> str:
        return f"{model}: {text} @ {temperature}"

    app = FastDash(callback_fn=func)

    assert app.inputs_with_ids[0].__doc__ == dmc.Select().__doc__, "First input should be Select"
    assert app.inputs_with_ids[0].data == ["gpt-4", "claude", "gemini"], "Literal options wrong"

    assert app.inputs_with_ids[1].__doc__ == dmc.Slider().__doc__, "Second input should be Slider"

    assert app.inputs_with_ids[2].__doc__ == dmc.TextInput().__doc__, "Third input should be a TextInput"
    assert app.inputs_with_ids[2].value == "Hello", "Optional[str] default should be preserved"
