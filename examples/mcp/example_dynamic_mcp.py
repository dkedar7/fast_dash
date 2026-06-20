"""DynamicDash + MCP — the form materializes from an agent's set_form call.

Run::

    pip install -e '.[mcp]'
    python examples/mcp/example_dynamic_mcp.py

Then any MCP client (http://localhost:8002/mcp) can call::

    set_form(specs=[
        {"name": "communication", "type": "Slider", "props": {"min":0, "max":10}},
        {"name": "technical",     "type": "Slider", "props": {"min":0, "max":10}},
        ...
    ])

and the form re-renders live in the browser within ~500ms.
"""

import plotly.graph_objects as go

from fast_dash import DynamicDash, Graph, Markdown


def score(**candidate_scores):
    """Render a radar chart of whatever numeric fields were sent."""
    numeric = {
        k: float(v)
        for k, v in candidate_scores.items()
        if isinstance(v, (int, float)) and v is not None
    }
    if not numeric:
        return (
            go.Figure().update_layout(title="No numeric fields yet"),
            "**Form not yet generated.** Ask the connected agent to call `set_form`.",
        )

    labels = list(numeric.keys())
    values = list(numeric.values())
    labels_c = labels + [labels[0]]
    values_c = values + [values[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(r=values_c, theta=labels_c, fill="toself", name="Candidate")
    )
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True)),
        showlegend=False,
        title="Candidate radar",
        margin=dict(l=40, r=40, t=60, b=40),
    )

    bullets = "\n".join(f"- **{k}**: {v}" for k, v in candidate_scores.items())
    return fig, f"### Submitted values\n{bullets}"


app = DynamicDash(
    callback_fn=score,
    placeholder=(
        "Form not generated yet. Tell the connected agent to call "
        "`set_form(...)` — the form will appear here within ~500ms."
    ),
    output_components=[Graph, Markdown],
    title="Dynamic MCP — candidate scorer",
    mcp_server=True,
    mcp_port=8002,
)


if __name__ == "__main__":
    # mcp_server=True means run() starts the MCP server automatically —
    # same one-call contract as FastDash. No manual serve_mcp_in_thread.
    app.run(debug=False, port=8052)
