import copy
import datetime
import enum
import inspect
import math
import numbers
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import reduce
from typing import Any, Union, Literal, Annotated, get_origin, get_args

import dash
from dash import Input, Output, State, dcc, html, ctx, Patch
from dash.exceptions import PreventUpdate
from flask import request

import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify
from dash_socketio import DashSocketIO

import matplotlib as mpl
import numpy as np
import pandas as pd
import PIL
from PIL import ImageFile
import plotly.graph_objs as go

from .utils import (
    Fastify,
    _pil_to_b64,
    _get_default_property,
    _parse_docstring_as_markdown,
    depends_on,
)


class AppLayout:
    def __init__(
        self,
        mosaic=None,
        inputs=None,
        outputs=None,
        title=None,
        title_image_path=None,
        subtitle=None,
        github_url=None,
        linkedin_url=None,
        twitter_url=None,
        navbar=True,
        footer=True,
        loader="bars",
        branding=False,
        about=True,
        minimal=False,
        scale_height=1,
        theme=None,
        app=None,
    ):
        self.mosaic = mosaic
        self.inputs = inputs
        self.outputs = outputs
        self.title = title
        self.title_image_path = title_image_path
        self.subtitle = subtitle
        self.github_url = github_url
        self.linkedin_url = linkedin_url
        self.twitter_url = twitter_url
        self.navbar = navbar
        self.footer = footer
        self.loader = loader
        self.branding = branding
        self.about = about
        self.minimal = minimal
        self.scale_height = scale_height
        self.theme = theme
        self.app = app

        self.unique_components = []
        self.col_style = {}
        self.row_style = {}

        # Detect dark Bootswatch themes
        _DARK_THEMES = {"CYBORG", "DARKLY", "QUARTZ", "SLATE", "SOLAR", "SUPERHERO", "VAPOR"}
        self._color_scheme = "dark" if (self.theme or "").upper() in _DARK_THEMES else "light"

        # Vizro-inspired Mantine theme: flat, professional, Inter font
        self._mantine_theme = {
            "fontFamily": "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            "primaryColor": "blue",
            "defaultRadius": 4,
            "headings": {
                "fontFamily": "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
            },
            "colors": {
                "dark": [
                    "#c3c5cb", "#a4a7b0", "#85889a", "#696d81",
                    "#545868", "#3e4254", "#373a44", "#272a35",
                    "#1c1f2a", "#141721",
                ],
            },
            "components": {
                "Button": {"defaultProps": {"size": "sm"}},
                "TextInput": {"defaultProps": {"size": "sm"}},
                "Select": {"defaultProps": {"size": "sm"}},
                "NumberInput": {"defaultProps": {"size": "sm"}},
                "Textarea": {"defaultProps": {"size": "sm"}},
                "Switch": {"defaultProps": {"size": "sm"}},
            },
        }

        if self.mosaic is None:
            self.mosaic = self._infer_mosaic(self.outputs)

    @staticmethod
    def _infer_mosaic(outputs):
        # Number of outputs
        n = len(outputs) - 1

        def calc_lcm(a, b):
            # Calculate LCM
            return abs(a * b) // math.gcd(a, b)

        def lcm_list(numbers):
            # LCM of numbers in a list
            return reduce(calc_lcm, numbers)

        def split_into_chunks(n):
            # Split into chunks of equal sizes
            full_chunks = n // 3
            remainder = n % 3
            result = [3] * full_chunks
            if remainder != 0:
                result.append(remainder)
            return result

        alphabets = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")

        # Split into chunks
        chunks = split_into_chunks(n)

        # Find LCM
        lcm = lcm_list(chunks)

        # Loop over alphanets to generate the final mosaic
        mosaic = ""
        for len_row in chunks:
            mosaic_row_list = []

            # Number of times to repeat elements in each row
            repetitions = int(lcm / len_row)

            for i in range(len_row):
                letter = alphabets.pop(0)
                mosaic_row_list += [letter] * repetitions

            mosaic += "".join(mosaic_row_list) + "\n"

        mosaic = mosaic.strip()

        return mosaic

    @staticmethod
    def _normalize_grid_string(layout):
        if "\n" not in layout:
            # single-line string
            return [list(ln) for ln in layout.split(";")]
        else:
            # multi-line string
            layout = inspect.cleandoc(layout)
            return [list(ln) for ln in layout.strip("\n").split("\n")]

    @staticmethod
    def _make_array(inp):
        """
        Convert input into 2D array

        Returns
        -------
        2D object array
        """
        r0, *rest = inp
        if isinstance(r0, str):
            raise ValueError("List mosaic specification must be 2D")
        for j, r in enumerate(rest, start=1):
            if isinstance(r, str):
                raise ValueError("List mosaic specification must be 2D")
            if len(r0) != len(r):
                raise ValueError(
                    "All of the rows must be the same length, however "
                    f"the first row ({r0!r}) has length {len(r0)} "
                    f"and row {j} ({r!r}) has length {len(r)}."
                )
        out = np.zeros((len(inp), len(r0)), dtype=object)
        for j, r in enumerate(inp):
            for k, v in enumerate(r):
                out[j, k] = v
        return out

    @staticmethod
    def _check_if_rectangular(mosaic):
        "Returns True if all elements in the mosaic array make a perfect rectangular area"

        # Get all the unique keys
        unique_ids = np.unique(mosaic)

        # go through the unique keys,
        for name in unique_ids:
            # sort out where each axes starts/ends
            indx = np.argwhere(mosaic == name)
            start_row, start_col = np.min(indx, axis=0)
            end_row, end_col = np.max(indx, axis=0) + 1

            # and construct the slice object
            slc = (slice(start_row, end_row), slice(start_col, end_col))

            # some light error checking
            if (mosaic[slc] != name).any():
                raise ValueError(
                    f"While trying to layout\n{mosaic!r}\n"
                    f"we found that the label {name!r} specifies a "
                    "non-rectangular or non-contiguous area."
                )

        return True

    @staticmethod
    def _get_n_unique(arr, axis):
        "Get unique number of elements in an array along a given axis"
        if axis not in [0, 1]:
            raise ValueError("Axis for a 2D array must be either 0 or 1")

        nunique_list = []

        for i in range(arr.shape[1 - axis]):
            sub_arr = arr[:, i] if axis == 0 else arr[i, :]
            nunique = np.unique(sub_arr).shape[0]
            nunique_list.append(nunique)

        return nunique_list

    @staticmethod
    def _get_break_indices(arr, axis, index):
        "Get the indices where an array elements switches to another"

        values = arr[:, index] if axis == 0 else arr[index, :]
        break_indices = []
        widths = []

        for idx, v in enumerate(values):
            if idx == 0:
                previous_break_index = 0
                previous_value = v
            else:
                if v != previous_value:
                    widths.append(idx - previous_break_index)
                    break_indices.append(idx)

                    previous_break_index = idx
                    previous_value = v

        widths.append(idx + 1 - previous_break_index)
        widths = [int((w * 12) / sum(widths)) for w in widths]
        extra_assign = [1 for i in range(12 % sum(widths))]
        extra_assign = extra_assign + [
            0 for i in range(len(widths) - len(extra_assign))
        ]

        widths = [
            int((w * 12) / sum(widths)) + ea for w, ea in zip(widths, extra_assign)
        ]

        return break_indices, widths

    @staticmethod
    def _get_sub_mosaics(arr, axis, index_breaks):
        "Get sub-mosaics along the given axis"

        sub_mosaics = []
        begin_index = 0
        index_breaks.append(9999)
        for i_break in index_breaks:
            if axis == 1:
                sub_mosaics.append(arr[:, begin_index:i_break])

            elif axis == 0:
                sub_mosaics.append(arr[begin_index:i_break, :])

            begin_index = i_break

        return sub_mosaics

    def _get_component(self, axis, width, style=None):
        if axis == 1:
            style = self.col_style if style is None else style
            style.update({"height": "100%"})
            layout = dbc.Col(
                [],
                style=style,
                width=width,
                class_name="p-0 d-flex flex-column flex-fill",
            )

        else:
            style = self.row_style if style is None else style
            # style.update({"max-height": "100%"})
            layout = dbc.Row([], style=style, class_name="p-0 g-1 d-flex flex-fill")

        return copy.deepcopy(layout)

    def _set_single_component(self, axis, width, n_rows=1, style=None, label=""):
        style = self.col_style if style is None else style
        component = self.output_component_mapper.get(label, label)
        style.update({"height": f"{n_rows * self.height_of_single_row}vh"})
        layout = dbc.Col(
            [component],
            class_name="p-1 flex-fill d-flex flex-column",
            style=style,
            width=width,
            # align="center",
        )

        return copy.deepcopy(layout)

    def _do_mosaic(self, mosaic_array, axis, layout):
        n_unique = len(np.unique(mosaic_array))

        if n_unique == 1:
            label = np.unique(mosaic_array)[0]

            self.unique_components.append(label)
            style = self.col_style

            lo = self._set_single_component(
                axis=axis,
                width=layout.width if isinstance(layout, dbc.Col) else None,
                style=style,
                label=label,
                n_rows=mosaic_array.shape[0],
            )
            return copy.deepcopy(lo)

        n_unique_axis = self._get_n_unique(arr=mosaic_array, axis=1 - axis)
        min_index = np.argmin(n_unique_axis)

        index_breaks, widths = self._get_break_indices(
            arr=mosaic_array, axis=1 - axis, index=min_index
        )
        sub_arrays = self._get_sub_mosaics(
            arr=mosaic_array, axis=1 - axis, index_breaks=index_breaks
        )

        for array, width in zip(sub_arrays, widths):
            child_layout = self._do_mosaic(
                array, 1 - axis, self._get_component(axis=1 - axis, width=width)
            )
            layout.children.append(child_layout)

        return layout

    def generate_navbar_container(self):
        """Build AppShell.Header with burger, title, and action icons."""
        if not self.navbar:
            return None

        right_items = []

        if self.about:
            right_items.append(
                dmc.Button(
                    "About",
                    id="about-navlink",
                    variant="subtle",
                    color="gray",
                    size="compact-sm",
                )
            )

        if self.github_url:
            right_items.append(
                html.A(
                    dmc.ActionIcon(
                        DashIconify(icon="ri:github-fill", width=20),
                        variant="subtle",
                        color="gray",
                        size="lg",
                    ),
                    href=self.github_url,
                    target="_blank",
                )
            )

        if self.linkedin_url:
            right_items.append(
                html.A(
                    dmc.ActionIcon(
                        DashIconify(icon="entypo-social:linkedin-with-circle", width=20),
                        variant="subtle",
                        color="gray",
                        size="lg",
                    ),
                    href=self.linkedin_url,
                    target="_blank",
                )
            )

        if self.twitter_url:
            right_items.append(
                html.A(
                    dmc.ActionIcon(
                        DashIconify(icon="formkit:twitter", width=20),
                        variant="subtle",
                        color="gray",
                        size="lg",
                    ),
                    href=self.twitter_url,
                    target="_blank",
                )
            )

        header_children = [
            dmc.Group(
                [
                    dmc.Group(
                        [
                            dmc.Burger(id="sidebar-button", opened=True, size="sm"),
                            dmc.Text(
                                self.title or "",
                                fw=600,
                                size="lg",
                                id="title8888928",
                            ),
                        ],
                        gap="sm",
                    ),
                    dmc.Group(
                        [
                            *(right_items or []),
                            *self._auth_header_items(),
                            dmc.Switch(
                                id="theme-toggle",
                                offLabel=DashIconify(icon="radix-icons:sun", width=16),
                                onLabel=DashIconify(icon="radix-icons:moon", width=16),
                                size="md",
                                checked=self._color_scheme == "dark",
                            ),
                        ],
                        gap="xs",
                    ),
                ],
                justify="space-between",
                style={"width": "100%"},
            ),
        ]

        # About modal (outside header but rendered in layout)
        if self.about:
            header_children.append(
                dmc.Modal(id="about-modal", size="80%", zIndex=10000)
            )

        return header_children

    def _auth_header_items(self):
        """Return header items for the auth gate (Sign out button).

        Empty list when auth is disabled. Rendered just before the
        theme toggle in the right-hand header group. Uses an html.A
        wrapper because dmc.ActionIcon does not support href directly.
        """
        if not getattr(self.app, "_auth_config", None):
            return []
        return [
            html.A(
                dmc.Button(
                    "Sign out",
                    id="logout-button",
                    variant="subtle",
                    color="gray",
                    size="compact-sm",
                ),
                href="/logout",
            )
        ]

    def generate_input_component(self):
        """Build the sidebar navbar content with inputs."""
        sidebar_children = []

        # Subtitle under inputs
        if self.subtitle:
            sidebar_children.append(
                dmc.Text(
                    self.subtitle,
                    size="xs",
                    c="dimmed",
                    id="subheader6904007",
                    style={"paddingBottom": "8px"},
                )
            )

        sidebar_children.append(
            dmc.Stack(
                children=self.inputs,
                gap="lg",
                id="input-group",
            )
        )

        return dmc.ScrollArea(
            dmc.Stack(sidebar_children, gap="md"),
            style={"height": "100%"},
            id="input-group-wrapper",
        )

    def generate_output_component(self):
        """Build the main content area with mosaic output grid."""
        mosaic = self._normalize_grid_string(self.mosaic)
        mosaic_arr = self._make_array(mosaic)
        mosaic_shape = mosaic_arr.shape
        # Approximate available height in vh for row distribution
        available_vh = 90 * self.scale_height
        self.height_of_single_row = available_vh / (mosaic_shape[0])

        self._check_if_rectangular(mosaic_arr)

        if self.outputs == []:
            self.output_component_mapper = {}
        else:
            unique_locations = np.unique(mosaic_arr)
            unique_locations.sort()
            self.output_component_mapper = {
                m: o for m, o in zip(unique_locations, self.outputs[:-1])
            }

        begin_axis = np.argmax(
            [
                max([len(np.unique(arr)) for arr in mosaic_arr]),
                max([len(np.unique(arr)) for arr in mosaic_arr.transpose()]),
            ]
        )

        begin = dbc.Row([], justify=True, class_name="g-1 d-flex")
        layout = self._do_mosaic(mosaic_arr, axis=1 - begin_axis, layout=begin)
        output_layout = dbc.Col(
            [layout] + [self.outputs[-1]],
            class_name="g-1 d-flex flex-fill flex-column",
            style={"height": f"calc({int(100 * self.scale_height)}vh - 136px)"},
            width=12,
        )

        loader_component = dmc.LoadingOverlay(
            id="loading-overlay",
            loaderProps=dict(type=self.loader),
        )
        output_layout = html.Div([loader_component, output_layout])

        return output_layout

    def generate_footer_container(self):
        return dmc.Affix(
            dmc.Tooltip(
                label="Made with Fast Dash!",
                position="top",
                withArrow=True,
                transitionProps={"duration": 300},
                children=dcc.Link(
                    dmc.ActionIcon(
                        DashIconify(icon="ion:rocket-sharp", width=18),
                        variant="filled",
                        radius="xl",
                        size="lg",
                    ),
                    href="https://github.com/dkedar7/fast_dash",
                    target="_blank",
                ),
            ),
            position={"bottom": 20, "right": 20},
            id="footer5265971",
        )

    def generate_layout(self, stream_event_names=None):
        if self.minimal:
            self.title = self.subtitle = self.navbar = self.footer = False

        header_children = self.generate_navbar_container() or []
        navbar_content = self.generate_input_component()
        main_content = self.generate_output_component()

        appshell = dmc.AppShell(
            [
                dmc.AppShellHeader(
                    dmc.Group(
                        header_children[0] if header_children else [],
                        style={"height": "100%", "padding": "0 20px"},
                    ),
                    id="header1162572",
                ),
                dmc.AppShellNavbar(
                    navbar_content,
                    p="md",
                    id="navbar3260780",
                    style={"overflowY": "auto"},
                ),
                dmc.AppShellMain(
                    html.Div(
                        main_content,
                        style={"padding": "20px", "height": "100%"},
                        id="output-group-col",
                    ),
                ),
            ],
            header={"height": 56},
            navbar={
                "width": 300,
                "breakpoint": "sm",
                "collapsed": {"mobile": False},
            },
            padding=0,
            id="appshell",
        )

        # Collect items that go outside AppShell
        extra = [
            dmc.NotificationContainer(id="notification-container"),
            html.Div(id="dummy-div", style={"display": "none"}),
        ]
        # About modal
        if self.about and header_children and len(header_children) > 1:
            extra.append(header_children[1])

        if self.branding:
            extra.append(self.generate_footer_container())

        extra.append(DashSocketIO(id="socketio", eventNames=stream_event_names))

        layout = dmc.MantineProvider(
            [appshell] + extra,
            id="mantine-provider",
            theme=self._mantine_theme,
            forceColorScheme=self._color_scheme,
        )

        return layout

    def callbacks(self, app):
        # Dark mode toggle — clientside for instant response
        app.app.clientside_callback(
            """
            function(checked) {
                return checked ? "dark" : "light";
            }
            """,
            Output("mantine-provider", "forceColorScheme"),
            Input("theme-toggle", "checked"),
        )

        @app.app.callback(
            Output("appshell", "navbar"),
            Input("sidebar-button", "opened"),
        )
        def toggle_sidebar(opened):
            user_agent = request.headers.get("User-Agent")

            if not opened or self.app.inputs == [] or self.app.inputs is None:
                collapsed = {"desktop": True, "mobile": True}
            elif ctx.triggered_id == "submit_inputs" and "Mobi" in user_agent:
                collapsed = {"desktop": False, "mobile": True}
            else:
                collapsed = {"desktop": False, "mobile": False}

            return {
                "width": 300,
                "breakpoint": "sm",
                "collapsed": collapsed,
            }

        @app.app.callback(
            Output("about-modal", "opened"),
            Output("about-modal", "children"),
            Input("about-navlink", "n_clicks"),
            State("about-modal", "opened"),
        )
        def display_function_about_information(n_clicks, opened):
            if n_clicks:
                if self.about == True:
                    about_text = _parse_docstring_as_markdown(
                        app.callback_fn, title=self.title
                    )

                elif isinstance(self.about, str):
                    about_text = self.about

                else:
                    about_text = _parse_docstring_as_markdown(
                        app.callback_fn, title=self.title
                    )

                return not opened, dcc.Markdown(about_text)

            raise PreventUpdate


