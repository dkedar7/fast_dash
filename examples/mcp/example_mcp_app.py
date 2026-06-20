"""fast_dash app with the MCP surface enabled (Dash >= 4.3 native MCP).

Run::

    pip install fast-dash 'dash>=4.3'
    python examples/mcp/example_mcp_app.py

The MCP server shares the web app's port. Point any MCP-capable agent
(Claude Code, Cursor, Cline, ...) at::

    {"servers": {"chart-builder": {"url": "http://localhost:8080/mcp"}}}

What the agent gets:

* fast_dash tools (drive the live app):
    - ``set_input(component_id, value)`` — ``component_id`` is the parameter
      name itself (e.g. ``"n_categories"``, ``"color"``).
    - ``set_inputs({...})`` — bulk, e.g. ``{"n_categories": 8, "color": "#2f9e44"}``
    - ``invoke(inputs=None)`` — set values and run the callback in one call.
    - ``get_invocation(index)`` — full kwargs+result from history.
    - ``list_component_types()``
    - ``set_form(specs)`` — rejected (plain FastDash, not DynamicDash).
* Native Dash resources/tools (introspect the live app):
    - ``dash://layout`` / ``dash://components`` — the component tree.
    - ``get_dash_component`` — read a component's current props.

Web UI runs on http://127.0.0.1:8080.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from fast_dash import fastdash


@fastdash(mcp_server=True, port=8080)
def plot_bars(n_categories: int = 6, color: str = "#1c7ed6") -> go.Figure:
    """Plot a bar chart with N random-height bars in the chosen color.

    Args:
        n_categories: Number of bars (between 2 and 20).
        color: Hex color for the bars.
    """
    rng = np.random.default_rng(42)
    df = pd.DataFrame(
        {
            "category": [f"C{i}" for i in range(int(n_categories))],
            "value": rng.integers(10, 100, size=int(n_categories)),
        }
    )
    fig = px.bar(df, x="category", y="value", color_discrete_sequence=[color])
    fig.update_layout(
        title=f"Random bars ({n_categories} categories)",
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig
