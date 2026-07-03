# Chat apps

Pass `chat=True` and your callback becomes a **streaming chat app** — a composer
pinned at the bottom, a scrolling transcript, and per-session conversation
history — with no LLM provider baked in. You bring the model; Fast Dash brings
the UI.

## The 5-line chatbot

The callback's first parameter must be named `query` (it receives the composer
text). `yield` strings to stream the reply token by token:

```python
from fast_dash import fastdash

@fastdash(chat=True)
def assistant(query: str):
    """A helpful assistant."""
    for token in my_llm.stream(query):     # any provider — you choose
        yield token
```

That is the whole app: a bottom-anchored composer, a streaming reply rendered as
markdown, and a transcript. Press **Enter** to send, **Shift+Enter** for a new
line.

!!! note "No vendor lock-in"
    Fast Dash never bundles an LLM SDK. `my_llm` above is *your* code calling
    whatever you like — OpenAI, Anthropic, a local model, a plain function.

## Conversation history

Declare a `history` parameter and Fast Dash injects the prior messages of the
current browser session before each turn — a list of
`{"role": "user" | "assistant", "content": str}`:

```python
@fastdash(chat=True)
def assistant(query: str, history: list):
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": query})
    for token in my_llm.stream(messages):
        yield token
```

History is kept **per browser session**, server-side, and bounded (default 50
turns; set `chat_history_size=...`).

## Developer-declared settings

Any parameter *other than* `query`, `history`, and `ctx` renders as a setting the
**user** sets manually, using the same type-hint inference as a regular Fast Dash
app — dropdowns, number inputs, switches, even a dataset upload:

```python
from typing import Literal
from fast_dash import fastdash, Upload

@fastdash(chat=True)
def assistant(
    query: str,
    model: Literal["gpt-4", "claude", "gemini"] = "claude",
    temperature: float = 0.7,
    dataset: Upload = None,
):
    ...   # model / temperature / dataset are passed to every turn
```