@dataclass
class _ResolvedHint:
    """Result of resolving a typing generic into actionable info."""

    base_type: Any = None
    component: Any = None
    nullable: bool = False


def _resolve_typing_hint(hint, default_value=None):
    """
    Pre-process a type hint that may be a typing generic.
    Returns a _ResolvedHint with either a pre-built component or a base_type
    that can be fed into the existing inference pipeline.
    """
    origin = get_origin(hint)
    args = get_args(hint)

    # Literal["a", "b", "c"] -> Select dropdown
    if origin is Literal:
        options = [str(o) for o in args]
        default = str(default_value) if default_value is not None and str(default_value) in options else options[0] if options else None
        return _ResolvedHint(
            component=Fastify(
                dmc.Select(data=options, value=default),
                "value",
                tag="Literal",
            ),
        )

    # Enum subclass -> Select dropdown
    if isinstance(hint, type) and issubclass(hint, enum.Enum):
        members = [str(e.value) for e in hint]
        default = str(default_value.value) if isinstance(default_value, enum.Enum) else members[0] if members else None
        return _ResolvedHint(
            component=Fastify(
                dmc.Select(data=members, value=default),
                "value",
                tag="Enum",
            ),
        )

    # Annotated[T, metadata] -> depends on metadata
    if origin is Annotated:
        inner_type = args[0]
        metadata = args[1] if len(args) > 1 else None

        # Annotated[int, range(0, 100)] -> Slider
        if isinstance(metadata, range):
            step = metadata.step if metadata.step != 1 else 1
            default = default_value if default_value is not None else metadata.start
            return _ResolvedHint(
                component=Fastify(
                    dmc.Slider(min=metadata.start, max=metadata.stop, step=step, value=default),
                    "value",
                    tag="Numeric",
                ),
            )

        # Annotated[str, ["option1", "option2"]] -> Select
        if isinstance(metadata, list):
            options = [str(o) for o in metadata]
            default = str(default_value) if default_value is not None and str(default_value) in options else options[0] if options else None
            return _ResolvedHint(
                component=Fastify(
                    dmc.Select(data=options, value=default),
                    "value",
                    tag="Annotated",
                ),
            )

        # Annotated[T, <unknown>] -> resolve inner type
        return _resolve_typing_hint(inner_type, default_value)

    # Optional[T] i.e. Union[T, None] -> unwrap to T
    if origin is Union:
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            resolved = _resolve_typing_hint(non_none_args[0], default_value)
            resolved.nullable = True
            return resolved
        if non_none_args:
            return _resolve_typing_hint(non_none_args[0], default_value)

    # Parameterized generics like list[str], dict[str, int] -> use origin type
    if origin is not None:
        return _ResolvedHint(base_type=origin)

    # Plain type or non-typing object -> pass through unchanged
    return _ResolvedHint(base_type=hint)


