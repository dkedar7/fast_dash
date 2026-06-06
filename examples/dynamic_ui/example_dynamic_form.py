"""Flavour A: a form whose shape is driven by a selector control.

The "Chart type" Select at the top reshapes the rest of the form into the
controls appropriate for that chart kind. Hit Run and you get a Plotly figure
built from the current spec.

Run::

    python examples/dynamic_ui/example_dynamic_form.py
"""

import numpy as np
import pandas as pd
import plotly.express as px

from fast_dash import DynamicDash, Graph


CHART_TYPES = ["bar", "scatter", "histogram"]


def spec_for(chart_type: str) -> list[dict]:
    """Map the selected chart type to the inputs that chart needs."""
    if chart_type == "bar":
        return [
            {
                "name": "n_categories",
                "type": "Slider",
                "label": "Number of categories",
                "value": 6,
                "props": {"min": 2, "max": 20, "step": 1},
            },
            {
                "name": "color",
                "type": "ColorInput",
                "label": "Bar color",
                "value": "#1c7ed6",
            },
        ]
    if chart_type == "scatter":
        return [
            {
                "name": "n_points",
                "type": "Slider",
                "label": "Number of points",
                "value": 100,
                "props": {"min": 10, "max": 1000, "step": 10},
            },
            {
                "name": "noise",
                "type": "Slider",
                "label": "Noise",
                "value": 0.5,
                "props": {"min": 0, "max": 2, "step": 0.05},
            },
            {
                "name": "color",
                "type": "ColorInput",
                "label": "Point color",
                "value": "#fa5252",
            },
        ]
    if chart_type == "histogram":
        return [
            {
                "name": "n_samples",
                "type": "Slider",
                "label": "Sample size",
                "value": 500,
                "props": {"min": 50, "max": 5000, "step": 50},
            },
            {
                "name": "n_bins",
                "type": "Slider",
                "label": "Number of bins",
                "value": 30,
                "props": {"min": 5, "max": 100, "step": 1},
            },
            {
                "name": "color",
                "type": "ColorInput",
                "label": "Bar color",
                "value": "#37b24d",
            },
        ]
    return []


def plot(
    chart_type: str = "bar",
    n_categories: int = 6,
    n_points: int = 100,
    noise: float = 0.5,
    n_samples: int = 500,
    n_bins: int = 30,
    color: str = "#1c7ed6",
):
    """Build a figure based on the dynamic form's current values."""
    rng = np.random.default_rng(42)

    if chart_type == "bar":
        df = pd.DataFrame(
            {
                "category": [f"C{i}" for i in range(int(n_categories))],
                "value": rng.integers(10, 100, size=int(n_categories)),
            }
        )
        fig = px.bar(df, x="category", y="value", color_discrete_sequence=[color])
    elif chart_type == "scatter":
        n = int(n_points)
        x = rng.normal(0, 1, n)
        y = 2 * x + rng.normal(0, noise, n)
        fig = px.scatter(x=x, y=y, color_discrete_sequence=[color])
    elif chart_type == "histogram":
        samples = rng.normal(0, 1, int(n_samples))
        fig = px.histogram(samples, nbins=int(n_bins), color_discrete_sequence=[color])
    else:
        fig = px.scatter(x=[0], y=[0])

    fig.update_layout(
        title=f"{chart_type.title()} chart",
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


app = DynamicDash(
    callback_fn=plot,
    parent_control={
        "name": "chart_type",
        "type": "Select",
        "label": "Chart type",
        "value": "bar",
        "props": {"data": CHART_TYPES, "allowDeselect": False},
    },
    spec_resolver=spec_for,
    output_components=[Graph],
    title="Dynamic form — chart builder",
)


if __name__ == "__main__":
    app.run(debug=True, port=8051)
