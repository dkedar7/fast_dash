# 0.6.0 Engineering Spec — Unified `chat=` API (RFC #145, clean break)

This file is the coordination contract for all implementation agents. It is
temporary (deleted before release). Where this spec and RFC #145 differ, THIS
SPEC WINS (the RFC assumed a deprecation cycle; 0.6.0 is a clean break — no
aliases, old knobs removed outright).

## Decisions already made (do not re-open)

- One argument: `chat=`. No `agent=` alias.
- REMOVED ENTIRELY (no deprecation aliases): `canvas`, `chat_drawer`,
  `chat_agent`, `chat_agent_title`, `chat_agent_drive`, `chat_agent_position`,
  and the canvas spec-registry (`CANVAS_COMPONENT_REGISTRY`) + drawer layout
  branches + the floating right-aside + its toggle button.
- O1: `chat_model=` accepts a model instance OR a provider string (resolved via
  `langchain.chat_models.init_chat_model`); env fallback `FASTDASH_MODEL`.
- O2: `set_layout` v1 rearranges/resizes EXISTING slots only (mosaic letters
  must be a subset of existing slot letters; refusal note otherwise).
- O3: names are `set_output`, `chat_tools` (as in RFC).
- Placement nuance (deviation from RFC wording, matches its intent): the rule
  keys on "an app callback exists", not "inputs exist". App-shaped callback
  present -> collapsible chat panel in the navbar (even if the app has zero
  inputs). No app callback (or chat-shaped callback) -> full-page chat.

## Public API (0.6.0)

```python
FastDash(
    callback_fn=...,          # optional when chat= is agent-ish
    chat=False,               # False | True | model instance | provider str? NO —
                              #   provider strings go in chat_model; chat= takes
                              #   True | callable | compiled graph | model instance
    chat_tools=None,          # None -> default full toolkit; tuple of str | RunPython(...)
    chat_model=None,          # model instance | "provider:model" str; env FASTDASH_MODEL
    chat_title="Assistant",   # panel header (sidebar placement)
    chat_placeholder=None,    # unchanged from 0.5.3
    chat_history_size=50,     # unchanged (chat mode)
)
```

Also on the `fastdash` decorator (same params).

Top-level exports (lazy where they need optional deps):
`from fast_dash import agent_toolkit, FastDashMiddleware, app_prompt, RunPython`

### `chat=` acceptance and mode resolution