def _get_readable_names_from_parent_classes(type_hint):
    "Get a readable label for the object's type. Order is important. If disturbed, type = bool could get matched with float."
    _map_types_to_readable_names = {
        str: "Text",
        bool: "Boolean",
        float: "Numeric",
        int: "Numeric",
        complex: "Numeric",
        list: "Sequence",
        set: "Sequence",
        range: "Sequence",
        # tuple: "Sequence",
        PIL.Image.Image: "Image",
        dict: "Dictionary",
        datetime.datetime: "Timestamp",
        datetime.date: "Date",
    }

    for parent_class in _map_types_to_readable_names:
        try:
            if issubclass(type_hint, parent_class):
                return _map_types_to_readable_names[parent_class]
        except TypeError:
            continue

    return None


def _get_component_from_input(hint, default_value=None):
    """
    Get FastComponent to represent the given input.

    This implementation returns the FastComponent associated with the specific input
    from the hint (type) of the input, type of the default value and the default value itself.

    Args:
        hint (FastComponent or Python data type): Either the input component or data type of the input.
        default_value (any, optional): Default value of the input component. Defaults to None.

    Returns:
        FastComponent: Component that can be used to represent the given input.
    """

    # If hint has the attribute "component_property", it indicates that hint is a FastComponent, return it
    if hasattr(hint, "component_property"):
        return hint

    # Elif the component is a Dash component, use the specified component_property
    # If one isn't specified, get the default component_property
    # If not even that assign it the component_property "value" and return the FastComponent.
    elif isinstance(type(hint), dash.development.base_component.ComponentMeta):
        default_component_property = _get_default_property(type(hint))

        return Fastify(component=hint, component_property=default_component_property)

    # Resolve typing generics (Literal, Enum, Optional, Annotated, list[str], etc.)
    resolved = _resolve_typing_hint(hint, default_value)
    if resolved.component is not None:
        return resolved.component
    hint = resolved.base_type

    # If hint is not type, assume that the user specified an object. Change it to type
    if not isinstance(hint, type):
        hint = type(hint)

    _hint_type = _get_readable_names_from_parent_classes(hint)
    _default_value_type = _get_readable_names_from_parent_classes(type(default_value))

    # If the hint is a PIL Image
    try:
        _is_pil = issubclass(hint, PIL.Image.Image)
    except TypeError:
        _is_pil = False
    if _is_pil:
        _hint_type = "Image"

    # If the default is a PIL Image
    if isinstance(default_value, PIL.Image.Image):
        _default_value_type = "Image"

    if _hint_type == "Text":
        if _default_value_type == "Text":
            component = Fastify(
                dmc.Textarea(
                    value=default_value,
                    autosize=True,
                    minRows=4,
                ),
                "value",
                tag=_hint_type,
            )

        elif _default_value_type == "Numeric":
            component = Fastify(
                dbc.Input(value=default_value, type="number"), "value", tag=_hint_type
            )

        elif _default_value_type == "Sequence":
            component = Fastify(
                dmc.Select(data=default_value), "value", tag=_hint_type
            )

        elif _default_value_type == "Dictionary":
            component = Fastify(
                dbc.Input(value=str(default_value)), "value", tag=_hint_type
            )

        elif _default_value_type == "Boolean":
            component = Fastify(
                dbc.Input(value=str(default_value)), "value", tag=_hint_type
            )

        elif _default_value_type == "Date":
            component = Fastify(
                dbc.Input(value=str(default_value)), "value", tag=_hint_type
            )

        elif _default_value_type == "Timestamp":
            component = Fastify(
                dbc.Input(value=str(default_value)), "value", tag=_hint_type
            )

        else:
            warnings.warn("Unknown or unsupported default value type. Assuming text.")
            component = Text

    elif _hint_type == "Numeric":
        if _default_value_type == "Text":
            component = Fastify(
                dbc.Input(value=hint(default_value), type="number"),
                "value",
                tag=_hint_type,
            )

        elif _default_value_type == "Numeric":
            component = Fastify(
                dbc.Input(value=default_value, type="number"), "value", tag=_hint_type
            )

        elif _default_value_type == "Sequence":
            if isinstance(default_value, range):
                start, step, stop = (
                    default_value.start,
                    default_value.step,
                    default_value.stop,
                )

                component = Fastify(
                    dmc.Slider(min=start, max=stop, step=step), "value", tag=_hint_type
                )

            else:
                default_value = list(map(hint, default_value))
                start, stop = min(default_value), max(default_value)
                step = (stop - start) / len(default_value)

            component = Fastify(
                dcc.Slider(
                    start,
                    stop,
                    step,
                    marks=None,
                    tooltip={"placement": "bottom", "always_visible": True},
                ),
                "value",
                tag=_hint_type,
            )

        else:
            component = Fastify(dbc.Input(type="number"), "value", tag=_hint_type)

    elif _hint_type == "Sequence":
        if _default_value_type == "Text":
            component = Fastify(
                dmc.MultiSelect(
                    data=[default_value],
                    value=[default_value],
                    searchable=True
                ),
                "value",
                tag=_default_value_type,
            )

        elif _default_value_type == "Sequence":
            component = Fastify(
                dmc.MultiSelect(
                    data=default_value,
                    searchable=True,
                ),
                "value",
                tag=_default_value_type,
            )

        elif _default_value_type == "Dictionary":
            component = Fastify(
                dmc.MultiSelect(
                    data=default_value,
                    searchable=True,
                ),
                "value",
                tag=_default_value_type,
            )

        else:
            component = Fastify(
                dmc.MultiSelect(
                    searchable=True
                ),
                "value",
                tag=_default_value_type,
            )

    elif _hint_type == "Dictionary":
        component = Fastify(
            dmc.MultiSelect(data=list(default_value.keys())), "value", tag=_hint_type
        )

    elif _hint_type == "Boolean":
        if _default_value_type == "Boolean":
            component = Fastify(
                dbc.Checkbox(value=default_value), "value", tag=_hint_type
            )

        else:
            component = Fastify(dbc.Checkbox(), "value", tag=_hint_type)

    elif _hint_type == "Image":
        if _default_value_type == "Image":
            acknowledge_image_component = Fastify(
                component=html.Img(width="100%", style={"padding": "1% 0% 0% 0%"}),
                component_property="src",
                tag=_hint_type,
            )
            component = Fastify(
                component=dcc.Upload(
                    children=dbc.Col(["Click to upload image"]),
                    style={
                        "lineHeight": "60px",
                        "borderWidth": "1px",
                        "borderStyle": "dashed",
                        "borderRadius": "5px",
                        "textAlign": "center",
                    },
                    contents=_pil_to_b64(default_value),
                ),
                component_property="contents",
                ack=acknowledge_image_component,
                tag=_hint_type,
            )

        else:
            acknowledge_image_component = Fastify(
                component=html.Img(width="100%", style={"padding": "1% 0% 0% 0%"}),
                component_property="src",
            )
            component = Fastify(
                component=dcc.Upload(
                    children=dbc.Col(["Click to upload image"]),
                    style={
                        "lineHeight": "60px",
                        "borderWidth": "1px",
                        "borderStyle": "dashed",
                        "borderRadius": "5px",
                        "textAlign": "center",
                    },
                ),
                component_property="contents",
                ack=acknowledge_image_component,
                tag=_hint_type,
            )

    elif _hint_type == "Date":
        if _default_value_type == "Date":
            component = Fastify(
                dcc.DatePickerSingle(
                    display_format="MMM DD, YYYY",
                    date=default_value,
                    style={"width": "100%"},
                ),
                "date",
                tag=_hint_type,
            )

        else:
            component = Fastify(
                dcc.DatePickerSingle(
                    display_format="MMM DD, YYYY",
                    date=datetime.date.today(),
                    style={"width": "100%"},
                ),
                "date",
                tag=_hint_type,
            )

    else:
        if _default_value_type is not None:
            if _default_value_type == "Text":
                component = Fastify(
                    dbc.Input(value=default_value), "value", tag=_default_value_type
                )

            elif _default_value_type == "Numeric":
                component = Fastify(
                    dbc.Input(value=default_value, type="number"),
                    "value",
                    tag=_default_value_type,
                )

            elif _default_value_type == "Sequence":
                if isinstance(default_value, range):
                    start, step, stop = (
                        default_value.start,
                        default_value.step,
                        default_value.stop,
                    )
                    component = Fastify(
                        dcc.Slider(
                            start,
                            stop,
                            step,
                            marks=None,
                            tooltip={"placement": "bottom", "always_visible": True},
                        ),
                        "value",
                        tag=_default_value_type,
                    )

                else:
                    component = Fastify(
                        dmc.Select(data=default_value),
                        "options",
                        tag=_default_value_type,
                    )

            elif _default_value_type == "Dictionary":
                component = Fastify(
                    dmc.Select(data=list(default_value.keys())),
                    "value",
                    tag=_default_value_type,
                )

            elif _default_value_type == "Boolean":
                component = Fastify(
                    dbc.Checkbox(value=default_value), "value", tag=_default_value_type
                )

            elif _default_value_type == "Date":
                component = Fastify(
                    dcc.DatePickerSingle(
                        display_format="MMM DD, YYYY",
                        date=default_value,
                        style={"width": "100%"},
                    ),
                    "date",
                    tag=_default_value_type,
                )

            elif _default_value_type == "Timestamp":
                component = Fastify(
                    dcc.DatePickerSingle(
                        display_format="MMM DD, YYYY",
                        date=default_value.date(),
                        style={"width": "100%"},
                    ),
                    "date",
                    tag=_default_value_type,
                )

            elif _default_value_type == "Image":
                acknowledge_image_component = Fastify(
                    component=html.Img(width="100%", style={"padding": "1% 0% 0% 0%"}),
                    component_property="src",
                    tag=_default_value_type,
                )
                component = Fastify(
                    component=dcc.Upload(
                        children=dbc.Col(["Click to upload image"]),
                        style={
                            "lineHeight": "60px",
                            "borderWidth": "1px",
                            "borderStyle": "dashed",
                            "borderRadius": "5px",
                            "textAlign": "center",
                        },
                        contents=_pil_to_b64(default_value),
                    ),
                    component_property="contents",
                    ack=acknowledge_image_component,
                    tag=_default_value_type,
                )

            else:
                warnings.warn("Unknown or unsupported hint. Assuming text.")
                component = Text

        else:
            warnings.warn("Unknown or unsupported hint. Assuming text.")
            component = Text

    return component


