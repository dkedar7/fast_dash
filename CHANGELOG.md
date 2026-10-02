# Release 0.7.1

## 0.7.1 (2026-10-02)

Patch release: closes a secret leak in 0.7.0 and lets agents read the
results of the apps they run.

### Security
- **`describe_app` returned secret-derived outputs unmasked.** After a run, an
  output computed from a `PasswordInput` came back in the clear in
  `describe_app`'s output `current_value`. 0.7.0 masked `invoke` and
  `get_invocation` (#194) but not this path. All three now mask it.

### Fixed
- **Agents can read what an app returned** (#261). `invoke`, `describe_app`
  and `get_invocation` returned the compact history summary: an 80-character
  preview of any text over 200 characters, and only the shape of tables and
  figures. They now return the value: text whole, a table's first 100 rows
  (ISO dates, `truncated` when longer), and a figure's data with plain arrays.
  Images stay summarized, and anything over 500 KB comes back clipped and
  marked `truncated`. `get_invocation` gains an `outputs` field;
  `outputs_summary` is unchanged.
- **Single-select inputs reject a list over MCP** (#267). A `str` list
  default, `Literal`, `Enum` or `Annotated[str, [...]]` input accepted a JSON
  array, so the callback received a `list`. It's now rejected the way a wrong
  type is (#150). MultiSelects still take lists.

### Docs
- **Connecting an agent** (#265): each client's real config. Claude Code and
  Cursor use `mcpServers`, VS Code uses `servers`. The single `servers`
  snippet was silently ignored by the first two.
- **`describe_app` example** (#264) now shows the library's actual output.
- **New "Drive it from Python" section** (#266): a tested `mcp`-SDK client
  example.
- The one-minute product film is on the README and the docs home page, served
  from dkedar.com. 26 MB of unused legacy images were removed from the repo.

## 0.7.0 (2026-09-26)

Backlog catch-up: the fixes from a full triage of the open issues, including two
community contributions. The theme is **human ↔ agent parity**: an untouched UI
Run and an agent's `invoke()` now hand the callback the same values, and
`describe_app` describes exactly what `invoke` accepts and returns.

### Security
- **A `PasswordInput` default was served in plaintext** (#224). A key pre-filled
  from config sat in `app.layout`, so `/_dash-layout`, Dash's native
  `dash://layout` and `get_dash_component` all exposed it. Every served surface
  now carries only the mask; the real value is swapped back in when the callback
  runs.

### Behaviour changes
- **Collection defaults start on a real value** (#204, #219). `x: str = ["a", "b"]`
  starts on `"a"`, `x: int = range(0, 10)` on `0`, and `x: list = [...]` passes
  `[]`. All three used to pass `None` on an untouched Run. A `depends_on` list
  resolver now selects its first option instead of clearing the value.
- **A `dict` parameter receives a `dict`** (#231) of the selected entries, all
  selected to start, not a list of key strings.
- **`datetime.datetime` inputs render a date *and time* picker** (#242) and keep
  the time on both surfaces (they were date-only, and dropped the time).
- **Output labels come from the returned variable names** (#201). They're parsed,
  not split on commas, so `return f"Hello, {name}!"` no longer invents a second
  output. A string literal still labels itself.
- **`port=` defaults to unset** (#203), so `run_kwargs={"port": N}` is honoured.
  The effective default is still 8080; if both are given and disagree, it warns
  and `port=` wins.
- **`describe_app` contract**: every static input gains `required`; component-
  class hints (`level: Slider = 3`) report the widget's JSON type (#198); a
  `DateRange` is an `array` (#218); list, dict and range defaults report the
  starting value as `default`; `datetime` values use the picker's
  `YYYY-MM-DD HH:mm:ss` spelling. Short lists and dicts come back whole from
  `invoke` / `get_invocation` instead of as `{"type": "list", "len": n}`.
- **`fast-dash[agent]` now includes the langstage bridge** (#211), so it's the
  only extra the auto-built chat assistant needs.

### Fixed
- **`stream=True` with `yield` crashed the Run** (#212, #207). Each yielded value
  now streams live and the last one is the result, on the UI and over MCP
  `invoke`. Without `stream=True` a generator runs to completion.
- **`update()` rejected the id `describe_app` reports** (#233). It accepts the
  bare name or the `output_`-prefixed id, and a bad name lists the valid ones.
- **`app.run(debug=True)` / `run(port=...)` raised `TypeError`** (#205). `run()`
  forwards Dash's run options, like `DynamicDash.run`.
- **`steps=` apps threw a 500 on every page load** (#213), and the sidebar toggle
  crashed on `backend="fastapi"` (#227).
- **An unknown `accent=` blanked the whole page** (#234). It falls back to blue
  with a warning.
- **`mcp_server=True` served no `/mcp` under gunicorn/uvicorn** (#244). `/mcp` is
  now mounted when the app is built, not in `run()`.
- **Unannotated `Figure` / `DataFrame` returns didn't render** (#217). They
  render as a graph / table (PIL and matplotlib as images).
- **MCP parity:** a component-class hint accepted any string (#198); a no-default
  parameter surfaced as a raw `TypeError` (#238); a single-output `list` return
  was cut to its first element (#237); DynamicDash dropped fields left at their
  default (#199) and treated Markdown blocks as inputs (#220).
- **A mistyped chat callback pointed at the wrong fix** (#214, by @Georgefifth
  in #215). It now names the `query` parameter rule.
- **An integer `Literal` had an inconsistent contract** (#235, by
  @wangzhengzhuo05 in #236). Both drive paths hand the callback the hinted type.

### Docs
- The Claude Code plugin skill is up to date (#247): widget table, starting
  values, and new patterns for MCP, `DynamicDash` and chat.
- New "Streaming outputs" and "Deploying an app with `mcp_server=True`" sections.

## 0.6.9 (2026-08-06)

Bug-fix release closing the eight findings the nightly dogfood filed against
0.6.8 — seven on the MCP agent contract, one on its UI-side sibling.

### Security
- **A secret could escape through a run's output** (#194) — `invoke` and
  `get_invocation` returned the callback's output unredacted, so an app that
  derives its output from a `PasswordInput` handed the credential to any agent
  that could reach the (unauthenticated) `/mcp`. The input axis was closed in
  #151; the output axis is closed now, masking the secret wherever it appears
  in a payload. The live browser still receives the real value.

### Fixed
- **The agent path skipped input coercion** (#186) — `invoke`/`set_inputs`
  handed the callback a raw option string / ISO string where a UI Run handed it
  an `Enum` member / `date`, re-opening #181 and #182 on the agent surface.
- **A parameter named `input_*` could not be driven over MCP** (#189) — the
  drive path stripped the prefix, so the Quickstart's own `input_text` was
  called as `text=` and raised `TypeError`.
- **`Annotated[str, [...]]` lost its dropdown options** (#192) — `describe_app`
  reported `options: null`, so validation was skipped and `set_input` accepted a
  value the UI could never emit.
- **A `depends_on` child kept its stale value** (#191) — switching the parent
  over MCP re-resolved the child's options but not its value, leaving
  `describe_app` advertising a `current_value` outside its own `options`.
- **`set_form` accepted duplicate field names** (#190) — two inputs sharing one
  id is a contract the callback can never honour.
- **`set_form` silently ignored unknown spec keys** (#193) — including
  `default`, the key `describe_app` itself emits, so feeding its output back
  produced an empty field. `default` is now an accepted alias for `value`, and
  unknown keys are rejected rather than dropped.
- **A component used as a type hint ignored the signature default** (#188) —
  the exported `Slider` ships `value=10`, so `level: Slider = 3` ran with 10
  while `describe_app` reported 3.

## 0.6.8 (2026-07-27)

One feature and three fixes, two of which made a documented type hint lie to the
callback it typed.

### Added
- **Drag to resize the input sidebar** (#80) — a grab strip on the sidebar's
  trailing edge resizes it up to half the viewport, with the output pane
  tracking it. Also operable from the keyboard (focus the handle, arrow keys
  nudge, shift for a coarser step), and hidden below the breakpoint where the
  navbar becomes a full-width overlay. A width you drag to survives collapsing
  and re-expanding the sidebar.

### Fixed
- **`update_live` apps rendered only for the first visitor per worker process**
  (#183) — the page-load render was gated on a permanent latch stored on the
  `FastDash` instance, so the first visitor got a dashboard and every later
  visitor (or a plain reload) got a silent blank one. Since every 0-input
  callback auto-enables `update_live`, this hit the parameterless dashboard
  case. Each page load now renders, and the re-mount protection that latch
  provided is preserved via a one-shot token.
- **`enum.Enum` inputs passed the raw option string, not the member** (#181) —
  `.value` / `.name` raised `AttributeError`, and `is` / `==` comparisons
  against a member silently never matched, returning a wrong result with no
  error. The callback now receives the Enum member its hint promises.
- **`datetime.date` inputs passed a raw ISO string once set** (#182) — the
  callback got a real `date` only while the input was untouched; picking a date
  (or an agent setting one) turned it into `"2025-12-25"`, so `.isoformat()`,
  `.year` and friends crashed. ISO values are now parsed back to
  `date`/`datetime`; values already of the right type, and unparseable ones,
  are left untouched.

## 0.6.7 (2026-07-25)

Bug-fix release clearing the open board — six findings from the nightly dogfood,
four of them on the MCP agent contract.

### Fixed
- **A second `mcp_server=True` app in one process silently hijacked the first**
  (#171) — Dash's MCP tool registry is process-global, so the second app's tools
  overwrote the first's and *both* `/mcp` endpoints resolved to whichever
  registered last: an agent driving app A silently ran app B's callback. The
  one-app-per-process limit was documented in prose but never enforced; it now
  raises a `RuntimeError` naming the owning app (re-mounting the same app stays
  idempotent).
- **The MCP `initialize` handshake told agents the app was stateless** (#173) —
  every client read Dash's stock *"does NOT update the user's browser"*
  instructions, steering agents away from the stateful drive tools that are the
  feature's whole point. Fast Dash now serves its own instructions.
- **`describe_app()` dropped the `label` key for DynamicDash outputs** (#172) —
  the documented `{id, tag, type, label}` shape held for `FastDash` but not
  `DynamicDash`, so a generic agent reading `output["label"]` raised `KeyError`.
  The key is now always present (`null` when the component has no label).
- **`backend="fastapi"` started completely silently** (#170) — no URL and no
  boot confirmation, so a user following the docs had nothing to open and no way
  to tell a running server from a hung one. The URL is announced and uvicorn's
  startup lines are no longer suppressed.
- **A non-ASCII character in a raised error crashed cp1252 consoles** (#169) —
  the `parent_control` `ValueError` carried `U+2192` (and an em dash), so
  printing that traceback on a default Windows console raised a secondary
  `UnicodeEncodeError` that masked the message. Both replaced, and a test now
  scans every `raise`/`warn` string in the package.

### Documentation
- **"10 minutes to Fast Dash" misdescribed collection defaults** (#176) — a
  `list`/`dict`/`range()` default builds the widget's *option set*, so an
  untouched Run passes `None`, not the default. Documented with the `TypeError`
  it otherwise causes and how to guard against it.

## 0.6.6 (2026-07-23)

Bug-fix release. Most were surfaced by the nightly dogfood routine, plus a
directly-reported rendering bug.

### Fixed
- **No-input callbacks rendered blank** — a callback that takes no inputs
  auto-enables `update_live` and runs on load, but its output stayed hidden
  behind the pre-run "Run to see results" placeholder, which only a Run click
  cleared. `update_live` apps have no Run step, so they now never gate and show
  their output immediately. (Affected every `update_live` app, not just 0-input
  ones.)
- **Agent `invoke()` output never rendered until the first human Run** (#164) —
  the same placeholder gate hid agent-produced output on a freshly-loaded page.
  Both the Interval and WebSocket output drains now clear it, so "agent drives,
  human watches" works without a Run first.
- **MCP drive tools leaked a raw `TypeError`** (#165) — omitting a required
  argument raised at call time, exposing the internal `enable_mcp.<locals>`
  qualname instead of the structured `{"ok": false, ...}` contract. Every tool
  now reports missing/unexpected arguments in that contract shape.
- **`describe_app()` reported a `dict`-default input as `type: "object"`** (#162)
  — but the MultiSelect it renders only accepts/produces an array of keys. The
  declared type is now reconciled with the rendered widget.
- **matplotlib outputs summarized as a colliding `"Figure"`** (#167) —
  `invoke`/`get_invocation` summarized a matplotlib figure via the generic
  fallback, whose `type: "Figure"` collided with the Plotly summary while
  carrying none of its keys. matplotlib now reports the same `"Image"` shape a
  PIL image does.

## 0.6.5 (2026-07-16)

Closes the agent loop: an auto-built chat assistant can now see what its own run
produced, not just trigger it.

### Changed
- **`run_app` reports its result to the assistant** (#135) — the auto-agent's
  `run_app` tool used to return a canned "outputs are updating", leaving the
  model blind to what it produced. It now runs the callback, returns a summary of
  each output slot's new value, and carries those outputs on its frame so the
  browser renders them without a second execution (exactly one run per
  `run_app`). Callback errors are reported back so the model can retry. The
  raw-frame / langstage drive path is unchanged.

## 0.6.4 (2026-07-15)

Two agent-contract discoverability gaps the nightly dogfood found in 0.6.3.

### Fixed
- **`describe_app()` reported `outputs: []` for every `DynamicDash` app** (#160) —
  the #152 output contract read the public `outputs_with_ids`, but `DynamicDash`
  stores its outputs under `_outputs_with_ids`. It now reports the real outputs.
- **`describe_app()` still reported `tag: "Text"` for a dropdown** (#158) — #147
  named the widget for the ColorInput/TextArea branches only; the Select branch
  and int/bool/date/Literal reported hint names absent from
  `list_component_types()`. Every static input's `tag` now names the widget it
  became and is a member of `list_component_types()`.

## 0.6.3 (2026-07-13)

An agent-contract release: the MCP surface now describes what an app really is,
and refuses what its UI could never produce.

### Fixed
- **`Tuple[int, str]` return hints silently dropped outputs** (#156) — the
  idiomatic spellings collapsed to one output; only bare `-> (int, str)` worked.
- **Apps shared one mutable-default `run_kwargs` dict** (#153) — constructing a
  second app rewrote the first's port, so `run()` bound the wrong one.
- **`PasswordInput` values leaked over the no-auth MCP route** (#151) — secrets
  now go in but never come back out (`"secret": true`, masked values).
- **Value validation was type-blind** (#150) — a string slipped past a Slider's
  min/max; numeric and boolean inputs now reject the wrong JSON type.
- **`DynamicDash` forms skipped all validation** (#144) — the form currently on
  screen (`initial_specs`, a `parent_control` cascade, or an agent's `set_form`)
  is now the contract enforced against, parent control included.
- **The MCP no-auth warning watched the defunct `mcp_host`** (#149) — it now
  fires at `run()`, keyed off the host actually bound.
- **All `str` widgets reported tag `"Text"`** (#147) — a colour picker, textarea
  and text box now each report the widget they became.

### Added
- **Output contract in `describe_app`** (#152) — agents can discover what a run
  produces (id, component tag, JSON type, label) without side-effectingly
  calling `invoke()`.

## 0.6.2 (2026-07-12)

### Added
- **Collapsible input accordion for chat sidebars.** A long input list can now
  tuck to a header instead of crowding the conversation. In full-page chat the
  inputs are secondary "Settings (N)" (collapsed by default when there are
  many); in a sidecar they are the primary "Inputs (N)" (open by default).
  Normal (non-chat) form apps are unchanged.

## 0.6.1 (2026-07-07)

### Changed
- **Typed agent events by default.** langstage extractors and chat renderers
  emit typed frames, so chat surfaces render structured agent events out of the
  box.

## 0.6.0 (2026-07-07)

### Added
- **Unified `chat=` API (RFC #145).** `chat=` is now polymorphic — pass `True`,
  a compiled agent graph, a spec string, or an agent callable — with a
  `chat_tools` allowlist and a collapsible sidebar panel.
- **Agent app toolkit + runtime layout/content engine**, with sandboxed
  execution, an auto-agent bridge, and human-in-the-loop (HITL) execution.

### Changed
- **Breaking:** the unified `chat=` argument supersedes the earlier per-mode
  chat flags. Update code that used the pre-0.6 chat parameters to pass the
  agent (or `True`) directly via `chat=`.

## 0.5.5 (2026-07-05)

### Bug fixes
- Correct the sidebar-chat navbar width so the output area and the collapse
  affordance align.

## 0.5.4 (2026-07-05)

### Added
- **`chat_agent_position="sidebar"`** — render the chat panel inside the inputs
  sidebar (the sidecar placement) rather than as a separate surface.

## 0.5.3 (2026-07-05)

### Added
- Mode-aware, customizable empty-transcript placeholder for chat apps.

## 0.5.2 (2026-07-04)

### Bug fixes
- The chat sidecar's `run_app` now renders outputs, not just inputs.

## 0.5.1 (2026-07-04)

### Bug fixes
- Make the `describe_app()` MCP contract consistent and surface date defaults.

## 0.5.0 (2026-07-03)

### Added
- **Chat mode (`chat=True`) and the agent sidecar (`chat=<agent>`).** Turn a
  `query`-first callback into a full-page chat app, or attach a chat assistant
  to a normal form app that can read and drive its inputs.
- **UI refresh.** A Mantine-based design foundation (accent-color API, richer
  theme), polished chrome/inputs/outputs, motion + accessibility + mobile
  support, skeleton loaders and a pre-run empty state, and input help captions
  inferred from the callback docstring. FontAwesome dropped.

## 0.4.1 (2026-07-01)

### Bug fixes
- **`describe_app()` reports Enum input defaults consistently.** A plain
  `enum.Enum` default was reported as `default: null` (even though a default
  exists), and an `IntEnum`'s `default`/`options` were ints while its
  `current_value` was a string — so the contract self-contradicted and an agent
  building `invoke(...)` from the advertised default passed a different type than
  a UI Run. The contract now reports `str(member.value)` for an Enum's `default`
  and `options`, matching the value the UI `Select` emits (which fast_dash builds
  with `str(e.value)`), so `default` / `options` / `current_value` are all
  type-consistent. Same contract-correctness class as #110 / #116 / #120. (#126)

## 0.4.0 (2026-06-30)

A UI/UX modernization pass on the default app surface, plus a real
figure-rendering fix.

### Bug fixes
- **A `plotly.graph_objects.Figure` return *type* now renders.** Output
  inference mapped the string annotation `"go.Figure"` to a Graph but the actual
  `go.Figure` *type* (any module without `from __future__ import annotations`)
  fell through to an `html.H1`, so the figure dict was rendered as a React child
  and crashed (React error #31), leaving the chart blank. Plotly figures — the
  most common Fast Dash output — now render either way.

### Changed
- **Inputs are now rendered entirely with Mantine components.** Numeric inputs
  use `dmc.NumberInput` and booleans use `dmc.Checkbox` (instead of the previous
  `dbc` controls), so every control follows the app's theme and dark mode. This
  fixes a number field staying white in dark mode and a checkbox rendering in an
  off-theme accent color. (The boolean input's `component_property` is now
  `checked` rather than `value`.)
- **A `str` input is a single-line text field by default.** Only a multi-line or
  long (>120 char) default becomes a text area, and a hex-color default
  (e.g. `"#1c7ed6"`) becomes a color picker. Previously every `str` became a
  tall text area, so forms scrolled before reaching the Run button.

### Added
- **Modern output cards.** Each output has a header strip (title + divider), a
  soft shadow with a hover lift, and a "Run to see results" empty state.
- **The Run button is pinned to the bottom of the input sidebar**, so it stays
  visible regardless of how many inputs there are; the inputs scroll
  independently above it.
- **Overflow containment.** A large output (wide table, long text) scrolls
  *inside* its card on both axes instead of growing out of its grid cell or
  pushing a neighbor off-screen; input controls stay within the sidebar width.

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