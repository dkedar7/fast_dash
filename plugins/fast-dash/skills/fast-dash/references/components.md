# Components reference

## Input inference (parameter type hint → component)

| Type hint | Default value | Component |
|---|---|---|
| `str` | *(any or none)* | Textarea |
| `str` | `["a", "b", "c"]` | Single-select dropdown |
| `int` | *(any)* | Number input |
| `int` | `range(0, 100)` | Slider |
| `float` | *(any)* | Number input |
| `float` | `range(0, 10)` | Slider |
| `bool` | `True` / `False` | Checkbox |
| `list` | `[...]` | Multi-select dropdown (from the values) |
| `dict` | `{"a": 1, "b": 2}` | Multi-select dropdown (keys are options, values ignored) |
| `datetime.date` | — | Date picker |
| `PIL.Image.Image` | — | Image upload |
| `Literal["a", "b", "c"]` | — | Single-select dropdown |
| `enum.Enum` subclass | — | Single-select dropdown |
| `Annotated[int, range(0, 100)]` | — | Slider |
| `Annotated[str, ["a", "b"]]` | — | Dropdown |
| `Optional[T]` | — | As `T`, nullable |
| Fast Dash component class (e.g. `Slider`) | — | Used directly |
| Any Dash component instance | — | Used directly |

Unknown hints fall back to text input.

## Output inference (return type hint → component)

| Return type | Component |
|---|---|
| `str`, `int`, `float`, `bool` | Text (`<h1>`) |
| `pd.DataFrame` | Table |
| `PIL.Image.Image` | Image |
| `matplotlib.figure.Figure` | Image |
| `plotly.graph_objects.Figure` | Plotly chart |
| `"plotly.graph_objects.Figure"` (string forward-ref) | Plotly chart |
| `"go.Figure"` / `"Figure"` | Plotly chart |
| Tuple of types | Multiple outputs, one component each |
| Fast Dash output class (`Graph`, `Image`, ...) | Used directly |

## Built-in component exports

All importable from `fast_dash`:

**Inputs:**
- `Text` — single-line text
- `TextArea` — multi-line text
- `PasswordInput` — masked text
- `NumberInput` — numeric with optional bounds
- `Slider` — numeric range picker
- `Switch` — toggle (True / False); uses `component_property="checked"`
- `MultiSelect` — multi-select dropdown
- `DateInput` — single date
- `DateRange` — date range
- `ColorInput` — color picker, returns hex
- `Upload` — file upload
- `UploadImage` — image upload

**Outputs:**
- `Graph` — Plotly chart
- `Image` — PIL / matplotlib / base64 image
- `Table` — DataFrame renderer
- `Markdown` — rendered markdown
- `Chat` — streaming chat history (pair with `stream=True`)
- `Download` — browser download trigger

## Overriding inference

```python
from fast_dash import fastdash, Slider, Graph

@fastdash(
    inputs=[Slider, Slider],   # force two sliders regardless of hints
    outputs=Graph,              # force a Plotly chart output
)
def foo(a, b):
    ...
```

## Wrapping arbitrary Dash components

```python
from fast_dash import Fastify
from dash import dcc

custom_slider = Fastify(dcc.Slider(min=0, max=100, value=50), "value")

@fastdash
def app(x: custom_slider) -> str:
    return f"You picked {x}"
```

`Fastify(component, component_property, label_=..., ack=...)` — the second arg is the Dash prop the input/output value lives on.