def _get_output_components(_hint_type):
    if hasattr(_hint_type, "component_property"):
        return _hint_type

    # Elif the component is a Dash component, use the specified component_property
    # If one isn't specified, get the default component_property
    # If not even that assign it the component_property "value" and return the FastComponent.
    elif isinstance(type(_hint_type), dash.development.base_component.ComponentMeta):
        default_component_property = _get_default_property(type(_hint_type))

        return Fastify(
            component=_hint_type,
            component_property=default_component_property,
            tag=_hint_type,
        )

    # Resolve typing generics
    resolved = _resolve_typing_hint(_hint_type)
    if resolved.component is not None:
        # For outputs, Literal/Enum should display as text, not a Select
        if resolved.component.tag in ("Literal", "Enum"):
            return Fastify(html.H1(), "children", tag=resolved.component.tag)
        return resolved.component
    _hint_type = resolved.base_type

    # Resolve string annotations (e.g. "plotly.graph_objects.Figure")
    if isinstance(_hint_type, str):
        _graph_hints = {
            "plotly.graph_objects.Figure", "plotly.graph_objs.Figure",
            "go.Figure", "Figure",
        }
        _df_hints = {"pd.DataFrame", "DataFrame", "pandas.DataFrame"}
        _img_hints = {"PIL.Image.Image", "Image"}
        if _hint_type in _graph_hints:
            return Fastify(
                component=dcc.Graph(style=dict(height="100%", width="100%")),
                component_property="figure",
                tag="Graph",
            )
        elif _hint_type in _df_hints:
            _hint_type = pd.DataFrame
        elif _hint_type in _img_hints:
            _hint_type = PIL.Image.Image

    # If hint is not type, assume that the user specified an object. Change it to type
    if not isinstance(_hint_type, type):
        _hint_type = type(_hint_type)

    try:
        if issubclass(_hint_type, PIL.Image.Image):
            component = Image

        elif issubclass(_hint_type, pd.DataFrame):
            component = Table

        elif _hint_type == mpl.figure.Figure:
            component = Image

        else:
            component = Fastify(html.H1(), "children", tag=_hint_type)
    except TypeError:
        component = Fastify(html.H1(), "children", tag=_hint_type)

    return component


