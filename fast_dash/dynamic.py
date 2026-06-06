"""Dynamic UI generation for fast_dash.

A sibling to :class:`FastDash` whose input form is generated at runtime,
either by a "router" control whose value reshapes the form (form-driven)
or by an external agent pushing a UI spec via MCP (see
:mod:`fast_dash.mcp`'s ``set_form`` tool).

The public surface is :class:`DynamicDash`, :func:`render_spec`, and
:data:`COMPONENT_REGISTRY`. The thin UI-spec DSL is documented on
:func:`render_spec`.

Pattern-matching ids embed the read-back property in the id dict so
heterogeneous inputs (Slider, Switch, Upload) coexist under one ``ALL``
selector:

    {"role": "dyn-input", "name": "<param>", "prop": "value" | "checked" | "contents"}
"""

from __future__ import annotations

import copy
import inspect
from typing import Any, Callable, Iterable

import dash
import dash_mantine_components as dmc
from dash import ALL, Input, Output, State, dcc, html, no_update
from dash_iconify import DashIconify

from fast_dash.Components import (
    ColorInput,
    DateInput,
    DateRange,
    Markdown,
    MultiSelect,
    NumberInput,
    PasswordInput,
    Slider,
    Switch,
    Text,
    TextArea,
    Upload,
    UploadImage,
)
from fast_dash.utils import Fastify


__all__ = [
    "COMPONENT_REGISTRY",
    "DynamicDash",
    "render_spec",
]


Select = Fastify(
    component=dmc.Select(placeholder="Select an option"),
    component_property="value",
    tag="Text",
)


COMPONENT_REGISTRY: dict[str, Any] = {
    "Text": Text,
    "TextArea": TextArea,
    "NumberInput": NumberInput,
    "Slider": Slider,
    "Select": Select,
    "MultiSelect": MultiSelect,
    "Switch": Switch,
    "DateInput": DateInput,
    "DateRange": DateRange,
    "ColorInput": ColorInput,
    "PasswordInput": PasswordInput,
    "Markdown": Markdown,
    "Upload": Upload,
    "UploadImage": UploadImage,
}


