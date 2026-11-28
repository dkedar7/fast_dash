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
    A plain `GET /mcp` answers with MCP's event stream (`text/event-stream`,
    body `: mcp stream open`) when the MCP server is mounted, and with the
    app's web page when it isn't. That makes a one-line readiness check for a
    container health check or CI:

    ```bash
    curl -fsS http://127.0.0.1:8080/mcp | grep -q "mcp stream open" && echo "MCP is up"
    ```

    Check `/mcp` itself: other paths under it, such as `/mcp/health`, return
    the web page even when MCP is running.

    To check what an agent will actually see, run `fastdash doctor --mcp`
    against the running app. It connects as a real MCP client (it needs
    `pip install mcp`), initializes, lists the tools and resources, and reads
    `describe_app`:

    ```console
    $ fastdash doctor --mcp http://127.0.0.1:8080/mcp
    Connecting to http://127.0.0.1:8080/mcp (streamable HTTP) ...
      initialize       OK   protocol 2025-11-25, server Plotly Dash 4.5.0
      list_tools       OK   get_dash_component, set_input, set_inputs, invoke, ...
      list_resources   OK   dash://layout, dash://components
      describe_app     OK   Plot Bars: 2 inputs (n:integer, color:string), 1 output (output_bars:Graph)
    MCP surface healthy.
    ```

    It exits with status 1 and names the likely cause when a step fails, for
    example when `/mcp` serves the web page because the app wasn't built with
    `mcp_server=True`. Add `--json` for the full report, contract included.

    Add `--config claude`, `cursor`, `vscode` or `all` to end a healthy check
    with the client config for that URL, in the client's own shape and named
    after the app's title, ready to paste:

    ```console
    $ fastdash doctor --mcp http://127.0.0.1:8080/mcp --config claude
      ...
    MCP surface healthy.

    Client config for Claude Code (.mcp.json):
      {"mcpServers": {"plot-bars": {"type": "http", "url": "http://127.0.0.1:8080/mcp"}}}
    Or run: claude mcp add --transport http plot-bars http://127.0.0.1:8080/mcp
    ```

    With `--json`, the same configs are under `"config"` in the report.

    To skip the paste, add `--write` with a single client. It merges the
    server into that client's project config file (`.mcp.json`,
    `.cursor/mcp.json` or `.vscode/mcp.json`, or the file given with
    `--config-path`), creating it if needed and keeping every server already
    in it:

    ```console
    $ fastdash doctor --mcp http://127.0.0.1:8080/mcp --config cursor --write
      ...
    MCP surface healthy.
    Wrote server "plot-bars" to .cursor/mcp.json (added; 2 other servers kept).
    ```

    Running it again changes nothing. If the file already has a different
    entry under that name (another server, or this app at an old URL), it is
    left alone unless you add `--force`. A file with comments (VS Code allows
    them) is never rewritten, since that would drop them; the command prints
    the entry to add by hand instead. In these cases it exits with status 1.

    By default the check is a single probe, so it fails at once if the app
    hasn't finished starting. Add `--wait` to make it a startup gate: it
    retries while the app is unreachable, `/mcp` still serves the web page, or
    nothing answers, and exits 0 as soon as the check passes (status 1 if the
    window runs out, with the last problem). `--wait` alone waits up to 30
    seconds; `--wait 60` sets the window, and `--timeout` then bounds each
    attempt. A failure from a server that did answer, such as a bad contract
    or a failed `--invoke`, still fails at once. It combines with the other
    flags, so starting an app and registering it is one line:

    ```console
    $ python app.py &
    $ fastdash doctor --mcp http://127.0.0.1:8080/mcp --wait --config claude --write
    Waiting for http://127.0.0.1:8080/mcp (up to 30s) ...
      ready after 4 attempts (3.6s)
      ...
    MCP surface healthy.
    Wrote server "plot-bars" to .mcp.json (added; 0 other servers kept).
    ```

    To skip the separate start and stop, give `--app` instead of `--mcp`.
    Doctor starts the app itself on a free local port, runs the same check
    once it is up, and stops it however the check ends, so it is one
    self-contained CI step. The target is a script that calls `.run()`
    (`app.py`), a script and its app object (`app.py:app`), or a module and
    its app object (`mypkg.server:app`). Whatever port and host the app's own
    `run()` asks for is replaced by that local port, and the reloader is off.
    It waits up to 60 seconds for the app to boot (`--wait` changes that). If
    the app exits first, the check fails at once with its exit code and last
    output. `--invoke`, `--json` and `--timeout` work as with `--mcp`:

    ```console
    $ fastdash doctor --app app.py --invoke
    Starting app.py on port 52817 ...
    Waiting for http://127.0.0.1:52817/mcp (up to 60s) ...
      ...
    MCP surface healthy.
    ```

    `--config` and `--write` aren't offered with `--app`: the URL they would
    give an agent is the temporary port, which is gone once the check ends.
    Register the app with `--mcp` at the address it really runs on.

    A good contract doesn't prove the app runs. Add `--invoke` to also run it
    once through the `invoke` tool, with its current values, the way an agent
    would. The check then fails if the callback raises or the app can't run
    from those values:

    ```console
    $ fastdash doctor --mcp http://127.0.0.1:8080/mcp --invoke
      ...
      invoke           OK   ran in 576.2 ms: output_bars={"data": [{"marker": {"color": "#1c7e...
    MCP surface healthy.
    ```

    `--invoke` runs your real callback, side effects and cost included, so it
    is off by default. An input with no default needs a value:
    `--invoke-input n=7`, repeatable. The value is read as JSON when it parses
    and as text otherwise. A failed run names the cause, for example
    `Problem: invoke ran and the callback failed: RuntimeError: database
    unavailable`.