def _infer_input_components(func):
    signature = inspect.signature(func)
    components = []

    parameters = signature.parameters.items()
    for _, value in parameters:
        hint = value.annotation
        default = None if value.default == inspect._empty else value.default

        # Handle depends_on defaults — reactive input wired to a parent input
        if isinstance(default, depends_on):
            dep = default
            component = Fastify(
                dmc.Select(placeholder="Select..."),
                "value",
                tag="Text",
            )
            component._depends_on_parent = dep.parent
            component._depends_on_resolver = dep.resolver
            components.append(component)
        else:
            component = _get_component_from_input(hint, default)
            components.append(component)

    return components


def _infer_output_components(func, outputs, output_labels):
    signature = inspect.signature(func)
    components = []

    if isinstance(outputs, list):
        parameters = [(None, o) for o in outputs]

    elif outputs is not None:
        parameters = [(None, outputs)]

    else:
        parameters = list(
            enumerate(
                signature.return_annotation
                if isinstance(signature.return_annotation, tuple)
                else [signature.return_annotation]
            )
        )

    if output_labels is None:
        output_labels = [None] * len(parameters)

    if isinstance(output_labels, list) and len(output_labels) != len(parameters):
        output_labels = [f"OUTPUT_{i + 1}" for i in range(len(parameters))]

    for (_, hint), label in zip(parameters, output_labels):
        component = _get_output_components(hint)
        component.label_ = label
        components.append(copy.deepcopy(component))

    return components


