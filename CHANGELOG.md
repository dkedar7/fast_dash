# Release 0.4.0

## 0.4.0 (2026-06-20)

### Changed
- **MCP now runs on Dash's native MCP server (requires Dash >= 4.3).** Instead
  of a standalone FastMCP server on a separate port, `mcp_server=True` mounts
  Dash's native MCP on the **same app/port** at `/mcp`. Agents connect at
  `http://<host>:<port>/mcp`.
  - The read-only surface is delegated to Dash: `dash://layout`,
    `dash://components`, and the `get_dash_component` tool.
  - fast_dash keeps the stateful "drive the app" tools (`set_input`,
    `set_inputs`, `invoke`, `set_form`, `get_invocation`,
    `list_component_types`), now registered via `dash.mcp.mcp_enabled`.
  - Removed: the separate MCP port, the `serve_mcp_in_thread`/`build_mcp_server`
    FastMCP plumbing, the bespoke result serialization, and the `screenshot`
    tool (Dash formats figures/DataFrames natively). The `[mcp]` extra is gone
    (Dash core already requires `mcp`).
  - The `mcp_port`/`mcp_host` kwargs are retained for compatibility but no
    longer open a second port.

### Added
- **Opt-in ASGI backend with real-time push.** `backend="fastapi"` (install
  `fast-dash[fastapi]`) runs the app on Dash's FastAPI backend with WebSocket
  callbacks; agent mutations stream to the browser via `set_props` (sub-100 ms)
  instead of the ~500 ms polling drain. Flask remains the default.
- **`stream=True` on the ASGI backend** is rebuilt on native WebSocket
  `set_props` (no flask-socketio / `DashSocketIO`). On the default Flask backend
  streaming continues to use flask-socketio, unchanged. (Chat append semantics
  on the native path are not yet ported and currently replace rather than
  append.)

### Notes
- The MCP route shares the web app's host/port and has no authentication; keep
  it loopback in development.
- Single MCP-enabled app per process (Dash's `mcp_enabled` registry is global).

## 0.3.0 (2026-06-20)

### Features
- **MCP app surface (opt-in).** Pass `mcp_server=True` to `@fastdash`,
  `FastDash`, or `DynamicDash` and the app simultaneously serves a web UI and
  an MCP server (streamable-HTTP, default port 8001 at `/mcp`) that AI agents
  (Claude Code, Cursor, Cline, …) can inspect and drive. Install with
  `pip install 'fast-dash[mcp]'`.
  - **Resources** (read-only state): `fastdash://app`, `.../inputs`,
    `.../outputs`, `.../layout`, `.../history`.
  - **Tools**: the callback itself, plus `set_input` / `set_inputs` /
    `invoke` / `get_invocation` / `list_component_types` / `screenshot`, and
    `set_form` for `DynamicDash`.
  - **Server → browser push**: agent mutations apply to the live UI within
    ~500 ms via a `dcc.Interval` drain (no reload).
- **`DynamicDash`**: a Dash app whose input form is generated at runtime,
  either by a parent control or by an agent calling the `set_form` MCP tool.
- **`invoke(inputs=...)`**: set values and run the callback in a single MCP
  round-trip (atomic validation — a bad key rejects without mutating state).
- **`DynamicDash(placeholder="...")`**: sugar for an empty-form hint message.

### Developer experience
- `DynamicDash.run()` auto-starts the MCP server when `mcp_server=True`
  (new `mcp_port` / `mcp_host` params), matching `FastDash` — one call, no
  manual `serve_mcp_in_thread`.
- `mcp_server=True` is the one canonical path; `serve_mcp_in_thread` is the
  documented escape hatch for bare callables.

### Bug fixes / hardening
- MCP tool returns are now sanitized so a non-JSON-serializable payload
  (e.g. numpy arrays from a Plotly figure) can no longer crash and tear down
  the client session; `screenshot()` degrades gracefully when `kaleido` is
  absent.
- Agent-driven `invoke()` now renders outputs in the browser identically to a
  UI submit for every output type (the output drain applies the same
  per-output transform, not just the Plotly-identity case).
- The input mirror is seeded from component / signature defaults so a headless
  agent sees real values before any browser renders the page.
- Callback registration degrades gracefully (with a warning) when a return
  type can't be modeled by the MCP schema generator (e.g. a pandas DataFrame),
  instead of crashing app startup.

### Notes
- The MCP port has no authentication; it binds `127.0.0.1` by default and
  warns if `mcp_host` is set to a non-loopback address.
- Multi-function and steps modes skip the MCP surface.

## 0.2.14 (2025-09-22)

### Bug Fixes
- **Automatic updates with no arguments**: Fixes behavior of callback execution when it has no arguments.