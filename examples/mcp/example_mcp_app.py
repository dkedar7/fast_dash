"""fast_dash app with the full MCP surface enabled.

Run::

    pip install -e '.[mcp]'
    python examples/mcp/example_mcp_app.py

Then point any MCP-capable agent (Claude Code, Cursor, Cline, ...) at::

    {"servers": {"chart-builder": {"url": "http://localhost:8001/mcp"}}}

What the agent gets:

* Tool ``plot_bars(n_categories, color)`` — call the function directly
* Tool ``set_input(component_id, value)`` — mirror one input value.
  ``component_id`` is the *parameter name* itself (e.g. ``"n_categories"``,
  ``"color"``) — not an ``input_``-prefixed id. Read ``fastdash://app/inputs``
  to list the exact ids and their current values.
* Tool ``set_inputs({...})`` — bulk, e.g. ``{"n_categories": 8, "color": "#2f9e44"}``
* Tool ``invoke()`` — run callback with current mirror, returns output summary
* Tool ``screenshot()`` — server-side PNG of the current Plotly figure (needs kaleido)
* Tool ``get_invocation(index)`` — full kwargs+result from history
* Tool ``list_component_types()``
* Tool ``set_form(specs)`` — rejected (this is a plain FastDash, not DynamicDash)
* Resource ``fastdash://app`` — title, signature, mode
* Resource ``fastdash://app/inputs`` — input panel mirror
* Resource ``fastdash://app/outputs`` — last computed outputs
* Resource ``fastdash://app/layout`` — full component tree
* Resource ``fastdash://app/history`` — last 20 invocations (summaries)

Web UI runs on http://127.0.0.1:8080 as usual.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from fast_dash import fastdash


@fastdash(mcp_server=True, port=8080, mcp_port=8001)
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