###################################
# Define default components #
###################################

##### General components
Text = Fastify(
    component=dmc.Textarea(
        placeholder="",
        autosize=True,
        minRows=4,
    ),
    component_property="value",
    placeholder="",
    tag="Text",
)

TextArea = Fastify(component=dbc.Textarea(), component_property="value", tag="Text")

NumberInput = Fastify(
    component=dmc.NumberInput(
        placeholder="Enter a number",
    ),
    component_property="value",
    tag="Numeric",
)

DateInput = Fastify(
    component=dmc.DateInput(
        placeholder="Pick a date",
        valueFormat="YYYY-MM-DD",
    ),
    component_property="value",
    tag="Date",
)

ColorInput = Fastify(
    component=dmc.ColorPicker(
        format="hex",
        value="#1c7ed6",
    ),
    component_property="value",
    tag="Text",
)

MultiSelect = Fastify(
    component=dmc.MultiSelect(
        placeholder="Select options",
    ),
    component_property="value",
    tag="Text",
)

DateRange = Fastify(
    component=dmc.DatePickerInput(
        placeholder="Pick date range",
        type="range",
        valueFormat="YYYY-MM-DD",
    ),
    component_property="value",
    tag="Text",
)

Switch = Fastify(
    component=dmc.Switch(
        label="Toggle",
    ),
    component_property="checked",
    tag="Bool",
)