## What the agent gets

| Surface | Provided by | Use |
|---|---|---|
| `describe_app()` | Fast Dash | **Start here.** The full contract + current state: each input's id, type, default, options and current value, and each output the app produces |
| `set_input(component_id, value)` | Fast Dash | Set one input |
| `set_inputs(inputs)` | Fast Dash | Set several inputs at once (`inputs` is a `{id: value}` dict); all or nothing |
| `invoke(inputs=None)` | Fast Dash | Run the callback (optionally setting inputs first), in one call |
| `set_form(specs)` | Fast Dash | Generate a form at runtime (`DynamicDash` only) |
| `get_invocation(index)` | Fast Dash | Fetch a past run's full kwargs + result |
| `list_component_types()` | Fast Dash | List the legal component types for `set_form` |
| `dash://layout`, `dash://components`, `get_dash_component` | Dash (native) | Read the static component tree (ids + Dash widget types) |

`component_id` is the **parameter name** itself (e.g. `"n"`, `"color"`).

Outputs come back as data: text whole, a table's first 100 rows, a Plotly
figure's `data` and `layout`. An **image output** (a PIL image, a matplotlib
figure or a `data:image/...` string) can't be read as JSON, so `invoke` and
`get_invocation` also return it as an MCP image content block: a PNG that a
vision-capable agent sees just as the user does. Its JSON entry keeps the
shape (`{"type": "Image", "size": [...], "image": "attached as an image content
block"}`), and the image block follows a text block naming the output id.
`describe_app` reports the shape only.

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
returns an expression gets `output_output_1`, `output_output_2`, and so on. `tag` is the widget the hint became — a `str` input can be a single-line
`TextInput`, a multi-line `TextArea` or a `ColorInput`, and they are not
interchangeable. Every input `tag` is a type `set_form` accepts, so an agent can
rebuild the widget it found. `outputs` lets an
agent see what a run returns **without** having to run it.

After a run, each output also carries the `current_value` that run produced.
A small value (a number, a short string, a short list) is shown whole. A large
one, such as a table, a figure or text over 2,000 characters, would make
every `describe_app` call as big as the run itself. It is summarized instead and
points at the full value:

```json
{"id": "output_report", "tag": "Table", "type": "array", "label": "REPORT",
 "current_value": {"type": "DataFrame", "shape": [100, 12], "columns": ["metric_0", "..."]},
 "current_value_summarized": true, "history_index": 3}
```

`get_invocation(3)` returns that run's outputs in full, as `invoke` did.

### The contract is enforced

Whatever `describe_app()` advertises is what `set_input` / `set_inputs` /
`invoke` accept — an agent cannot set a value the UI itself could never produce.
A value outside a dropdown's `options`, outside a Slider's `min`/`max`, or of the
wrong type (a string for a number, a string for a switch) is rejected with an
error naming the constraint. An upload takes what the browser sends, a
`data:<mime>;base64,...` URI, and an `UploadImage` only one that decodes to an
image. `invoke` and `set_inputs` are atomic: one bad value rejects the
whole call without changing anything. `set_inputs` then returns
`{"ok": false, "applied": {}, "errors": {...}}`, with each rejected key in
`errors`. The same holds for a form an agent builds
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

    The same goes for **outputs**: if the callback's result contains a secret's
    value, the agent gets `********` in its place (the browser still shows the
    real result). The match is on the text, so a short or common secret masks
    more than the secret: with a `PasswordInput` of `42`, every `42` in the
    output is masked, because any of them could be the PIN. When that happens,
    `invoke` and `get_invocation` list the masked outputs under `"redacted"`,
    and `describe_app` marks the output `"redacted": true`, so an agent knows
    a `********` is a mask and not the app's own text.

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

Each change also shows a short notice in the corner of the page, so the human
can tell the agent's edit from their own: "An agent set n = 42", "An agent is
running the app with factor = 5" (shown when the run starts, so a long run is
announced before its result lands), "An agent rebuilt the form (2 fields)",
or "The agent's run failed (ValueError)". A `PasswordInput` value shows as
`********`, and a long value is shortened. A rejected call shows nothing. Pass
`agent_activity=None` to keep the mirror silent:

