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
box. Their live values are passed to the callback each turn, rendered in the
**sidebar** above (or beside) the transcript.

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
    ...   # ctx.thread_id, ctx.resume
```

- `ctx.thread_id` — the session id (the LangGraph checkpointer thread).
- `ctx.resume` — a decision answering a pending interrupt (HITL), else `None`.

## Add an assistant to a normal app (a chat sidecar)

The sections above make the chat *the* app. The mirror image: keep a **normal**
Fast Dash app — typed inputs, real outputs, a Run button — and mount an
**independent** chat assistant beside it by passing your agent as `chat=`. The
assistant lives in the left sidebar, stacked under the inputs and collapsible;
the app keeps working on its own (set inputs, Run, read outputs). The agent is a
chat callback, a LangGraph graph, or a chat-model instance — exactly as for
full-page chat:

```python
from fast_dash import FastDash

def dashboard(revenue: int = 100, region: str = "West") -> str:
    """A normal Fast Dash app."""
    return f"{region}: ${revenue}"

FastDash(
    callback_fn=dashboard,                 # your app, unchanged
    chat=my_langgraph_agent,               # graph | "module:attr" | (query, ctx) callback | model
    chat_title="Assistant",
).run()
```

The agent shares nothing with the app's callback except the capabilities the
toolkit grants, all reached through `ctx` and drive frames:

- **Read** — declare `ctx` and `ctx.inputs` gives the agent the app's live input
  values `{name: value}` each turn. `ctx.input_specs` gives the app's input
  *contract* (types, options, bounds) — the same one an MCP agent sees.
- **Drive** — the agent can `yield {"type": "set_input", "name": ..., "value": ...}`
  to set a control, `yield {"type": "run_app"}` to run the app and refresh its
  outputs, `yield {"type": "set_output", "slot": "A", "value": ...}` to render a
  value into one output slot directly, and `yield {"type": "set_layout", "mosaic": "AB"}`
  to rearrange the existing output slots. Anything a user can do, the agent can do.

### Let Fast Dash build the agent (`agent_toolkit`)

Pass a chat model (a model instance, a `"provider:model"` string, or `chat=True`
with `chat_model=`) and Fast Dash **auto-builds** a LangChain assistant wired to
your app. Its tools come from `agent_toolkit(app)` — `read_app`, `set_input`,
`run_app`, `set_output`, `set_layout`, and `run_python` — trimmed to the
`chat_tools` allowlist you pass (needs `pip install "fast-dash[agent]"`):

```python
from fast_dash import FastDash

def dashboard(revenue: int = 100, region: str = "West") -> str:
    return f"{region}: ${revenue}"

FastDash(
    callback_fn=dashboard,
    chat=True,
    chat_model="openai:gpt-4o-mini",       # or a model instance / FASTDASH_MODEL
    chat_tools=("read_app", "set_input", "run_app"),  # read + drive, no code exec
).run()
```

`chat_tools=None` (the default) enables the full toolkit — including
`run_python`, which runs Python in the app process with human-in-the-loop
approval. Narrow it to a tuple of tool-name strings (and/or `RunPython(...)`
configs). `chat_tools=("read_app",)` gives a **read-only** assistant that
converses and reads `ctx.inputs` but can't drive the app; `chat_tools=()` is a
chat with no app access at all.

To wire the toolkit into an agent you build yourself, call `agent_toolkit(app)`
for the tools and `app_prompt(app)` for a system prompt, or attach
`FastDashMiddleware(app)` to a LangChain `create_agent`.

The auto-trim rules keep the assistant safe by default: on an `update_live` app
every app-driving verb is dropped (its inputs recompute on change, so driving
would double-run the callback or be immediately overwritten — the assistant is
read-only there), and on a multi-function / steps app the toolkit trims to
`read_app` only. A chat-shaped `callback_fn` **and** an agent in `chat=` is
rejected — one adds a chat *to* an app, the other *is* the chat.

Bad inputs are handled: `set_input` is validated against the app's contract, so
an unknown input, a value outside an input's options, or a wrong-typed value is
refused with a message (and fed back to the model) rather than reaching the
callback. A user's **Run** always wins — it restores the default output layout,
so `set_layout` / `set_output` changes never outlive a manual Run. Pressing
**Stop** mid-turn stops immediately — any input the agent had already set stays
set (Stop means "stop now", not "undo").

!!! warning "Password inputs are never exposed"
    A `PasswordInput`'s value is **redacted** from `ctx.inputs`, omitted from
    `ctx.input_specs` / `app_tool_specs`, and `set_input` on it is refused — so a
    secret the user typed is never sent to the model and the agent can't set it.
    `run_app` still runs the callback with the real value.

!!! note "Large outputs"
    `run_app`'s outputs are streamed to the browser like any other update; a
    very large output (a big `DataFrame` or image) is a correspondingly large
    payload per drive. Prefer paging or summarising heavy outputs the assistant
    triggers frequently.

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

## Driving a chat app over MCP

`mcp_server=True` exposes the chat app to agents at `/mcp`:

- `describe_app()` reports the composer contract (the `query` string) and any
  sidebar `settings`.
- `invoke(query=..., settings=...)` runs one turn headlessly and returns its
  frames (JSON-safe); history and thread state advance across calls.

## What chat mode does and doesn't allow

`chat=True` is a distinct interaction mode, so a few combinations are rejected at
startup with a clear message:

- the first parameter **must** be `query`;
- `update_live=True`, multi-function apps, and steps apps are **not** supported;
- `outputs=` and `stream=` are ignored (the transcript is the output; streaming
  is always on).

The existing [`Chat` output component](components.md) (`-> Chat`) is unchanged
and still available for embedding a chat transcript as one output among several.