def _humanize(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").strip().title()


def _spec_to_component(spec: dict) -> Any:
    """Instantiate a FastComponent from a single UI spec dict.

    The returned component carries a dict id of the shape
    ``{"role": "dyn-input", "name": <name>, "prop": <component_property>}``
    so the Run callback can read it back under a homogeneous-property pool.
    """
    if not isinstance(spec, dict):
        raise TypeError(f"Spec entries must be dicts, got {type(spec).__name__}")

    name = spec.get("name")
    type_ = spec.get("type")
    if not name:
        raise ValueError(f"Spec missing required 'name': {spec!r}")
    if type_ not in COMPONENT_REGISTRY:
        raise ValueError(
            f"Unknown component type {type_!r} for field {name!r}. "
            f"Allowed: {sorted(COMPONENT_REGISTRY)}"
        )

    factory = COMPONENT_REGISTRY[type_]
    props = dict(spec.get("props") or {})
    # Pass props through Fastify.__call__ → deep-copies the component and
    # setattrs each kwarg, which Dash picks up as a prop override.
    comp = factory(**props) if props else copy.deepcopy(factory)

    initial = spec.get("value")
    if initial is not None:
        setattr(comp, comp.component_property, initial)

    comp.id = {
        "role": "dyn-input",
        "name": name,
        "prop": comp.component_property,
    }
    comp.label_ = spec.get("label") or _humanize(name)
    return comp


def render_spec(specs: Iterable[dict], container_id: str = "dyn-form") -> html.Div:
    """Render a list of UI specs into a Dash container.

    Spec shape::

        {
            "name": "<param>",     # required, id key + callback kwarg
            "type": "Slider",       # required, key in COMPONENT_REGISTRY
            "label": "Optional",    # falls back to title-cased name
            "value": 0.5,           # optional initial value
            "props": {"min": 0, "max": 1, "step": 0.05}  # forwarded to inner Dash component
        }

    Pure function; no callback registration. Reused by the parent-control
    resolver callback inside :class:`DynamicDash` and by the MCP
    ``set_form`` tool.
    """
    specs = list(specs or [])
    groups = []
    for spec in specs:
        comp = _spec_to_component(spec)
        groups.append(
            dmc.Stack(
                [
                    dmc.Text(comp.label_, size="sm", fw=500),
                    comp,
                ],
                gap=4,
            )
        )
    return html.Div(groups, id=container_id)


def _prepare_output(comp: Any, idx: int) -> Any:
    out = copy.deepcopy(comp)
    out.id = f"dyn-output-{idx}"
    if getattr(out, "component_property", None) is None:
        out.component_property = "children"
    return out


class DynamicDash:
    """A Dash app whose input form is generated at runtime.

    Two ways to drive the form:

    * **Form-driven**: supply ``parent_control`` + ``spec_resolver``. The
      parent control is statically rendered; its value flows into the
      resolver, whose returned list of specs becomes the form's children.

    * **MCP-driven**: an external agent (Claude Code, Cursor, …) calls
      the ``set_form`` MCP tool with a spec list; the running app
      re-renders. See :mod:`fast_dash.mcp` for the agent surface.

    A "Run" button gathers all dynamic input values into a kwargs dict
    and invokes ``callback_fn``. Outputs are written into
    ``output_components``.
    """

    def __init__(
        self,
        callback_fn: Callable,
        initial_specs: list[dict] | None = None,
        parent_control: dict | None = None,
        spec_resolver: Callable[[Any], list[dict]] | None = None,
        output_components: list | None = None,
        title: str = "Dynamic Dash",
        **dash_kwargs,
    ):
        if parent_control is not None and spec_resolver is None:
            raise ValueError(
                "parent_control was given but spec_resolver is None — "
                "supply a callable that maps parent value → list of specs."
            )

        self.callback_fn = callback_fn
        self.initial_specs = list(initial_specs or [])
        self.parent_control = parent_control
        self.spec_resolver = spec_resolver
        self.output_components = list(output_components or [])
        self.title = title

        sig = inspect.signature(callback_fn)
        self._has_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        self._callback_param_names = {
            name
            for name, p in sig.parameters.items()
            if p.kind
            not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
        }

        self._outputs_with_ids = [
            _prepare_output(c, i) for i, c in enumerate(self.output_components)
        ]

        self.app = dash.Dash(
            __name__,
            external_stylesheets=dash_kwargs.pop("external_stylesheets", []),
            suppress_callback_exceptions=True,
            **dash_kwargs,
        )
        self.app.title = title
        self.app.layout = self._build_layout()
        self._register_callbacks()

    def _build_parent_control(self):
        if self.parent_control is None:
            return None
        spec = dict(self.parent_control)
        type_ = spec.get("type")
        if type_ not in COMPONENT_REGISTRY:
            raise ValueError(
                f"parent_control has unknown type {type_!r}. "
                f"Allowed: {sorted(COMPONENT_REGISTRY)}"
            )
        factory = COMPONENT_REGISTRY[type_]
        props = dict(spec.get("props") or {})
        comp = factory(**props) if props else copy.deepcopy(factory)
        initial = spec.get("value")
        if initial is not None:
            setattr(comp, comp.component_property, initial)
        comp.id = "dyn-parent"
        label = spec.get("label") or _humanize(spec.get("name") or "Choose")
        return dmc.Stack(
            [dmc.Text(label, size="sm", fw=600), comp],
            gap=4,
        ), comp

    def _build_layout(self):
        parent_pack = self._build_parent_control()
        if parent_pack is not None:
            parent_block, parent_comp = parent_pack
            self._parent_prop = parent_comp.component_property
        else:
            parent_block = None
            self._parent_prop = None

        navbar_children = []
        if parent_block is not None:
            navbar_children.append(parent_block)
            navbar_children.append(dmc.Divider())

        navbar_children.extend(
            [
                dmc.Text("Inputs", size="sm", c="dimmed"),
                render_spec(self.initial_specs, container_id="dyn-form"),
                dmc.Button(
                    "Run",
                    id="dyn-run",
                    n_clicks=0,
                    fullWidth=True,
                    mt="md",
                    leftSection=DashIconify(icon="mdi:play", width=16),
                ),
            ]
        )

        main_children = []
        if self._outputs_with_ids:
            main_children.append(dmc.Stack(self._outputs_with_ids, gap="md"))
        else:
            main_children.append(
                dmc.Text("(no output components configured)", c="dimmed")
            )

        return dmc.MantineProvider(
            dmc.AppShell(
                [
                    dmc.AppShellHeader(
                        dmc.Group(
                            [
                                DashIconify(icon="mdi:auto-fix", width=22),
                                dmc.Text(self.title, fw=600, size="lg"),
                            ],
                            gap="xs",
                            p="md",
                        )
                    ),
                    dmc.AppShellNavbar(
                        dmc.ScrollArea(
                            dmc.Stack(navbar_children, gap="sm", p="md"),
                        ),
                    ),
                    dmc.AppShellMain(
                        dmc.Stack(main_children, gap="md", p="md"),
                    ),
                    # MCP set_form pushes spec lists here; the from_mcp callback
                    # below re-renders the form.
                    dcc.Store(id="_mcp_spec_store"),
                ],
                header={"height": 56},
                navbar={"width": 340, "breakpoint": "sm"},
                padding="md",
            )
        )

    def _register_callbacks(self):
        app = self.app

        # ----- (i) parent control → form (form-driven) -----------------------
        if self.parent_control is not None and self.spec_resolver is not None:
            resolver = self.spec_resolver

            @app.callback(
                Output("dyn-form", "children"),
                Input("dyn-parent", self._parent_prop),
                prevent_initial_call=False,
            )
            def reshape_from_parent(parent_value):
                if parent_value is None:
                    return no_update
                try:
                    specs = resolver(parent_value)
                except Exception:
                    return no_update
                try:
                    return render_spec(specs).children
                except Exception:
                    return no_update

        # ----- (ii) MCP set_form → form (agent-driven) -----------------------
        # An external agent calls the set_form MCP tool, which pushes a spec
        # list into the _mcp_spec_store via socket.io. This callback re-renders
        # the form from those specs.
        @app.callback(
            Output("dyn-form", "children", allow_duplicate=True),
            Input("_mcp_spec_store", "data"),
            prevent_initial_call=True,
        )
        def reshape_from_mcp(specs):
            if not specs:
                return no_update
            try:
                return render_spec(specs).children
            except Exception:
                return no_update

        # ----- (iii) Run → invoke callback_fn --------------------------------
        if self._outputs_with_ids:
            outputs = [
                Output(o.id, o.component_property) for o in self._outputs_with_ids
            ]
            n_out = len(outputs)
            parent_name = (
                self.parent_control.get("name") if self.parent_control else None
            )
            parent_prop = self._parent_prop

            base_states = [
                State({"role": "dyn-input", "name": ALL, "prop": "value"}, "value"),
                State(
                    {"role": "dyn-input", "name": ALL, "prop": "checked"}, "checked"
                ),
                State(
                    {"role": "dyn-input", "name": ALL, "prop": "contents"},
                    "contents",
                ),
                State({"role": "dyn-input", "name": ALL, "prop": "value"}, "id"),
                State({"role": "dyn-input", "name": ALL, "prop": "checked"}, "id"),
                State({"role": "dyn-input", "name": ALL, "prop": "contents"}, "id"),
            ]
            if parent_name:
                base_states.append(State("dyn-parent", parent_prop))

            @app.callback(
                outputs,
                Input("dyn-run", "n_clicks"),
                *base_states,
                prevent_initial_call=True,
            )
            def run_callback(n_clicks, *states):
                if not n_clicks:
                    return [no_update] * n_out

                (
                    vals_value,
                    vals_checked,
                    vals_contents,
                    ids_value,
                    ids_checked,
                    ids_contents,
                    *rest,
                ) = states

                kwargs: dict[str, Any] = {}
                for v, idd in zip(vals_value, ids_value):
                    kwargs[idd["name"]] = v
                for v, idd in zip(vals_checked, ids_checked):
                    kwargs[idd["name"]] = v
                for v, idd in zip(vals_contents, ids_contents):
                    kwargs[idd["name"]] = v
                if parent_name and rest:
                    kwargs[parent_name] = rest[0]

                if self._has_var_kw:
                    filtered = dict(kwargs)
                else:
                    filtered = {
                        k: v
                        for k, v in kwargs.items()
                        if k in self._callback_param_names
                    }

                try:
                    result = self.callback_fn(**filtered)
                except TypeError as e:
                    missing = self._callback_param_names - set(filtered.keys())
                    msg = (
                        f"Could not run callback: {e}. "
                        f"Missing required fields: {sorted(missing)}"
                    )
                    return [msg] + [no_update] * (n_out - 1)
                except Exception as e:
                    return [f"Error: {e}"] + [no_update] * (n_out - 1)

                if not isinstance(result, (list, tuple)):
                    result = [result]
                result = list(result)
                while len(result) < n_out:
                    result.append(no_update)
                return result[:n_out]

    def run(self, debug: bool = False, port: int = 8050, **kwargs):
        """Convenience wrapper around the Dash dev server."""
        self.app.run(debug=debug, port=port, **kwargs)
