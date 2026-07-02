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

## Settings in the sidebar

Any parameter *other than* `query` and `history` renders in the sidebar as a
setting, using the same type-hint inference as a regular Fast Dash app:

```python
from typing import Literal

@fastdash(chat=True)
def assistant(
    query: str,
    history: list,
    model: Literal["gpt-4", "claude", "gemini"] = "claude",
    temperature: float = 0.7,
):
    ...
```

`model` becomes a dropdown and `temperature` a number input; their live values
are passed to every turn. With no such parameters, the sidebar is hidden and the
chat fills the width.

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

Any callback may also declare a `thread_id` parameter to receive the session id
(the same value the adapter threads into the checkpointer).

## Backends

Streaming rides whatever transport the backend already uses, with no change to
your callback:

- **Flask** (default): frames stream as socket.io events.
- **ASGI** (`backend="fastapi"`, needs `fast-dash[fastapi]`): frames are pushed
  with Dash's native `set_props` over a WebSocket — no socket.io.

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
