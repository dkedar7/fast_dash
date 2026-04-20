---
name: fast-dash
description: Build a Fast Dash web app from a Python function. Use when the user wants to turn a function into an interactive app, add a UI to an existing function, or build a dashboard / form / wizard. Fast Dash infers UI components from type hints, so a well-typed function becomes an app with one decorator.
---

# Fast Dash

Fast Dash turns a Python function into a Plotly Dash web app. The `@fastdash` decorator reads the function's signature, maps each parameter's type hint to a UI component, maps the return type to an output component, and serves the result. No frontend, no callbacks, no boilerplate.

## When to use this skill

Use this skill when the user:
- has a Python function and wants a UI for it ("make this a web app", "add a form", "dashboard around this")
- is prototyping an ML / data / API tool and wants shareable interactivity
- needs cascading inputs, a multi-step wizard, or multiple tools in one app

Do **not** use this for: production apps with complex routing, custom auth, or non-Python frontends — Fast Dash is opinionated for the single-file-Python-function use case.

## Install

```bash
pip install fast-dash
```

## The core pattern

```python
from fast_dash import fastdash

@fastdash
def greet(name: str = "world") -> str:
    return f"Hello, {name}!"

# Serving on http://127.0.0.1:8080
```

That is the whole app. Open the URL, type a name, click **Run**.

## How to approach a Fast Dash task

1. **Start from the user's function.** If they don't have one, write the smallest function that captures their intent.
2. **Add type hints and defaults.** This is where the UI comes from — `int` → number input, `bool` → checkbox, `str` with a list default → dropdown, etc. See [references/components.md](references/components.md) for the full table.
3. **Decorate with `@fastdash`.** For more control (tabbed multi-function apps, multi-step pipelines), use the `FastDash(...)` class directly.
4. **Run and verify.** The decorator starts a server immediately on import. For notebooks, pass `mode="inline"`.

## Common patterns

| Pattern | Syntax | When |
|---|---|---|
| Single function | `@fastdash` | One tool, one form |
| Multiple outputs | `-> (Graph, Graph)` + `mosaic="AB"` | Dashboard with several plots |
| Cascading inputs | `state=depends_on("country", resolver)` | Dependent dropdowns |
| Multiple tools, one app | `FastDash([fn_a, fn_b], tab_titles=[...])` | Tabbed "apps" under one URL |
| Multi-step wizard | `FastDash(steps=[fn_a, fn_b, fn_c])` + `from_step(prev_fn)` | Pipeline UX, one panel at a time |
| Streaming outputs | `update("output_x", chunk)` inside the fn + `stream=True` | LLM / token-by-token / progress |
| Notebook rendering | `@fastdash(mode="inline")` | Jupyter |
| Wrap a custom component | `Fastify(dcc.Slider(...), "value")` | Any Dash component |

Full examples for each: [references/patterns.md](references/patterns.md).

## Type hint → component quick reference

| Hint | Component |
|---|---|
| `str` | Textarea |
| `int`, `float` | Number input |
| `bool` | Checkbox |
| `Literal["a", "b"]` | Dropdown |
| `Annotated[int, range(0, 100)]` | Slider |
| `list` | Multi-select |
| `datetime.date` | Date picker |
| `pd.DataFrame` (return) | Table |
| `plotly.graph_objects.Figure` (return) | Plotly chart |
| `PIL.Image.Image` | Image upload / display |

Full table with every supported hint: [references/components.md](references/components.md).

## Built-in components to import

Pass these directly as `inputs=` or `outputs=` when you want to override inference:

```python
from fast_dash import (
    # Inputs
    Text, TextArea, PasswordInput,
    NumberInput, Slider,
    Switch, MultiSelect,
    DateInput, DateRange, ColorInput,
    Upload, UploadImage,
    # Outputs
    Graph, Image, Table, Markdown, Chat, Download,
)
```

For streaming and building custom UIs, also available:

```python
from fast_dash import (
    Fastify,           # wrap any Dash component as a Fast Dash component
    depends_on,        # cascading input default
    from_step,         # multi-step pipeline data threading
    update, notify,    # push partial results / toasts during streaming
    dcc, dbc, dmc, html,  # re-exported: dash.dcc, dash_bootstrap_components, dash_mantine_components, dash.html
)
```

## Non-obvious things that will bite you

- **`@fastdash` starts the server on import.** Put it in a `if __name__ == "__main__":` guard if the file is imported elsewhere, or skip the decorator and use `FastDash(...).run()`.
- **Default Bootswatch `theme=` does not restyle Mantine chrome** (v0.2.x). Only dark/light flips for known dark themes (`CYBORG`, `DARKLY`, `SLATE`, ...).
- **Don't reuse a single component instance across inputs and outputs** — pass the class (`inputs=Text`) not an instance. Mutation surprises.
- **Output labels come from the `return` line of the source.** REPL / `exec` contexts fall back to `OUTPUT_1`, `OUTPUT_2`. Pass `output_labels=[...]` to override.

Full list with reproducers: [references/gotchas.md](references/gotchas.md).

## Decision tree

- User has **one function, simple form** → `@fastdash` on the function, done.
- User has **one function, multiple outputs** → `@fastdash(mosaic="AB\nAC")`, return a tuple of components.
- User has **multiple independent tools** → `FastDash([fn_a, fn_b], tab_titles=[...]).run()`.
- User has **a pipeline (step 1 output feeds step 2)** → `FastDash(steps=[fn_a, fn_b, ...]).run()` with `from_step(prev_fn)` defaults.
- User has **dependent dropdowns** → `depends_on("parent_name", resolver)` as a default value.
- User wants **streaming / token-by-token output** (LLMs, progress) → call `update(component_id, data)` inside the function + `stream=True` on the app.
- User wants the app **in a Jupyter notebook** → add `mode="inline"`.
- User wants to **not start the server immediately** → use `FastDash(...)` class, skip `.run()`.

## Before reporting complete

Run the app and verify it loads. If you can't open a browser:
- check the console for tracebacks
- confirm the port (default `8080`) is free
- for notebooks, confirm `mode="inline"` was set

If the user has dash[testing] installed, a headless smoke test is worthwhile. Otherwise, ask the user to verify the UI themselves.
