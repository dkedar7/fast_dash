# Patterns reference

Each pattern is a complete, runnable example.

## 1. Single function, hello world

```python
from fast_dash import fastdash

@fastdash
def greet(name: str = "world") -> str:
    return f"Hello, {name}!"
```

## 2. Multiple inputs

```python
from fast_dash import fastdash

@fastdash
def describe(text: str, count: int = 3) -> str:
    """Repeat text `count` times."""
    return " · ".join([text] * count)
```

## 3. Multiple outputs with mosaic layout

Mosaic strings are ASCII art. Each letter = one output, in order.

```python
from fast_dash import fastdash, Graph
import plotly.express as px

@fastdash(mosaic="AB\nAC")
def dashboard(rows: int = 100) -> (Graph, Graph, Graph):
    df = px.data.iris().head(rows)
    return (
        px.scatter(df, x="sepal_width", y="sepal_length", color="species"),
        px.histogram(df, x="petal_width"),
        px.box(df, y="petal_length", color="species"),
    )
```

## 4. Cascading inputs (depends_on)

Child dropdown options/values derived from parent's current value.

```python
from fast_dash import fastdash, depends_on

countries = {
    "USA": ["California", "Texas", "New York"],
    "India": ["Maharashtra", "Karnataka", "Delhi"],
}

@fastdash
def pick_state(
    country: str = list(countries),
    state: str = depends_on("country", lambda c: countries[c]),
) -> str:
    return f"{state}, {country}"
```

The resolver receives the parent's current value. Return:
- a **list** → sets the dependent dropdown's options (clears value)
- a **dict** `{"data": [...], "value": ...}` → sets both
- a **scalar** → sets only the value

## 5. Multi-function tabs

Each function = one tab with its own inputs/outputs/callback.

```python
from fast_dash import FastDash

def greet(name: str) -> str:
    return f"Hello, {name}!"

def add(a: int, b: int) -> int:
    return a + b

FastDash(
    callback_fn=[greet, add],
    tab_titles=["Greeter", "Adder"],   # optional; defaults to function names
).run()
```

## 6. Multi-step pipeline

Wire step N+1's input to step N's output via `from_step`.

```python
from fast_dash import FastDash, from_step
import pandas as pd

def load_data(rows: int = 100) -> pd.DataFrame:
    """Load a sample dataset."""
    return pd.DataFrame({"x": range(rows), "y": [i * 2 for i in range(rows)]})

def double(data=from_step(load_data)) -> pd.DataFrame:
    """Double every value."""
    return data * 2

def summarise(data=from_step(double), prefix: str = "Result:") -> str:
    """One-line summary. User can customise the prefix."""
    return f"{prefix} {len(data)} rows, sum={data.values.sum()}"

FastDash(steps=[load_data, double, summarise], title="Pipeline").run()
```

Each step shows one at a time with Run / Back / Next. Steps can mix `from_step` params (no UI) with regular UI params (like `prefix` above).

## 7. from_step with transform

Apply a function before passing the cached value downstream.

```python
from fast_dash import FastDash, from_step
import pandas as pd

def load_data(rows: int = 100) -> pd.DataFrame:
    return pd.DataFrame({"x": range(rows), "y": [i ** 2 for i in range(rows)]})

def show_columns(
    columns=from_step(load_data, transform=lambda df: list(df.columns)),
) -> str:
    return f"Columns: {columns}"

FastDash(steps=[load_data, show_columns]).run()
```

## 8. Notebook rendering

```python
@fastdash(mode="inline", title="My App")
def app(x: int = 5) -> int:
    return x ** 2
```

Modes: `"inline"` (embedded), `"jupyterlab"` (new tab in JupyterLab), `"external"` (separate browser tab).

## 9. Live updates (no Run button)

```python
@fastdash(update_live=True)
def square(x: int = 5) -> int:
    return x ** 2
```

Output re-renders on every input change. For functions with zero inputs, `update_live=True` is set automatically.

## 10. Skip the decorator

For full control of the app lifecycle:

```python
from fast_dash import FastDash

def my_fn(x: int) -> int:
    return x * 2

app = FastDash(callback_fn=my_fn, title="Doubler", port=8050)
app.run()
```

## 11. Streaming outputs

Set `stream=True` and `yield` partial results: each yielded value replaces the output as it arrives, and the last one is the result. Yield a tuple to stream several outputs at once.

```python
import time
from fast_dash import FastDash

def slow_count(n: int = 3) -> str:
    out = ""
    for i in range(1, n + 1):
        out += f"tick {i}
"
        time.sleep(0.2)
        yield out

FastDash(callback_fn=slow_count, stream=True).run()
```

To push from a regular function instead, call `update(name, data)` and `return` the final value. `name` is the returned variable's name (`"output"` below); the `output_`-prefixed id that `describe_app` reports (`"output_output"`) works too.

```python
from fast_dash import FastDash, update

def stream_text(input_text: str = "hi") -> str:
    output = ""
    for char in "This is the expected output.":
        output += char
        update("output", output)      # push the text so far
    return output

FastDash(callback_fn=stream_text, stream=True).run()
```

Without `stream=True` a generator still works: it runs to completion and shows the last value. An MCP agent's `invoke()` always gets the last value. Use `notify(data, action="show")` to push a toast mid-run. For token-by-token chat, use `chat=True` (see the chat docs) rather than a `Chat` output.

## 12. Custom Dash components via Fastify

```python
from fast_dash import fastdash, Fastify
from dash import dcc

bounded_slider = Fastify(dcc.Slider(min=0, max=100, value=50), "value")

@fastdash
def app(x: bounded_slider) -> str:
    return f"You picked {x}"
```

## Useful decorator options

| Option | Default | Effect |
|---|---|---|
| `title` | function name | App title |
| `mosaic` | auto-grid | ASCII layout for multiple outputs |
| `theme` | `"JOURNAL"` | Bootswatch name (dark themes auto-flip dark mode) |
| `port` | `8080` | Server port |
| `mode` | `None` | `"inline"`, `"jupyterlab"`, `"external"` |
| `update_live` | `False` | Re-run on every change |
| `about` | `True` | Docstring → About modal; pass a string to override |
| `minimal` | `False` | Hide chrome for embedding |
| `stream` | `False` | Enable streaming outputs |