```python
FastDash(callback_fn=fn, mcp_server=True, agent_activity=None)
```

The notices cover `FastDash` and `DynamicDash` apps, not `chat=True` apps.

### Watch a long run

A callback that `yield`s (a multi-step pipeline, a long simulation, an LLM
loop) shows each frame in the browser as it comes. An agent can watch the same
frames: when its `invoke` call asks for progress (an MCP `progressToken`, which
a client SDK sends when you pass a progress handler), each yielded frame
arrives as a `notifications/progress` message while the run goes on, and the
result is the final value, as without progress. With the official
[`mcp`](https://pypi.org/project/mcp/) SDK:

```python
async def show(progress, total, message):
    print(progress, message)          # 1 tick 1 / 2 tick 1 tick 2 / ...

await session.call_tool("invoke", {"inputs": {"n": 4}}, progress_callback=show)
```

A frame's `message` is its text. A multi-output frame is a JSON object keyed
by output id, a table or figure is its compact summary, and anything longer
than 2,000 characters keeps its last 2,000. A `PasswordInput` value is masked,
as in every other result. Without a `progressToken`, `invoke` answers exactly
as before.

## Drive it from Python

`fast_dash.connect()` drives a running app from a script, a notebook or another
service. Its methods are the app's tools, it blocks until each answers, and it
returns the tool's JSON as a dict. It needs no `asyncio` and no extra package.
Start the app above, then run:

```python
from fast_dash import connect

with connect("http://127.0.0.1:8080/mcp") as app:
    print([i["id"] for i in app.describe_app()["inputs"]])   # ['n', 'color']

    run = app.invoke(inputs={"n": 12, "color": "#2f9e44"})
    print(run["ok"], run["history_index"])                   # True 0

    past = app.get_invocation(index=run["history_index"])
    print(past["kwargs_summary"])                            # {'n': 12, 'color': '#2f9e44'}
```

Every tool takes keyword arguments named as in the table above:
`set_input(component_id, value)`, `set_inputs(inputs)`, `invoke(inputs)`,
`set_form(specs)` and `get_invocation(index)`. `describe_app` and
`list_component_types` take none. Arguments also go by position
(`app.set_input("n", 3)`), `app.tools` lists the tool names, and an image
output's PNG bytes are in the result's `.images`.
`app.invoke(inputs={...}, on_progress=print)` calls `on_progress` with each
frame's text as a yielding callback produces it (see
[Watch a long run](#watch-a-long-run)).

A bad call raises `fast_dash.mcp.MCPError` with the reason: the server can't be
reached, nothing is mounted at that path, or a tool failed. A rejected input is
not an error; it comes back as `{"ok": False, "errors": {...}}`, as it does for
an agent. A root URL gets `/mcp` added. `headers={...}` goes with every request,
for example an `Authorization` header for a proxy in front of the app, and
`timeout=` (default 30 seconds) caps each call, or with `on_progress` the wait
between frames.

For async code, or to see the raw protocol, use the official
[`mcp`](https://pypi.org/project/mcp/) client SDK (`pip install mcp`) and its
streamable-HTTP client against the same URL.

### Test it without a server

`app.mcp_test_client()` calls the same tools in-process and synchronously: no
server, port, `asyncio` or `mcp` package. Each call is a JSON-RPC request to the
app's real `/mcp` route, so a test sees exactly what an agent sees, validation
errors included. Each tool is a method, and it returns the tool's JSON as a dict:

```python
from fast_dash import FastDash

def plot_bars(n: int = 5, color: str = "#1c7ed6") -> int:
    return n

def test_agent_contract():
    client = FastDash(callback_fn=plot_bars, mcp_server=True).mcp_test_client()

    assert [i["id"] for i in client.describe_app()["inputs"]] == ["n", "color"]
    assert list(client.invoke(inputs={"n": 12})["outputs"].values()) == [12]

    bad = client.invoke(inputs={"n": "twelve"})
    assert bad["ok"] is False and "n" in bad["errors"]
```

Arguments go by name or by position (`client.set_input("n", 3)`). An image
output's PNG bytes are in the result's `.images`, and `client.tools` lists the
tool names. The client works with both the Flask and FastAPI backends. The app
needs `mcp_server=True`, and the one-MCP-app-per-process rule still applies.

It has the same methods as `connect()`, so a script written against one runs
against the other.

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
    `gunicorn app:server` and `uvicorn app:server` never call `run()`, so
    there the route warns instead, once, the first time a request reaches it
    from a non-loopback address.

- **One MCP-enabled app per process** (Dash's tool registry is process-global).
- **Multi-function and steps modes** skip the MCP surface.
- Chat *append* on the native-WebSocket streaming path is not yet ported (it
  replaces rather than appends).
