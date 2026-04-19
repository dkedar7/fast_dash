#!/usr/bin/env python
"""Unit tests for string-form type annotations in output inference.

Ensures that returning a function with a string annotation like
``"plotly.graph_objects.Figure"`` still produces the right FastComponent,
rather than falling through to the generic text renderer.
"""
from fast_dash.Components import _get_output_components


def test_plotly_graph_objects_figure_string():
    comp = _get_output_components("plotly.graph_objects.Figure")
    assert comp.tag == "Graph"
    assert comp.component_property == "figure"


def test_plotly_graph_objs_figure_string():
    comp = _get_output_components("plotly.graph_objs.Figure")
    assert comp.tag == "Graph"
    assert comp.component_property == "figure"


def test_go_figure_string():
    comp = _get_output_components("go.Figure")
    assert comp.tag == "Graph"
    assert comp.component_property == "figure"


def test_bare_figure_string():
    comp = _get_output_components("Figure")
    assert comp.tag == "Graph"
    assert comp.component_property == "figure"


def test_dataframe_string_annotations_resolve_to_table():
    import pandas as pd
    for s in ("pd.DataFrame", "DataFrame", "pandas.DataFrame"):
        comp = _get_output_components(s)
        # These fall into the normal issubclass(pd.DataFrame) branch → Table
        # The Table FastComponent wraps a DataTable
        assert "DataTable" in comp.component.__class__.__name__, f"got {comp.component.__class__} for {s}"


def test_image_string_annotations_resolve_to_image():
    import PIL.Image
    for s in ("PIL.Image.Image", "Image"):
        comp = _get_output_components(s)
        # Falls into issubclass(PIL.Image.Image) branch → Image component
        assert comp.component.__class__.__name__ == "Img", f"got {comp.component.__class__} for {s}"


def test_unknown_string_annotation_falls_back_to_text():
    """Strings we don't recognize should still produce a valid output component."""
    comp = _get_output_components("SomeRandomType")
    # Falls through the string-resolution block; ends up as H1 (text fallback)
    assert comp.component.__class__.__name__ == "H1"