PasswordInput = Fastify(
    component=dmc.PasswordInput(
        placeholder="Enter password",
    ),
    component_property="value",
    tag="Text",
)

Markdown = Fastify(
    component=dcc.Markdown(
        style={"padding": "10px"},
    ),
    component_property="children",
    tag="Text",
)

Slider = Fastify(
    component=dcc.Slider(
        min=0,
        max=20,
        step=1,
        value=10,
        tooltip={"placement": "top", "always_visible": True},
    ),
    component_property="value",
    tag="Numeric",
)


##### Input components
Upload = Fastify(
    component=dcc.Upload(
        children=dbc.Col(["Click to upload"]),
        style={
            "lineHeight": "60px",
            "borderWidth": "1px",
            "borderStyle": "dashed",
            "borderRadius": "5px",
            "textAlign": "center",
        },
    ),
    component_property="contents",
    tag="Text",
)

acknowledge_image_component = Fastify(
    component=html.Img(width="100%", style={"padding": "1% 0% 0% 0%"}),
    component_property="src",
    tag="Image",
)

UploadImage = Fastify(
    component=dcc.Upload(
        children=dbc.Col(["Click to upload image"]),
        style={
            "lineHeight": "60px",
            "borderWidth": "1px",
            "borderStyle": "dashed",
            "borderRadius": "5px",
            "textAlign": "center",
        },
    ),
    component_property="contents",
    ack=acknowledge_image_component,
    tag="Image",
)


