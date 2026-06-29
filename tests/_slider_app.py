"""Helper callback for the #120 Slider-bounds test.

Deliberately has **no** ``from __future__ import annotations`` so the documented
slider type hints resolve to real ``range`` / ``Annotated`` objects at
inference time — i.e. the exact way a user's plain script (the issue's repro)
builds the app. (Defining it inside the future-annotations ``test_mcp`` module
would stringify the annotations and degrade the widget; that's the separate
issue #119.)
"""

from typing import Annotated


def slider_demo(
    via_annot: Annotated[int, range(0, 100)] = 30,   # Annotated[int, range] -> Slider
    via_range: int = range(0, 100),                  # int with range() default -> Slider
    plain_num: int = 5,                              # int -> NumberInput (unbounded)
) -> str:
    """Echo the three numeric inputs."""
    return f"{via_annot} {via_range} {plain_num}"
