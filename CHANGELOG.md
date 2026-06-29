# Release 0.3.5

## 0.3.5 (2026-06-29)

### Bug fixes
- **Type-hint inference no longer degrades under `from __future__ import
  annotations`.** With PEP 563 enabled, every annotation reaches inference as a
  string (`"dict"`, `"list"`, `"Annotated[int, range(...)]"`), so a `dict` input
  silently rendered as a Text box instead of a multi-select, a `list`-defaulted
  `str` as a Text box instead of a dropdown, and `Annotated[int, range(...)]` /
  `int = range(...)` as a Text box instead of a Slider. fast_dash now resolves
  annotations (via `get_type_hints`, preserving `Annotated` metadata) before
  building components, with a per-parameter fallback so one unresolvable
  annotation (e.g. a forward-ref return type) doesn't degrade the other inputs.
  (#119)
- **`describe_app()` now exposes a static Slider's `min`/`max`/`step`.** A
  `Slider` input (`Annotated[int, range(...)]` or an `int = range(...)` default)
  is hard-bounded in the UI, but for a static `FastDash` app the contract
  reported it as a generic unbounded number (no `props`), so a headless agent
  couldn't discover or stay within the range. The contract now carries a
  `props: {min, max, step}` block for bounded widgets (mirroring what DynamicDash
  forms already expose); a genuinely unbounded number box still reports no
  bounds. (#120)

### Changed
- **`set_input` / `set_inputs` / `invoke` reject out-of-range Slider values.**
  Extending the 0.3.4 options validation: a numeric value outside a Slider's
  `min`/`max` (e.g. `99999` on a `range(0, 100)` slider) is now rejected with a
  clear error, the way a UI slider physically can't emit it — completing the
  human<->agent parity for numeric inputs. Unbounded inputs stay permissive and
  `invoke` remains atomic. (#120)

### Bug fixes
- **`describe_app()` no longer leaks a `depends_on` object repr, and resolves a
  cascading input's options.** For the documented `depends_on(...)` cascading-
  inputs pattern, the dependent input's `default` was reported as a stringified
  internal object (`"<fast_dash.utils.depends_on object at 0x...>"`) and its
  `options` as `null`. The contract now reports `default: null` and resolves the
  dependent dropdown's `options` from the current parent value using the same
  helper the live cascade uses — so an agent reading only the contract can drive
  a cascading input correctly. More generally, a non-JSON default (e.g. a
  `range`) is never surfaced as an object repr. (#116)
- **A `dict` default now surfaces its keys as `options`.** A `dict`-defaulted
  parameter renders a multi-select of the dict's keys, but `describe_app()`
  reported `options: null` (unlike a `list` default). The keys are now
  discoverable through the contract. (#116)

### Changed
- **`set_input` / `set_inputs` / `invoke` validate values against advertised
  `options`.** A value the UI `Select`/`MultiSelect` could never produce (e.g.
  `set_input("flavor", "strawberry")` against a `["vanilla", "choco"]` dropdown)
  is now rejected with an `allowed options` error, mirroring the existing
  unknown-id guard — closing a human<->agent parity gap. Inputs with no
  advertised options stay permissive, and `invoke` remains atomic (a bad value
  rejects without mutating the mirror). (#116)

## 0.3.3 (2026-06-27)

### Bug fixes
- **A single-select dropdown (`str` with a list default) no longer seeds its
  *options* as its value over MCP.** Previously the input mirror seeded the
  whole options list, so `describe_app()` reported a `list` `current_value`
  under `type: "string"`, and `invoke()` with defaults passed a `list` to a
  `str` parameter while the browser held `None`. The mirror now seeds `None`
  for list/dict/range defaults (those are the component's options, not its
  value), so `describe_app`'s `current_value` is type-consistent and `invoke()`
  matches a UI Run. Thanks to @muhamedfazalps for the report. (#110)

## 0.3.2 (2026-06-26)

### Bug fixes
- **`describe_app()` now reports an agent-built DynamicDash form.** After an
  agent calls `set_form`, `describe_app()` previously returned `inputs: []`
  (the form was drivable but undiscoverable through the documented "start here"
  tool). It now derives each field's `id`, `type`, `label`, `default`,
  `options`, and `props` (e.g. a Slider's `min`/`max`/`step`) plus its current
  value from the materialized form — so agent-generated UIs are discoverable
  headlessly and across reconnecting sessions.

## 0.3.1 (2026-06-25)

### Bug fixes
- **`backend="fastapi"` now works when run as a script.** Previously the ASGI
  backend never bound (Dash 4.3 infers the uvicorn import string by frame-walking,
  which fast_dash's extra `run()` frame broke), and Dash's native `/mcp` route
  500'd on the ASGI backend. fast_dash now serves the ASGI app object directly via
  uvicorn and installs a small middleware that sets the request context for `/mcp`.
- **`DynamicDash(..., port=...)`** no longer raises a `TypeError` from `dash.Dash()`;
  the port is used as `run()`'s default (an explicit `run(port=...)` still wins).

### Added
- **`describe_app()` MCP tool** — returns the input contract *and* current state
  for a headless agent: each input's id, type, default, allowed options, and
  `current_value` (including values set via `set_input` / `set_inputs`, which the
  native `dash://components` / `get_dash_component` don't surface without a browser).

### Changed
- The `set_inputs` MCP tool argument is renamed `values` → `inputs` to match
  `invoke(inputs=...)`.
- Docs: the per-parameter agent contract lives in `describe_app()`, not the drive
  tools' raw input schemas.

## 0.3.0 (2026-06-20)

Requires **Dash >= 4.3**.

### Added
- **MCP app surface.** Pass `mcp_server=True` to `@fastdash`, `FastDash`, or
  `DynamicDash` and the app serves a web UI **and** an MCP server on the **same
  port** at `/mcp`, built on [Dash's native MCP](https://dash.plotly.com). AI
  agents (Claude Code, Cursor, Cline, …) can inspect and drive it.
  - Native Dash resources for introspection: `dash://layout`,
    `dash://components`, and the `get_dash_component` tool.
  - fast_dash tools that drive the live app — `set_input`, `set_inputs`,
    `invoke`, `set_form` (DynamicDash), `get_invocation`, `list_component_types`
    — registered via `dash.mcp.mcp_enabled`.
  - Agent mutations reflect in the live browser within ~500 ms (no reload).
- **`DynamicDash`** — a Dash app whose input form is generated at runtime,
  either by a parent control or by an agent calling the `set_form` tool.
  `run()` mounts the MCP server automatically; `placeholder="..."` sets an
  empty-form hint.
- **`invoke(inputs=...)`** — set values and run the callback in a single MCP
  round-trip (atomic validation: a bad key rejects without mutating state).
- **Opt-in ASGI backend with real-time push.** `backend="fastapi"` (install
  `fast-dash[fastapi]`) runs the app on Dash's FastAPI backend with WebSocket
  callbacks; agent mutations and `stream=True` updates push to the browser via
  `set_props` (sub-100 ms) instead of the ~500 ms polling drain. Flask remains
  the default, and `stream=True` on Flask continues to use flask-socketio
  unchanged. (Chat append on the native-WebSocket streaming path is not yet
  ported and currently replaces rather than appends.)
- The input mirror is seeded from component / signature defaults so a headless
  agent sees real values before any browser renders the page.

### Notes
- The MCP route shares the web app's host/port and has **no authentication**;
  keep it loopback in development.
- One MCP-enabled app per process (Dash's `mcp_enabled` registry is global).
- Multi-function and steps modes skip the MCP surface.

## 0.2.14 (2025-09-22)

### Bug Fixes
- **Automatic updates with no arguments**: Fixes behavior of callback execution when it has no arguments.