##### Output components
Image = Fastify(
    component=html.Img(
        style={
            "object-fit": "contain",
            "max-height": "90%",
            "max-width": "100%",
            "height": "auto",
        }
    ),
    component_property="src",
    tag="Image",
)

Graph = Fastify(
    component=dcc.Graph(style=dict(height="100%", width="100%")),
    component_property="figure",
    placeholder=(
        go.Figure()
        .update_yaxes(visible=False, showticklabels=False)
        .update_xaxes(visible=False, showticklabels=False)
    ),
    tag="Graph",
)

Chat = Fastify(
    html.Div(
        style={
            "overflow-y": "scroll",
            "overflow-x": "hidden",
            "display": "flex",
            "flex-direction": "column-reverse",
        }
    ),
    "children",
    tag="Chat",
)

Download = Fastify(
    component=html.Div(),
    component_property="children",
    tag="Download",
)

Table = Fastify(
    dash.dash_table.DataTable(
        page_size=100,
        page_action="native",
        sort_action="native",
        style_header={
            "backgroundColor": "white",
            "fontWeight": "bold",
            "color": "black",
            "textAlign": "center",
            "border": "1px solid #f0f0f0",
            "fontFamily": '"News Cycle","Arial Narrow Bold",sans-serif',
        },
        style_cell={
            "backgroundColor": "white",
            "color": "black",
            "textAlign": "center",
            "border": "1px solid #f0f0f0",
            "fontFamily": '"News Cycle","Arial Narrow Bold",sans-serif',
        },
        style_table={
            "border": "1px solid #f0f0f0",
            "overflowY": "auto",
            "fontFamily": '"News Cycle","Arial Narrow Bold",sans-serif',
        },
    ),
    "data",
)
