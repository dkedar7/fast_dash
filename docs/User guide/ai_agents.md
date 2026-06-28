# Drive your app with AI agents (MCP)

*New in 0.3.0.*

Pass `mcp_server=True` and your Fast Dash app serves a web UI **and** a
[Model Context Protocol](https://modelcontextprotocol.io) (MCP) server, so any
MCP-capable agent — Claude Code, Cursor, Cline, … — can inspect and drive it.
The same type hints that build the UI describe the inputs an agent sees via the
[`describe_app`](#discover-the-input-contract) tool (id, type, default, allowed
options, and current value).

The MCP server is built on [Dash's native MCP support](https://dash.plotly.com)
(Dash ≥ 4.3, installed automatically) and is mounted on the **same port** as the
web app, at `/mcp`.

```python
from fast_dash import fastdash
import plotly.graph_objects as go

@fastdash(mcp_server=True)            # web UI AND MCP on :8080/mcp
def plot_bars(n: int = 6, color: str = "#1c7ed6") -> go.Figure:
    """Plot a bar chart with n bars in the chosen color."""
    ...
```

## Connect an agent

Point any MCP client at the app's `/mcp` endpoint (streamable HTTP):

```json
{"servers": {"my-app": {"url": "http://localhost:8080/mcp"}}}
```

## What the agent gets

| Surface | Provided by | Use |
|---|---|---|
| `describe_app()` | Fast Dash | **Start here.** The input contract + current state: each input's id, type, default, options, and current value |
| `set_input(component_id, value)` | Fast Dash | Set one input |
| `set_inputs(inputs)` | Fast Dash | Set several inputs at once (`inputs` is a `{id: value}` dict) |
| `invoke(inputs=None)` | Fast Dash | Run the callback (optionally setting inputs first), in one call |
| `set_form(specs)` | Fast Dash | Generate a form at runtime (`DynamicDash` only) |
| `get_invocation(index)` | Fast Dash | Fetch a past run's full kwargs + result |
| `list_component_types()` | Fast Dash | List the legal component types for `set_form` |
| `dash://layout`, `dash://components`, `get_dash_component` | Dash (native) | Read the static component tree (ids + Dash widget types) |

`component_id` is the **parameter name** itself (e.g. `"n"`, `"color"`).

### Discover the input contract

Call **`describe_app()`** to learn the exact input ids, their Python types,
defaults, allowed options, and **current values** — and use that to build a valid
`invoke` call:

```json
{
  "title": "Plot Bars",
  "doc": "Plot a bar chart with n bars in the chosen color.",
  "inputs": [
    {"id": "n",     "type": "integer", "default": 6,         "options": null, "current_value": 6},
    {"id": "color", "type": "string",  "default": "#1c7ed6", "options": null, "current_value": "#1c7ed6"}
  ]
}
```

!!! note
    The drive tools' (`invoke` / `set_inputs` / `set_input`) raw MCP *input
    schemas* are generic objects — the per-parameter contract lives in
    `describe_app()`, not in those tool schemas. The native `dash://components`
    resource lists ids and Dash *widget* types only, and `get_dash_component`
    reflects the **browser**, so for a headless agent neither shows values an
    agent set via `set_input`/`set_inputs` — use `describe_app()` for current
    values.

## Drive it from the agent

```python
# From the agent's side — set inputs and run in a single round-trip:
invoke({"n": 12, "color": "#2f9e44"})
```

Agent mutations are reflected in the **live browser** within ~500 ms (no
reload), so a human watching the page sees what the agent does.

## Agent-generated UIs with DynamicDash

`DynamicDash` is a Fast Dash app whose input form is generated at runtime —
either by a parent control or by an agent calling the `set_form` tool. The form
materializes in the browser within ~500 ms of the call.

```python
from fast_dash import DynamicDash, Graph, Markdown

def score(**candidate_scores):
    """Render a radar chart of whatever numeric fields were sent."""
    ...

app = DynamicDash(
    callback_fn=score,
    placeholder="Ask the agent to call set_form() to build the form.",
    output_components=[Graph, Markdown],
    mcp_server=True,
)
app.run(port=8052)                    # run() mounts the MCP server on :8052/mcp
```

The agent then calls, for example:

```python
set_form([
    {"name": "communication", "type": "Slider", "props": {"min": 0, "max": 10}},
    {"name": "technical",     "type": "Slider", "props": {"min": 0, "max": 10}},
])
```

After `set_form`, **`describe_app()` reflects the materialized form** — each field's
`id`, `type`, `default`, `options`, and `props` (e.g. a slider's `min`/`max`) plus
its current value — so a reconnecting (or second) agent can discover and drive the
form without remembering the spec it sent. From there, `set_inputs(...)` + `invoke()`
run it.

## Real-time push (opt-in)

On the default Flask backend, agent mutations reach the browser via a ~500 ms
polling drain. Install the `fastapi` extra and pass `backend="fastapi"` to run
on Dash's ASGI backend, where updates stream over a WebSocket with `set_props`
(sub-100 ms, no polling):

<div class="termy">

``` console
$ pip install 'fast-dash[fastapi]'
```

</div>

```python
@fastdash(mcp_server=True, backend="fastapi")   # real-time WebSocket push
def plot_bars(n: int = 6) -> go.Figure:
    ...
```

The same ASGI backend also powers native-WebSocket **streaming** for
`stream=True` apps (no `flask-socketio`); on the default Flask backend,
`stream=True` continues to use `flask-socketio` unchanged.

## Security & limitations

!!! warning
    The MCP route shares the web app's host/port and has **no authentication** —
    anyone who can reach it can drive your callback. Keep it bound to
    `127.0.0.1` (the default) during development, and put it behind your own
    auth before exposing it.

- **One MCP-enabled app per process** (Dash's tool registry is process-global).
- **Multi-function and steps modes** skip the MCP surface.
- Chat *append* on the native-WebSocket streaming path is not yet ported (it
  replaces rather than appends).
