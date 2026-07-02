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
dicts. Phase 1 renders `content` (and surfaces `error`); the remaining types are
part of the contract and render in later phases:

| Frame | Shape | Renders as |
|---|---|---|
| `content` | `{"type": "content", "content": str}` | streamed markdown text |
| `reasoning` | `{"type": "reasoning", "content": str}` | a "thinking" block |
| `tool_start` | `{"type": "tool_start", "name": str, "args": dict}` | a tool-call card |
| `tool_end` | `{"type": "tool_end", "name": str, "result": Any}` | completes the card |
| `artifact` | `{"type": "artifact", "content": Figure \| DataFrame \| Image \| str}` | an inline artifact |
| `error` | `{"type": "error", "message": str}` | an error notice |

A bare `str` yield, a plain `str` return, and this frame grammar can be mixed
freely. Unknown frame types are ignored (with a warning), never fatal; an
exception raised inside the callback is caught, shown as an error in the reply,
and the session stays usable.

## What chat mode does and doesn't allow

`chat=True` is a distinct interaction mode, so a few combinations are rejected at
startup with a clear message:

- the first parameter **must** be `query`;
- `update_live=True`, multi-function apps, and steps apps are **not** supported;
- `outputs=` and `stream=` are ignored (the transcript is the output; streaming
  is always on);
- `mcp_server=True` is skipped for now (a correct chat MCP contract lands in a
  later release).

The existing [`Chat` output component](components.md) (`-> Chat`) is unchanged
and still available for embedding a chat transcript as one output among several.
