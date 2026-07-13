# History

# Release 0.6.3

## 0.6.3 (2026-07-13)

An **agent-contract** release: the MCP surface now describes what an app really
is, and refuses what its UI could never produce. Every open bug at the time of
writing is fixed.

### Fixed

- **`Tuple[int, str]` return hints silently dropped outputs** ([#156]). Only the
  bare parenthesized spelling `-> (int, str)` produced two outputs; the
  idiomatic `Tuple[int, str]` / `tuple[int, str]` are generic *aliases*, not
  tuple objects, so they collapsed to a single output and every return value
  after the first was discarded. Both spellings now expand, including under
  `from __future__ import annotations` (where the hint arrives as a string), and
  a variadic `tuple[int, ...]` correctly stays a single output.
- **Apps shared one `run_kwargs` dict** ([#153]). `run_kwargs=dict()` was a
  mutable default that the constructor then mutated with its own port, so
  building a second app silently rewrote the first app's port (and any other
  `run_kwargs`, including the security-relevant `host`) — `app.run()` bound the
  wrong port. `run_kwargs` is now copied, never aliased, and the caller's dict is
  left untouched.
- **`PasswordInput` values leaked over the no-auth MCP route** ([#151]). The chat
  surface redacted secrets; the MCP surface handed them out in plain text via
  `describe_app`, the `set_input` echo, and `get_invocation`. A password's value
  now goes *in* (an agent can still fill the field) but never comes back out:
  the contract marks the input `"secret": true` and every value it reports is
  masked — including a secret carried in a spec's `props`, and one whose form
  has since been replaced (its value is dropped from the mirror with it).
- **Value validation was type-blind** ([#150]). The range check only fired for
  numbers, so a *string* sailed straight past a Slider's `min`/`max` — `"9999"`
  is not an `int`, so nothing compared it to the maximum — and reached the
  callback as a value no drag of the slider could produce. Numeric and boolean
  inputs now reject values of the wrong JSON type.
- **`DynamicDash` forms skipped all validation** ([#144]). Every guard keyed off
  the *static* input list, which a `DynamicDash` doesn't have, so unknown ids,
  out-of-options values and out-of-range slider values were all accepted in
  silence. The specs of the form **currently on screen** are now the contract
  that `set_input` / `set_inputs` / `invoke` enforce against — whether that form
  came from `initial_specs`, a `parent_control` cascade, or an agent's
  `set_form` (including `[{"label": ..., "value": ...}]` style `Select` options).
  The parent control is part of the contract too: the UI passes it to the
  callback, so an agent can discover and drive it.
- **The MCP no-auth warning watched the wrong knob** ([#149]). It warned on
  `mcp_host`, which stopped binding anything when MCP moved onto the app's own
  port, and stayed silent on the setting that actually exposes an
  unauthenticated tool endpoint: serving on `0.0.0.0`. It now fires at `run()`,
  keyed off the host the server really binds.
- **All `str` widgets reported the same tag** ([#147]). A colour picker, a
  textarea and a text box all described themselves as `"Text"`, so a headless
  agent reading `describe_app` couldn't tell them apart. Each now reports the
  widget it actually became (`ColorInput` / `TextArea` / `Text`).

### Added

- **Output contract in `describe_app`** ([#152]). It reported inputs only, so the
  one way for a headless agent to learn what an app returns was to *call* it —
  discovery by side effect. `describe_app` now also lists each output's `id`,
  the component `tag` it renders into (`Graph` / `Table` / `Markdown` / …), its
  JSON `type` and `label`, plus a summary of the value currently on screen once
  something has run.

[#144]: https://github.com/dkedar7/fast_dash/issues/144
[#147]: https://github.com/dkedar7/fast_dash/issues/147
[#149]: https://github.com/dkedar7/fast_dash/issues/149
[#150]: https://github.com/dkedar7/fast_dash/issues/150
[#151]: https://github.com/dkedar7/fast_dash/issues/151
[#152]: https://github.com/dkedar7/fast_dash/issues/152
[#153]: https://github.com/dkedar7/fast_dash/issues/153
[#156]: https://github.com/dkedar7/fast_dash/issues/156

# Release 0.6.2

## 0.6.2 (2026-07-12)

Chat sidebars get a **collapsible input accordion**, so a long list of settings
(or, in a sidecar, the app's own inputs) can tuck to a header instead of
crowding the conversation.

### Added

- **Collapsible "Settings" / "Inputs" accordion in chat sidebars.** The sidebar
  inputs are wrapped in a fully-collapsible `dmc.Accordion` — a single-mode item
  that closes completely on click — scoped to chat surfaces; a normal (non-chat)
  form app is unchanged.
    - **Full-page chat (`chat=True`)**: the inputs are secondary settings, shown
      as a **"Settings (N)"** panel that defaults *collapsed* when there are
      several (and open when there are only a few), keeping the transcript roomy.
    - **Sidecar (`chat=<agent>`)**: the app's own inputs are the primary
      interface, shown as an **"Inputs (N)"** panel that defaults *open*; it only
      adds a way to tuck them so the chat panel can reclaim the space. The
      accordion stays inside the input container and never touches the chat
      panel — collapsing the chat panel still lifts the height cap so the inputs
      show in full.

# Release 0.6.1

## 0.6.1 (2026-07-07)

LangGraph chat agents now render their **typed agent events** as first-class
cards by default. When an agent calls a common tool, Fast Dash's langstage
bridge extracts a structured object from the tool result and shows a purpose-built
card in the transcript instead of a raw tool blob -- a reflection collapses into a
thinking block, a `write_todos` result becomes a task list with status icons, and
`display_inline` renders figures / tables / markdown inline.

### Added

- **Typed agent-event rendering, on by default.** The langstage bridge now passes
  the seven built-in extractors to `iter_event_frames`, so a LangGraph agent's
  tool results stream as `extraction` frames that render as typed cards. No opt-in
  is required; a plain `(query, ctx)` chat callable is unaffected.

  | Tool | `extracted_type` | Rendered as |
  |---|---|---|
  | `think_tool` | `reflection` | a collapsible "Reflection" thinking block |
  | `write_todos` | `todos` | a task list; per-item status icon, completed struck through |
  | `memory` | `memory_updated` | a compact "Memory updated" callout |
  | `skill_view` | `skill_loaded` | a "Skill loaded" callout |
  | `skill_manage` | `skill_event` | a skill create / update / delete callout |
  | `__compression__` | `compression_summary` | a subtle "Context compressed" divider callout |
  | `display_inline` | `display_inline` | the flagship: figures / tables / markdown rendered inline (the same renderer artifacts use) |

  An unknown `extracted_type` falls back to a compact collapsible JSON card, so a
  typed event is never dropped.

- **`chat_extractors=`** (new `FastDash` / `fastdash` parameter): an iterable of
  extractor objects (each with a `tool_name`, an `extracted_type`, and a callable
  `extract(content)`) appended to the built-in defaults, deduped by `tool_name`
  with your extractor winning on a collision -- so you can override how any
  built-in tool renders. Entries are duck-type validated at construction with a
  friendly ASCII error. Only used for a LangGraph agent; a plain chat callable
  ignores it silently.

### Fixed

- Inline artifact tables render as a real `DataTable` again (a `className` kwarg
  unsupported by `dash_table.DataTable` on dash 4.3 had been silently falling back
  to markdown text); the class now rides a wrapper div.

# Release 0.6.0

## 0.6.0 (2026-07-07)

A single unified `chat=` argument replaces the family of `chat_*` knobs, and the
in-app assistant gains a real tool surface: it can read the app, drive its
inputs, set individual outputs, rearrange the output layout, and run Python
(with human-in-the-loop approval). This is a clean break — the old canvas /
drawer / `chat_agent_*` API is removed outright (no deprecation aliases).

### Breaking changes

- **Six parameters removed** (no aliases): `canvas`, `chat_drawer`, `chat_agent`,
  `chat_agent_title`, `chat_agent_drive`, `chat_agent_position`. Everything an
  agent-on-an-app used to configure now flows through `chat=` and its companions.
- **The canvas surface is gone.** The canvas component registry
  (`CANVAS_COMPONENT_REGISTRY` app plumbing), the drawer layout branches, the
  floating right-hand aside, and its toggle button are all removed. A chat
  assistant now lives in the left sidebar (stacked under the inputs), the only
  placement. The `canvas` / `set_props` chat frames are no longer part of the app
  grammar — an unrecognized frame warns and is skipped rather than building a
  canvas. (The provider-neutral `canvas_tool_specs` on-ramp helper stays for code
  that opts into a canvas explicitly.)
- **`chat=` is now polymorphic.** One argument accepts several kinds of value,
  and the mode is resolved from it together with the shape of `callback_fn`:

  | `chat=` value | `callback_fn` | Result |
  |---|---|---|
  | `False` / `None` | any | a normal app, no chat |
  | `True` | chat-shaped (first param `query`) | full-page chat; the callback is the handler |
  | `True` | app-shaped | the app **plus an auto-built assistant** sidecar (needs the `[agent]` + `[langstage]` extras and a `chat_model=` / `FASTDASH_MODEL`) |
  | a model instance | app-shaped / `None` | an assistant auto-built around that model (sidecar, or full-page if no app callback) |
  | a `(query, ctx)` callable | app-shaped / `None` | your agent as supplied, as a sidecar or full-page chat |
  | a compiled LangGraph graph | app-shaped / `None` | driven through the langstage bridge |

- **`chat_tools=`** replaces `chat_agent_drive=`. It is the server-side allowlist
  of what the assistant may do: `None` -> the default full toolkit (`read_app`,
  `set_input`, `run_app`, `set_output`, `set_layout`, and `run_python` with
  approval); a tuple of tool-name strings and/or `RunPython(...)` configs to
  narrow it; `()` for a read-nothing/do-nothing chat. A frame whose verb is not
  in the allowlist appends a legible refusal note to the transcript instead of
  acting. The old auto-trim rules survive as allowlist trims (with warnings):
  `update_live=True` drops every app-driving verb (the app recomputes on change,
  so driving would double-run or be overwritten); a multi-function / steps app
  trims to `read_app` only.
- **Placement is inferred, not configured.** The rule keys on whether an app
  callback exists: an app-shaped callback -> a collapsible chat panel in the left
  sidebar (even with zero inputs); no app callback (or a chat-shaped one) ->
  full-page chat.

### Added

- **A chat-agent toolkit** (`fast_dash.agent_toolkit(app)`) — the list of
  LangChain `@tool` functions the assistant uses, trimmed to the app's
  `chat_tools` allowlist: `read_app`, `set_input`, `run_app`, `set_output`,
  `set_layout`, `run_python` (+ `push_result`). Wire it into your own agent
  yourself, or attach `FastDashMiddleware(app)` to a `create_agent`, or let
  `chat=True` build one for you.
- **`set_output` and `set_layout`** frames/tools. `set_output(slot, value)`
  renders a value into one output slot through the same transform pipeline the
  Run button uses (addressed by mosaic letter, e.g. `"A"`). `set_layout(mosaic)`
  rearranges/resizes the *existing* slots by re-parenting their leaf components
  (leaf ids stay stable, so registered callbacks keep working). A user's Run
  always wins: it restores the default output layout before the response lands.
- **`run_python`** — the assistant can execute Python in the app process against
  a per-conversation namespace, with **human-in-the-loop approval** by default
  (approve / edit / reject). Produced figures / DataFrames show inline and can be
  placed into an output slot with `push_result`. A sandboxed variant
  (`run_python_sandboxed`) runs code in a scrubbed, network-blocked subprocess.
- **The `[agent]` extra** (`pip install "fast-dash[agent]"`) — LangChain 1.x +
  LangGraph. Auto-building an assistant with `chat=True` also uses `[langstage]`
  to stream it as chat frames.
- **New top-level exports**: `agent_toolkit`, `FastDashMiddleware`, `app_prompt`
  (lazy — importing `fast_dash` never drags in the optional extra), alongside the
  existing `RunPython`.
- **`chat_model=`** accepts a model instance or a `"provider:model"` string
  (resolved via `langchain.chat_models.init_chat_model`); env fallback
  `FASTDASH_MODEL`. **`chat_title=`** sets the sidebar panel header.

### Migrating from 0.5.x

| 0.5.x | 0.6.0 |
|---|---|
| `chat_agent=my_agent` | `chat=my_agent` |
| `chat_agent_drive=False` | `chat_tools=("read_app",)` (read-only) |
| `chat_agent_title="Helper"` | `chat_title="Helper"` |
| `chat_agent_position="sidebar"` / `"aside"` | removed — the sidebar is the placement |
| `canvas=True` | `chat=` an agent (or `chat=True`) with the `set_layout` / `set_output` tools |

# Release 0.5.5

## 0.5.5 (2026-07-05)

### Fixed
- **`chat_agent_position="sidebar"` layout.** The wider (420px) sidebar wasn't
  reaching Mantine's AppShell: the `toggle_sidebar` callback reset the navbar to
  `width: 300` on load, so the main content offset and the collapse animation
  were computed from the wrong width. The result was the output area sliding
  *under* the sidebar (right panel clipped off-screen) and the sidebar refusing
  to fully close (a ~120px strip stayed visible). The callback now returns the
  sidebar-chat width, matching the layout, so the offset and collapse-transform
  are consistent — the output fills the space beside the sidebar, and toggling
  the inputs closes it completely. Removed the `--app-shell-navbar-width` CSS
  override that was papering over the mismatch.

# Release 0.5.4

## 0.5.4 (2026-07-05)

### Added
- **`chat_agent_position="sidebar"`** places the chat sidecar *inside the left
  inputs sidebar* — stacked under the inputs, always visible — instead of the
  default floating right aside (`"aside"`). The inputs take their natural height
  and the chat fills the rest; the navbar is widened to give it (and its charts)
  room. Good for putting a conversational assistant right next to the controls
  it complements.

# Release 0.5.3

## 0.5.3 (2026-07-05)

### Changed
- **The empty-chat hint fits the app and the mode.** The transcript's
  placeholder was hardcoded to "Ask the assistant to change the output." — which
  reads oddly for a pure `chat=True` app (there is no output to change). It now
  defaults per mode (a conversation for `chat=True`, "change the output" for a
  canvas / sidecar) and is overridable with a new `chat_placeholder=` argument.
  The text is rendered from a `data-placeholder` attribute so it can differ per
  app.

# Release 0.5.2

## 0.5.2 (2026-07-05)

### Bug fixes
- **Chat sidecar `run_app` now renders the outputs, not just the inputs.** When a
  `chat_agent` drove the app (`set_input` + `run_app`), it correctly updated the
  input controls and computed the new outputs — but the outputs stayed hidden
  behind the pre-run "Run to see results" placeholder, so the charts never
  refreshed until the user clicked Run manually. The placeholder
  (`fd-not-run` on `#output-group-col`) was only cleared by a real Run
  (`submit_inputs.n_clicks`), which the sidecar never fires. The drive path now
  clears it on a `run_app` (both the Flask drive reducer and the ASGI
  `set_props` path), so an agent's run refreshes the *view* — the "anything you
  can do, the agent can do" promise holds for outputs too.

# Release 0.5.1

## 0.5.1 (2026-07-04)

### Bug fixes
- **`describe_app()` reports a JSON `type` consistently across app kinds.** A
  static app derived each input's `type` from the callback annotation (a JSON
  type like `"integer"`), but a `DynamicDash` form reported the *component name*
  (`"Slider"`) in the same field — so a headless agent reading `type` got two
  different vocabularies. `DynamicDash` now reports the JSON type too, with the
  component name always in `tag` (as on a static app). (#131)
- **`Optional[T]` inputs report `T`'s type, not `"string"`.** An
  `Optional[int]` / `int | None` parameter collapsed to `type: "string"` because
  the raw `Union` wrapper isn't in the type map. The wrapper is now unwrapped to
  its single non-`None` member, so an optional input advertises the type it
  actually accepts (`integer` / `number` / `boolean`). (#132)
- **Date/datetime input defaults are surfaced, not dropped.** A `DateInput` /
  timestamp built from a `datetime.date` / `datetime.datetime` default reported
  `default: null` (the default-handling branch didn't match a date object). It
  now surfaces the ISO string the DatePicker emits, keeping the time component
  for a `datetime`. (#134)
- **Docs: MCP tool examples use keyword arguments.** The flagship `invoke` /
  `set_form` snippets in the README and the AI-agents guide showed
  `invoke({...})` / `set_form([...])`, omitting the required `inputs=` / `specs=`
  keyword the tools expect. (#137)

Same contract-correctness class as #110 / #116 / #120 / #126.

# Release 0.5.0

## 0.5.0 (2026-07-03)

### Features
- **Native chat mode (`chat=True`)**: turn a callback into a streaming chat app
  — a bottom-anchored composer, a scrolling transcript, per-session history, and
  a provider-neutral frame grammar (`content` / `reasoning` / `tool_start` /
  `tool_end` / `artifact` / `interrupt` / `error`). No LLM SDK is bundled.
- **LangGraph agents**: `chat=True` also accepts a compiled LangGraph graph or a
  `"module:attr"` spec string (via `fast-dash[langstage]`), with multi-turn
  memory on the graph's checkpointer and human-in-the-loop interrupts.
- **The canvas (`canvas=True`)**: a live, assistant-built output region beside the
  transcript — a conversational DynamicDash the model builds and mutates with
  `canvas` / `set_props` frames. `chat_drawer=True` gives an app-first layout.
- **Chat sidecar (`chat_agent=`)**: mount an independent chat agent on a *normal*
  Fast Dash app. The agent reads the app's live inputs (`ctx.inputs`,
  `ctx.input_specs`) and drives it (`set_input` / `run_app` frames, or the
  `app_tool_specs()` / `apply_tool_call()` LLM on-ramp) — anything a user can do,
  the agent can do. `chat_agent_drive=False` makes it read-only.
- **Driving chat over MCP**: `mcp_server=True` exposes a chat app's `describe_app`
  / `invoke` contract so a headless agent sees and drives it like a browser user.
- **UI refresh**: a first-class `accent=` colour, an enriched Mantine theme,
  docstring-derived input help captions, skeleton loaders, a pre-run empty state,
  a sidecar drive affordance (agent-set inputs flash, the output pulses),
  streaming caret, code-copy buttons, mobile sheet + a11y (aria-labels, focus,
  reduced-motion). Dropped the unused FontAwesome stylesheet.

### Security
- **Password inputs are never exposed to a sidecar agent**: a `PasswordInput`'s
  value is redacted from `ctx.inputs`, omitted from the contract, and `set_input`
  on it is refused — while the app still runs with the real value.

# Release 0.2.14

## 0.2.14 (2025-09-22)

### Bug Fixes
- **Automatic updates with no arguments**: Fixes behavior of callback execution when it has no arguments.

# Release 0.2.13

## 0.2.13 (2025-07-01)

### Bug Fixes
- **Disable websockets**: Default behavior is disabled websockets so server deployments are faster.

# Release 0.2.12

## 0.2.12 (2025-06-29)

### Improvements
- **Dependencies**: `fastdash` CLI can also be configured with a port number
- **Testing**: Modify text streaming test to use `update` function correctly

### Bug Fixes
- **Stream handler**: Fix stream handler to use notification=False by default

# Release 0.2.11

## 0.2.11 (2025-06-26)

### Features
- **CLI**: Add CLI project creation functionality and register script entry point
- **Notifications**: Add notify function and integrate notification handling in FastDash class
- **Callbacks**: Refactor component selection and enhance FastDash class with callback attribute for easier app interactions
- **Branding**: Add option to disable FastDash branding in the app
- **Streaming**: Add streaming functionality with socket.io support and loader support to FastDash components
- **Chat**: Enhance Chat component with streaming support, partial updates, and artifacts (Plotly figures, images, matplotlib, pandas, text)

### Improvements
- **Dependencies**: Update dependencies and improve component configurations for compatibility
- **Components**: Replace dcc.Dropdown with dmc.Select and dmc.MultiSelect for improved component handling
- **Testing**: Implement polling mechanism and improve synchronization in streaming tests

### Bug Fixes
- **Component Data**: Fix component data handling in _get_component_from_input and update tests
- **Dependencies**: Remove unused default properties for DateRangePicker and Prism components

# Release 0.2.10

## 0.2.10 (2025-02-16)

### Fixes

- Upgrade Poetry to 0.2.10
- Fix: Solve issue when building apps directly from the terminal. @https://github.com/dkedar7/fast_dash/issues/58

# Release 0.2.9

## 0.2.9 (2024-02-24)

### Fixes

- Fix: In case of no input arguments, sidebar either freezes or becomes unresponsive.
- Fix: When `update_live` is set to `True`, the app fails to reload dynamically.

# Release 0.2.8

## 0.2.8 (2023-12-10)

### Features

- On mobile layouts, automatically close sidebars when submit is clicked. Thank you @seanbearden for the issue.
- New examples in the documentation.
- Added some new examples to README.

### Fixes

- Set image component width to 100%.
- Fix: If input is None, it's not automatically transformed.

## 0.2.7 (2023-10-18)

### Features

- New component: `Table`
- - Fast components are callable to update attributes. For example, to update the `page_size` attribute of `Table`, do `Table(page_size=20)`. At the same time, Fast Components can also be used as non-callable objects.
- Pandas DataFrame is rendered as a `Table`.
- "About" button displays the function docstring in parse markdown. New utility function to extract function docstring has been incorporated for this feature. This is, however, still experimental.
- Documentation upates, new "Usage Patterns" page.
- New tests.
- Fast Dash now supports Python 3.11.

### Deprecations

- Support for Python 3.7 has been deprecated.

## 0.2.6 (2023-09-04)

### Features

- New chat component! Setting the output data type to `Chat` and returning a dictionary displays a chat component.
- Introduced a transformation step before passing inputs to the callback. This allows converting non-native inputs to native data types. For example, passing a PIL.Image as input data tyoe hint doesn't need converting it to a base64 string.
- Errors are displayed as notifications.
- Updated documentation and tests. 

## 0.2.5 (2023-08-13)

### Improvements

- Fix: `update_live` is automatically set to `True` if the callback function doesn't require any inputs.

## 0.2.4 (2023-08-12)

### Improvements

- Improve responsiveness on mobile views.
- `outputs` argument overrides callback function output hints.
- Improve pytest coverage.

## 0.2.3 (2023-08-01)

### Features

- Dash components can be used as type hints directly. They are converted to Fast components during app initialization.
- Added a mosaic layout example to README.
- `dash` can be imported from `fast_dash` like this: `from fast_dash import dash`.

## 0.2.2 (2023-07-26)

### Features

- New example: Chat over docs with Embedchain.

### Improvements

- Squashed a bug that was preventing the submit and reset buttons to sync with each other. The result is a more stable deploy using callback context.

## 0.2.1 (2023-07-23)

### Features

- Infer output labels from the callback function or specify the `output_labels`` argument
- Show overlay when loading outputs
- Use dmc.Burger icon instead of open, close icons. Allows for a clearner sidebar open/close UX
- New examples

### Improvements

- [Bug] Components are now initialized with the desired height
- Sidebar collapse burger is not supported in minimal layout
- Replace branding text with icon
- New pytests to improve coverage

## 0.2.0 (2023-07-02)

### Features

- Enable sidebar layout.
- Mosaic to build custom layouts.
- Collapsible sidebar.

### Improvements

- Sidebar layout improvements to allow flex sizing of components.
- Unit test updates to support the latest tox and poetry versions.

## 0.1.7 (2022-08-21)

* Introduce Fast Dash decorator (`fastdash`) for automatic and quick deployment.
* Autoinfer input and output components from type hints and default values.
* Autoinfer title and subheader by inspecting the callback function.
* New test cases.
* Modified documentation layout and content.
* New GitHub Actions workflow to publish documentation only.

## 0.1.6 (2022-05-09)

* Navbar and footer are not thinner than before, which makes them less distracting ;)
* They no longer stick to the top and bottom respectively. Scrolling on the page makes the navbar dissappear!
* Update live: New live update option! Setting the argument `update_live=True` removes `Submit` and `Clear` buttons. Any action updates the app right away.
* New spinners: Finally, Fast Dash now has loading spinners to indicate loading outputs. This comes in handy when executing long running scripts.

## 0.1.5 (2022-04-02)

* Add examples: Object detection, molecule 3D viewer and UI updates to the existing examples.
* Easier fastification: Fastify now allows using a complete Dash component as the first argument.
* Tests: Increase pytest coverage to 95%.

## 0.1.4 (2022-03-21)

* New component property allows setting "acknowledgment" component!
* Default app title is 'Prototype'.
* New UploadImage component uses another html.Img component as acknowledgment.
* Added a new Neural Style Transfer example.
* Added examples to pytest cases.

## 0.1.3 (2022-03-11)

* Added 3 new examples.
* Make `navbar` and `footer` removable from the app UI.
* Updated documentation structure.
* Added Google Cloud Run deployment docs.

## 0.1.2 (2022-03-06)

* Supports usage of the same FastComponent multiple times via deepcopy.
* Correct documentation typos and examples.
* Added text-to-text examples.
* Modifications to the Fastify component.

## 0.1.1 (2022-02-28)

* First wide release.
* Adding input, output image functionality.
* Added mkdocs documentation.

## 0.1.0 (2022-01-29)

* First release on PyPI.