`model` becomes a dropdown, `temperature` a number input, `dataset` an upload
box. Their live values are passed to the callback each turn. Without a canvas
they render in a **sidebar**; with `canvas=True` they render in the **chat panel**
above the composer (next to the assistant's dynamic controls). So one app can mix
fixed, developer-declared inputs *and* assistant-built dynamic ones.

## The frame grammar

Yielding a `str` is sugar for a text frame. For richer replies, `yield` frame
dicts — every type below renders natively:

| Frame | Shape | Renders as |
|---|---|---|
| `content` | `{"type": "content", "content": str}` | streamed markdown text |
| `reasoning` | `{"type": "reasoning", "content": str}` | a collapsible "thinking" block |
| `tool_start` | `{"type": "tool_start", "name": str, "args": dict, "id": str}` | a tool-call card (spinner) |
| `tool_end` | `{"type": "tool_end", "name": str, "result": Any, "id": str}` | resolves the matching card |
| `artifact` | `{"type": "artifact", "content": Figure \| DataFrame \| Image \| str}` | an inline artifact |
| `extraction` | `{"type": "extraction", "content": Any}` | a JSON card |
| `interrupt` | `{"type": "interrupt", "action_requests": [...], "allowed_decisions": [...]}` | an approve/reject card |
| `error` | `{"type": "error", "message": str}` | an error notice |

`tool_start` and `tool_end` are paired by their `id` (defaulting to `name`), so a
card opens with a spinner and resolves in place when the result arrives. Artifacts
materialize at turn completion. A bare `str` yield, a plain `str` return, and this
frame grammar can be mixed freely. Unknown frame types are ignored (with a
warning), never fatal; an exception raised inside the callback is caught, shown as
an error in the reply, and the session stays usable.

## A richer example

```python
import numpy as np
import plotly.graph_objects as go
from fast_dash import FastDash

def analyst(query: str, history: list):
    yield {"type": "reasoning", "content": "Fetch the series, then plot it."}
    yield {"type": "tool_start", "name": "fetch_series", "id": "t1",
           "args": {"query": query}}
    yield {"type": "tool_end", "name": "fetch_series", "id": "t1",
           "result": {"rows": 50, "status": "ok"}}
    yield "Here is the series you asked about: "
    x = np.linspace(0, 12, 50)
    yield {"type": "artifact", "content": go.Figure(go.Scatter(x=x, y=np.sin(x)))}

FastDash(callback_fn=analyst, title="Analyst", chat=True).run()
```

While a turn streams, the **Send** button becomes a **Stop** button; pressing it
cancels the turn and the partial reply is kept with a `(stopped)` marker.

## LangGraph agents

Instead of a callback, `chat=True` accepts a compiled LangGraph graph or a
`"module:attr"` spec string (needs `fast-dash[langstage]`). The graph is bridged
to the frame grammar by [langstage-core](https://pypi.org/project/langstage-core/),
and multi-turn memory rides the graph's checkpointer keyed by the chat session:

```python
from fast_dash import FastDash

# a compiled LangGraph graph, or "my_pkg.agents:graph"
FastDash(callback_fn="my_pkg.agents:graph", chat=True).run()
```

## The `ctx` object

`query` and `history` are all the 5-line chatbot needs. Power features fold into
one optional `ctx` parameter (a `ChatContext`) instead of a growing list of magic
names — declare it to opt in:

```python
def bot(query, history, ctx):
    ...   # ctx.thread_id, ctx.canvas, ctx.resume
```

- `ctx.thread_id` — the session id (the LangGraph checkpointer thread).
- `ctx.canvas` — the canvas's live values `{name: value}` (empty without a canvas).
- `ctx.resume` — a decision answering a pending interrupt (HITL), else `None`.

## The canvas (assistant-built UI)

`canvas=True` adds a live output region beside the transcript that the assistant
**builds and mutates** — a conversational [DynamicDash](dynamic.md). The chat
becomes a left panel; the canvas is the main area. Two frames drive it, using the
same UI-spec grammar as DynamicDash (`{name, type, props, value, label, span}`):

- `{"type": "canvas", "specs": [...]}` — (re)build the canvas from a spec list
  (component types, properties, content).
- `{"type": "set_props", "target": "<name>", "props": {...}}` — patch one
  component in place (e.g. widen a slider's range).

Each spec's optional **`span`** (out of 12, default 12 = full-width row) arranges
components into a responsive grid — two `span: 6` panels sit side by side, so the
assistant lays out real multi-column dashboards, not just a single column.

`ctx.canvas` gives the assistant the canvas's **live values** each turn, so it can
read what the user changed:

```python
from fast_dash import FastDash

def assistant(query, ctx):
    if "build" in query.lower():
        yield "Set the two numbers on the right, then say 'add them'."
        yield {"type": "canvas", "specs": [
            {"name": "a", "type": "Slider", "value": 3, "props": {"min": 0, "max": 20}},
            {"name": "b", "type": "Slider", "value": 5, "props": {"min": 0, "max": 20}},
        ]}
    elif "add" in query.lower():
        a, b = ctx.canvas["a"], ctx.canvas["b"]
        yield f"{a} + {b} = {a + b}"

FastDash(callback_fn=assistant, chat=True, canvas=True).run()
```

Components split by kind automatically: **input** widgets (`Slider`, `Select`,
`Switch`, `ColorInput`, …) render in an input area on the chat side (above the
composer), while **display** components (`Graph`, `Table`, `Image`, `Markdown`)
render in the output canvas. So the assistant builds a control panel on one side
and a live dashboard on the other, from a single spec list. The canvas is a
separate surface from the transcript: `content` frames still stream into the
chat, while `canvas`/`set_props` frames target it.

### Driving the canvas with an LLM

In practice an LLM emits the canvas mutations. `canvas_tool_specs()` returns
provider-neutral JSON-Schema tool definitions; `apply_tool_call()` turns a
returned tool call into a frame — no LLM SDK is bundled:

```python
import anthropic
from fast_dash import FastDash, canvas_tool_specs, apply_tool_call

client = anthropic.Anthropic()
TOOLS = canvas_tool_specs()          # build_canvas, set_canvas_props

def assistant(query, history, ctx):
    msg = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=1024, tools=TOOLS,
        messages=[{"role": "user", "content": query}],
    )
    for block in msg.content:
        if block.type == "text":
            yield block.text
        elif block.type == "tool_use":
            frame = apply_tool_call(block)   # -> canvas / set_props frame
            if frame:
                yield frame

FastDash(callback_fn=assistant, chat=True, canvas=True).run()
```

### App-first: chat as an add-on (`chat_drawer=True`)

By default the chat is the primary surface. With `chat_drawer=True` the app comes
first: the developer-declared settings and a **Run** button fill a left sidebar,
the output canvas is the main area, and the chat collapses into a drawer that
opens from a floating **Assistant** button. The user can drive the whole app with
settings + Run and never open the chat; the assistant is there when they want it
to change the layout or plots.

```python
from typing import Literal
from fast_dash import FastDash

def studio(query, ctx, points: int = 40,
           color: Literal["indigo", "teal", "red"] = "indigo"):
    fig = make_plot(points, color)          # from the settings
    if query:                                # a chat message (not a Run)
        yield f"Updated. You asked: {query}"
    yield {"type": "canvas", "specs": [{"name": "plot", "type": "Graph", "value": fig}]}

FastDash(callback_fn=studio, chat=True, chat_drawer=True).run()
```

`chat_drawer=True` implies a canvas (the output surface). Clicking **Run** invokes
the callback with an empty `query` (check `if query:` to tell a Run from a chat
message) and updates the canvas without adding a transcript entry.

## Backends

Streaming rides whatever transport the backend already uses, with no change to
your callback:

- **Flask** (default): frames stream as socket.io events.
- **ASGI** (`backend="fastapi"`, needs `fast-dash[fastapi]`): frames are pushed
  with Dash's native `set_props` over a WebSocket — no socket.io.

## Human-in-the-loop (interrupts)

A LangGraph agent that calls `interrupt(...)` pauses the turn and Fast Dash
renders an **approve / reject** card (from the interrupt's `allowed_decisions`)
showing the requested action. The composer is held until you choose a decision;
clicking one resumes the same turn on its checkpoint — the agent continues from
where it paused. Multi-step approvals just pause again. (Resume is a LangGraph
capability, so the live decision buttons appear for langstage agents; a plain
generator that yields an `interrupt` frame renders the card as informational.)

## Serving the agent over AG-UI

`serve_agui=True` (LangGraph agent on `backend="fastapi"`) mounts an AG-UI SSE
endpoint at `/agui`, so external AG-UI frontends (e.g. CopilotKit) can drive the
same graph the chat UI does — the mirror of the MCP story:

```python
FastDash(callback_fn="my_pkg.agents:graph", chat=True,
         backend="fastapi", serve_agui=True).run()
```

## Driving a chat app over MCP

`mcp_server=True` exposes the chat app to agents at `/mcp`:

- `describe_app()` reports the composer contract (the `query` string), any
  sidebar `settings`, and — with a canvas — its current specs and component types.
- `invoke(query=..., settings=..., canvas_values=...)` runs one turn headlessly
  and returns its frames (JSON-safe) plus the post-turn `canvas` specs; history
  and thread state advance across calls. So a headless agent sees and drives the
  canvas exactly as a browser user does.

## What chat mode does and doesn't allow

`chat=True` is a distinct interaction mode, so a few combinations are rejected at
startup with a clear message:

- the first parameter **must** be `query`;
- `update_live=True`, multi-function apps, and steps apps are **not** supported;
- `outputs=` and `stream=` are ignored (the transcript is the output; streaming
  is always on).

The existing [`Chat` output component](components.md) (`-> Chat`) is unchanged
and still available for embedding a chat transcript as one output among several.
