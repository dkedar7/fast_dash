# Gotchas and non-obvious behavior

## 1. `@fastdash` starts the server on import

The decorator launches the server as a side effect of import. If the module is imported elsewhere (tests, other scripts), the server starts there too.

**Fix:**
```python
if __name__ == "__main__":
    @fastdash
    def my_app(...): ...
```

Or use the class form and call `.run()` explicitly:
```python
from fast_dash import FastDash
def my_fn(...): ...
app = FastDash(callback_fn=my_fn)
if __name__ == "__main__":
    app.run()
```

## 2. Output labels come from the source code of the `return` line

Fast Dash inspects the source to name outputs. Two failure modes:

- **REPL / `exec` / frozen environments** → falls back to `OUTPUT_1`, `OUTPUT_2`. App still works.
- **f-string returns** → labels can be garbled. Pass `output_labels=["Nice name"]` to override.

## 3. Shared component instances mutate each other

```python
# BAD — one shared instance
my_text = Text
@fastdash(inputs=my_text, outputs=my_text)   # subtle bugs
def app(x): return x

# GOOD — pass the class, Fast Dash creates fresh instances
@fastdash(inputs=Text, outputs=Text)
def app(x): return x
```

## 4. `theme` does not restyle Mantine chrome (v0.2.x)

Since the UI overhaul, the chrome (header, navbar, buttons, inputs) is Mantine. Bootswatch `theme=` only affects:
- Dark / light mode flip for known dark names (`CYBORG`, `DARKLY`, `QUARTZ`, `SLATE`, `SOLAR`, `SUPERHERO`, `VAPOR`)
- `dbc`-rendered bits like Tables

Per-theme accent colors / fonts (e.g. JOURNAL's orange serif) do **not** propagate to the Mantine layer. If a user expects different Bootswatch themes to look different, set their expectations early.

## 5. Jupyter: server + port conflicts across cells

Each cell that calls `@fastdash` or `FastDash().run()` starts a server on port `8080` by default. Re-running a cell usually replaces the previous server, but if you're launching multiple apps, pass distinct `port=` values.

Use `mode="inline"` in notebooks so the app renders in the cell output.

## 6. `from_step` defaults must point to *a function object in the same `steps=` list*

```python
def a(x: int = 1) -> int: return x * 2
def b(y=from_step(a)) -> int: return y + 10

FastDash(steps=[a, b]).run()        # OK — a is in steps
FastDash(steps=[b]).run()           # FAILS — a is not in steps
```

## 7. `depends_on` parent must be a parameter of the *same function*

```python
@fastdash
def app(
    country: str = list(COUNTRIES),
    state: str = depends_on("country", resolver),   # OK — "country" is a param
):
    ...
```

Referencing a parameter from a different function (in multi-function or steps mode) will not wire up.

## 8. Modern type hints: prefer built-in generics

Python 3.9+ `list[int]`, `dict[str, int]`, etc. work. `typing.List`, `typing.Dict` also work for back-compat. `Optional[T]`, `Union[T, None]`, and `T | None` all treated as nullable-T.

## 9. The `Run` button (previously `Submit`)

As of v0.2.16 the submit button is labeled **Run**. Component ID `submit_inputs` is unchanged — tests and custom callbacks keep working.

## 10. Docstrings become the About modal

The first docstring of the decorated function becomes the "About" modal content. Supports Markdown + NumPy-style parameter tables. Disable with `about=False`, override with `about="Custom markdown"`.

## 11. Python version support

Fast Dash v0.2.16 supports **Python 3.11 – 3.14**. 3.9 and 3.10 are dropped.

## 12. Multi-function mode IDs are prefixed

Inputs/outputs in a multi-function app get IDs like `func0_text`, `func1_text`. If a user writes a custom callback referencing these, they must use the prefixed form.
