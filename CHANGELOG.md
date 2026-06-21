# Release 0.3.0

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