| `chat=` value | callback_fn | Resulting mode |
|---|---|---|
| False/None | any | normal app (no chat) — unchanged |
| True | chat-shaped (first param named `query`) | chat mode (existing #133 behavior, callback IS the handler) |
| True | app-shaped | app + AUTO-BUILT agent sidecar (requires [agent] extra + chat_model/FASTDASH_MODEL; friendly ASCII errors otherwise) |
| True | None | construction Error (nothing to chat with) |
| model instance | app-shaped or None | auto-built agent around that model; sidecar if app-shaped callback, full-page chat if None |
| `(query, ctx)` callable (incl. async / async-gen) | app-shaped | sidecar (agent as supplied, frames only) |
| same callable | None | full-page chat driven by the callable |
| compiled LangGraph (duck-typed `is_langstage_target`) | app-shaped | sidecar via langstage bridge |
| same graph | None | full-page chat via langstage bridge (existing chat-mode graph path) |
| chat-shaped callback_fn AND separate agent in chat= | — | construction Error ("two chat handlers") |

Model-instance detection: object with `invoke` + `bind_tools` attrs and not
callable-with-(query, ctx) and not a graph. Keep the duck-typing conservative
and documented in code comments.

Internal flags: keep `self.is_chat` (full-page chat), `self.has_chat_sidecar`
(app + agent). Store `self.chat_tools_config` (resolved allowlist, see below),
`self.chat_title`. Delete `is_canvas` / `is_chat_drawer` and every branch they
gate (grep the whole repo, including mcp.py and tests).

### `chat_tools` resolution

Default (None) -> `("read_app", "set_input", "run_app", "set_output",
"set_layout", "run_python")` where run_python carries approval=True.
Entries: str names or `RunPython(approval=bool)` config objects.
`chat_tools=()` -> read-nothing/do-nothing agent (chat + artifacts only).

Enforcement is SERVER-SIDE at frame dispatch in chat_app.py (single choke
point), independent of how the agent was built. A frame whose verb is not in
the allowlist appends a legible italic refusal note to the transcript (reuse
the `_sidecar_no_drive_note` pattern):
`_( The <verb> capability is disabled on this app (chat_tools). )_`
Existing auto-trim rules survive, expressed as allowlist trims with warnings:
- `update_live=True` -> remove set_input/run_app (double-trigger hazard)
- multi-function/steps app -> trim to ("read_app",)

## Frame grammar additions (chat_app.py dispatch)

Existing frames unchanged. New/changed:

| Frame | Shape | Behavior |
|---|---|---|
| `set_output` | `{"type": "set_output", "slot": str, "value": Any}` | Render `value` through the SAME transform pipeline the Run button uses for that output slot (position-matched), push per-client. Slot = mosaic letter (str, e.g. "a"). Invalid slot -> refusal note. |
| `set_layout` | `{"type": "set_layout", "mosaic": str}` | Validate (rectangular, letters subset of existing slots — reuse `_check_if_rectangular` etc.); server re-runs the mosaic engine RE-PARENTING the existing leaf components; push new children of `output-group-col` per-client. Invalid -> refusal note with the reason. |
| `set_props` | REMOVED (was canvas-only) | Unknown-frame warn+skip path |
| `set_input`, `run_app` | unchanged shapes | now gated by chat_tools allowlist |

Transports:
- Flask/socket.io: extend the existing drive op protocol with `layout` and
  `set_output` ops; the clientside reducer applies children via
  `dash_clientside.set_props`. Serialized component trees travel as Dash
  component JSON (`to_plotly_json` recursively) — the renderer accepts these
  as children.
- ASGI: `set_props("output-group-col", {"children": <tree>})` full push
  (established pattern: full-state push, not ops).

## Run-always-wins (reconciliation)

- At build time, serialize the default output layout tree into
  `dcc.Store(id="fd-default-layout")`.
- A clientside callback on `submit_inputs.n_clicks` (prevent_initial_call)
  restores `output-group-col.children` from that store BEFORE the server
  callback response lands (the response then fills leaf values by ID as
  usual). Always-restore (idempotent) — no dirty flag.
- Leaf component IDs are STABLE across re-mosaic (the same component objects
  are re-parented, never recreated) so registered callbacks keep working.
- Every agent-driven change fires the existing drive-flash affordance.

## agent_tools.py (new module, no heavy imports at module top)

- Per-turn frame buffer: `contextvars.ContextVar` holding a list.
  `emit_frame(frame: dict)`, `drain_frames() -> list[dict]`, and a
  `turn_buffer()` context manager the sidecar loop enters per turn.
- Tools (plain functions usable as langchain @tool targets; created bound to
  an app via `agent_toolkit(app)`):
  - `read_app()` -> dict: app contract (reuse the MCP describe machinery) +
    current input values (MCP mirror) + output slot letters/types.
  - `set_input(name, value)` -> emits set_input frame; returns ack str.
  - `run_app()` -> emits run_app frame; returns ack str (results stream to UI).
  - `set_output(slot, value)` -> emits set_output frame.
  - `set_layout(mosaic)` -> emits set_layout frame.
  - `run_python(code)` -> if approval required: `langgraph.types.interrupt`
    with an action_request describing the code; on resume-approve execute; on
    edit execute edited code; on deny return denial message to the model.
    Execution: `exec` in the app process, cwd = app root, module-level
    `__fd_exec__` namespace persisted per session thread_id; capture stdout,
    last-expression value (AST pattern from DataChat), and matplotlib/plotly
    figures; results usable via set_output (return a short repr + stash rich
    objects in a per-thread registry the set_output tool can reference).
  - `run_python_sandboxed(code)` -> sandbox.py engine.
- `app_prompt(app) -> str`: system-prompt text describing the app contract,
  slots, and available tools with usage guidance.
- `FastDashMiddleware(app)`: langchain.agents.middleware.AgentMiddleware
  subclass contributing the toolkit + app_prompt. Import guarded; clear
  ImportError message `pip install "fast-dash[agent]"`.
- `build_auto_agent(app, model)`: resolve model (instance or
  init_chat_model(str)); `langgraph.prebuilt.create_react_agent(model,
  tools=agent_toolkit(app), prompt=app_prompt(app))`. Guarded import.

## sandbox.py (new module; generalized port of DataChat's engine)

`run_code(code: str, inject: dict[str, Any] | None = None, timeout: int = 25)
-> {"stdout": str, "result": Any|None, "figure": str|None (plotly JSON),
"table": records|None, "error": str|None}`.
Subprocess runner: scrubbed env (drop names matching KEY/TOKEN/SECRET/
PASSWORD/OPENROUTER/OPENAI/ANTHROPIC), socket function-level network block
(block getaddrinfo/create_connection/connect — NOT the socket class),
resource limits POSIX-only (RLIMIT_CPU, RLIMIT_AS; skip cleanly on Windows),
inject vars via parquet/pickle file handoff, AST last-expression capture.

## Constraints (violations = rejected work)

1. ASCII-only in error strings/warnings/console output (Windows cp1252).
2. Mantine-only UI chrome; AppShellSection pinning (never position:sticky in
   ScrollArea).
3. Everything on the wire JSON-safe; figures/DataFrames converted server-side.
4. No new required core dependencies. `[agent]` extra = langchain>=1.0 +
   langgraph. `[langstage]` unchanged. Tests for optional-dep features carry
   skipif guards (pattern: `requires_fastapi` in tests).
5. Navbar width lesson (v0.5.5/#143): AppShell navbar width must agree
   between generate_layout and the toggle_sidebar callback. The sidebar-chat
   width stays 420; keep both call sites in sync.
6. Match existing code style (comment density, naming). No gratuitous renames
   of internal symbols.
7. Do NOT commit. Run the test suites you touched (`poetry run pytest
   tests/test_chat.py -q` minimum) before reporting done; report pass counts.
8. Unknown frame types warn+skip, never crash. A tool/frame error must never
   kill the turn loop.

## Test invocation

- `cd C:/Users/Kedar/Documents/Code/fast_dash`
- `poetry run pytest tests/test_chat.py -q` (and the full suite when told)
- Env has langchain 1.3.11 + langgraph + langstage_core 1.0.1 + fastapi
  installed — write real tests, guard with skipif for CI.
