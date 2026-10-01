# Drive your app with AI agents (MCP)

*New in 0.3.0.*

Pass `mcp_server=True` and your Fast Dash app serves a web UI **and** a
[Model Context Protocol](https://modelcontextprotocol.io) (MCP) server, so any
MCP-capable agent — Claude Code, Cursor, Cline, … — can inspect and drive it.
The same type hints that build the UI describe what an agent sees via the
[`describe_app`](#discover-the-contract) tool: every input (id, type, default,
allowed options, current value) and every output the app produces.

The MCP server is built on [Dash's native MCP support](https://dash.plotly.com)
(Dash ≥ 4.3, installed automatically) and is mounted on the **same port** as the
web app, at `/mcp`.

```python
from fast_dash import fastdash
import plotly.graph_objects as go

@fastdash(mcp_server=True)            # web UI AND MCP on :8080/mcp
def plot_bars(n: int = 6, color: str = "#1c7ed6") -> go.Figure:
    """Plot a bar chart with n bars in the chosen color."""
    bars = go.Figure(go.Bar(y=list(range(1, n + 1)), marker_color=color))
    return bars
```

## Connect an agent

The endpoint is `http://localhost:8080/mcp`, served over MCP's streamable HTTP
transport. Each client names its config key differently:

**Claude Code**: run `claude mcp add --transport http my-app http://localhost:8080/mcp`,
or add it to the project's `.mcp.json`:

```json
{"mcpServers": {"my-app": {"type": "http", "url": "http://localhost:8080/mcp"}}}
```

**Cursor**: in `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global):

```json
{"mcpServers": {"my-app": {"url": "http://localhost:8080/mcp"}}}
```

**VS Code**: in `.vscode/mcp.json`:

```json
{"servers": {"my-app": {"type": "http", "url": "http://localhost:8080/mcp"}}}
```

!!! tip "Checking that MCP is up"
    Opening `/mcp` in a browser (or with `curl`) shows the app's web page, not
    an MCP response, so it can't tell you whether the server is running.
    Connect with an MCP client instead, such as the
    [Python example below](#drive-it-from-python).

## What the agent gets

| Surface | Provided by | Use |
|---|---|---|
| `describe_app()` | Fast Dash | **Start here.** The full contract + current state: each input's id, type, default, options and current value, and each output the app produces |
| `set_input(component_id, value)` | Fast Dash | Set one input |
| `set_inputs(inputs)` | Fast Dash | Set several inputs at once (`inputs` is a `{id: value}` dict) |
| `invoke(inputs=None)` | Fast Dash | Run the callback (optionally setting inputs first), in one call |
| `set_form(specs)` | Fast Dash | Generate a form at runtime (`DynamicDash` only) |
| `get_invocation(index)` | Fast Dash | Fetch a past run's full kwargs + result |
| `list_component_types()` | Fast Dash | List the legal component types for `set_form` |
| `dash://layout`, `dash://components`, `get_dash_component` | Dash (native) | Read the static component tree (ids + Dash widget types) |

`component_id` is the **parameter name** itself (e.g. `"n"`, `"color"`).

### Discover the contract

Call **`describe_app()`** to learn the exact input ids, their Python types,
defaults, allowed options and **current values**, plus what a run produces — and
use that to build a valid `invoke` call:

```json
{
  "title": "Plot Bars",
  "doc": "Plot a bar chart with n bars in the chosen color.",
  "inputs": [
    {"id": "n",     "tag": "NumberInput", "type": "integer", "default": 6,        "options": null, "current_value": 6,         "secret": false, "required": false},
    {"id": "color", "tag": "ColorInput", "type": "string",  "default": "#1c7ed6", "options": null, "current_value": "#1c7ed6", "secret": false, "required": false}
  ],
  "outputs": [
    {"id": "output_bars", "tag": "Graph", "type": "object", "label": "BARS"}
  ]
}
```

`required: true` marks a parameter with no default: `invoke` refuses to run
without it and names what's missing. An output's `id` comes from the variable
the function returns (`return bars` gives `output_bars`); a function that
returns an expression gets `output_output_1`, `output_output_2`, and so on. `tag` is the widget the hint became — a `str` input can be a text box, a
textarea or a colour picker, and they are not interchangeable. `outputs` lets an
agent see what a run returns **without** having to run it.

### The contract is enforced

Whatever `describe_app()` advertises is what `set_input` / `set_inputs` /
`invoke` accept — an agent cannot set a value the UI itself could never produce.
A value outside a dropdown's `options`, outside a Slider's `min`/`max`, or of the
wrong type (a string for a number, a string for a switch) is rejected with an
error naming the constraint, and `invoke` is atomic: one bad value rejects the
whole call without mutating anything. The same holds for a form an agent builds
at runtime with `set_form` — the specs it declared become the contract it is
then held to.

!!! warning "Secrets"
    A `PasswordInput`'s value is **never reported back** over MCP: the contract
    marks it `"secret": true` and masks it everywhere (`describe_app`, the
    `set_input` echo, `get_invocation`). An agent can fill the field; it cannot
    read it. A `PasswordInput` **default** (say, a key pre-filled from config)
    never leaves the server either: the served page and Dash's native
    `dash://layout` / `get_dash_component` carry only `********`, and the real
    value is swapped back in when the callback runs.

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
invoke(inputs={"n": 12, "color": "#2f9e44"})
```

Agent mutations are reflected in the **live browser** within ~500 ms (no
reload), so a human watching the page sees what the agent does.

## Drive it from Python

To script an app, or test your own agent-driven app, connect with the official
[`mcp`](https://pypi.org/project/mcp/) SDK. It is installed with Fast Dash.
Start the app above, then run:

```python
import json

import anyio
from mcp import ClientSession

try:
    from mcp.client.streamable_http import streamable_http_client
except ImportError:  # older mcp releases spell it streamablehttp_client
    from mcp.client.streamable_http import streamablehttp_client as streamable_http_client

URL = "http://127.0.0.1:8080/mcp"


async def call(session, tool, args=None):
    """Call a Fast Dash tool and return its JSON result."""
    result = await session.call_tool(tool, args or {})
    return json.loads(result.content[0].text)


async def main():
    async with streamable_http_client(URL) as (read, write, *_):
        async with ClientSession(read, write) as session:
            await session.initialize()

            app = await call(session, "describe_app")
            print([i["id"] for i in app["inputs"]])          # ['n', 'color']

            run = await call(session, "invoke", {"inputs": {"n": 12, "color": "#2f9e44"}})
            print(run["ok"], run["history_index"])           # True 0

            past = await call(session, "get_invocation", {"index": run["history_index"]})
            print(past["kwargs_summary"])                    # {'n': 12, 'color': '#2f9e44'}


anyio.run(main)
```

Every tool takes keyword arguments named as in the table above:
`set_input(component_id, value)`, `set_inputs(inputs)`, `invoke(inputs)`,
`set_form(specs)` and `get_invocation(index)`. `describe_app` and
`list_component_types` take none.

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
app.run(port=8052)                    # MCP is served at :8052/mcp
```

The agent then calls, for example:

```python
set_form(specs=[
    {"name": "communication", "type": "Slider", "props": {"min": 0, "max": 10}},
    {"name": "technical",     "type": "Slider", "props": {"min": 0, "max": 10}},
])
```

After `set_form`, **`describe_app()` reflects the materialized form** — each field's
`id`, `type`, `default`, `options`, and `props` (e.g. a slider's `min`/`max`) plus
its current value — so a reconnecting (or second) agent can discover and drive the
form without remembering the spec it sent. From there, `set_inputs(...)` + `invoke()`
run it, validated against the very specs the form was built from: a value outside
that slider's `0..10` is rejected exactly as it would be on a static app.

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
    auth before exposing it. Serving on a non-loopback host (e.g.
    `run_kwargs={"host": "0.0.0.0"}`) with `mcp_server=True` raises a warning.

- **One MCP-enabled app per process** (Dash's tool registry is process-global).
- **Multi-function and steps modes** skip the MCP surface.
- Chat *append* on the native-WebSocket streaming path is not yet ported (it
  replaces rather than appends).
