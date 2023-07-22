import copy
import datetime
import inspect
import math
import numbers
import warnings
from collections.abc import Iterable, Sequence
from functools import reduce

import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
import matplotlib as mpl
import numpy as np
import PIL
import plotly.graph_objs as go
from dash import Input, Output, State, dcc, html
from dash_iconify import DashIconify
from PIL import ImageFile

from .utils import Fastify, _pil_to_b64


class BaseLayout:
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
        minimal=False,
        scale_height=1,
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
        self.minimal = minimal
        self.scale_height = scale_height

    def generate_navbar_container(self):
        if not self.navbar:
            return None

        # 1. Navbar
        social_media_navigation = []
        if self.github_url:
            social_media_navigation.append(
                dbc.NavItem(
                    dbc.NavLink(
                        html.I(
                            className="fa-2x fab fa-github", style={"color": "#ffffff"}
                        ),
                        href=self.github_url,
                        target="_blank",
                    )
                )
            )

        if self.linkedin_url:
            social_media_navigation.append(
                dbc.NavItem(
                    dbc.NavLink(
                        html.I(
                            className="fa-2x fab fa-linkedin",
                            style={"color": "#ffffff"},
                        ),
                        href=self.linkedin_url,
                        target="_blank",
                    )
                )
            )

        if self.twitter_url:
            social_media_navigation.append(
                dbc.NavItem(
                    dbc.NavLink(
                        html.I(
                            className="fa-2x fab fa-twitter-square",
                            style={"color": "#ffffff"},
                        ),
                        href=self.twitter_url,
                        target="_blank",
                    )
                )
            )

        navbar = dbc.NavbarSimple(
            children=[dbc.NavItem(dbc.NavLink("About", href="#"))]
            + social_media_navigation,
            brand=[
                dmc.Group(
                    [
                        dmc.Burger(
                            id="sidebar-button", opened=True, color="white", size=15
                        ),
                        self.title,
                    ],
                    spacing=5,
                )
            ]
            or "",
            color="primary",
            dark=True,
            fluid=True,
            fixed=None,
            style={"padding": "0 0 0 0"},
        )

        navbar_container = dbc.Container(
            [navbar],
            fluid=True,
            style={"padding": "0 0 0 0"},
            id="navbar3260780",
            className="dbc",
        )

        return navbar_container

    def generate_header_component(self):
        header_children = []

        if self.title:
            header_children.append(
                dbc.Row(
                    html.H2(
                        self.title, style={"textAlign": "center"}, id="title8888928"
                    ),
                    style={"padding": "1% 0% 1% 0%"},
                )
            )

        if self.title_image_path:
            header_children.append(
                dbc.Row(
                    dbc.Row(
                        html.Img(src=self.title_image_path, style={"width": "250px"}),
                        justify="center",
                    )
                )
            )

        if self.subtitle:
            header_children.append(
                dbc.Row(
                    dbc.Row(
                        html.H5(
                            self.subtitle,
                            id="subheader6904007",
                            style={"textAlign": "center"},
                        ),
                        style={"padding": "0% 0% 1% 0%"},
                    )
                )
            )

        header_container = dbc.Container(header_children, id="header1162572")

        return header_container

    def generate_input_component(self):
        input_container = dbc.Col(
            children=self.inputs,
            id="input-group",
            style={
                "padding": "2% 1% 1% 2%",
                "lineHeight": "60px",
                "borderWidth": "1px",
                "borderRadius": "5px",
                "background-color": "#F2F2F2",
            },
            width=5,
            xs=12,
            sm=12,
            md=5,
            lg=5,
            xl=5,
            xxl=5,
        )

        return input_container

    def generate_output_component(self):
        output_container = dbc.Col(
            children=self.outputs,
            id="output-group",
            style={
                "padding": "2% 1% 1% 2%",
                "lineHeight": "60px",
                "borderWidth": "1px",
                "borderRadius": "5px",
                "background-color": "#F2F2F2",
            },
            width=5,
            xs=12,
            sm=12,
            md=5,
            lg=5,
            xl=5,
            xxl=5,
        )

        return output_container

    def generate_footer_container(self):
        if self.footer is False:
            return None

        footer = dbc.NavbarSimple(
            brand="Made with Fast Dash",
            brand_href="https://fastdash.app/",
            color="primary",
            dark=True,
            fluid=True,
            fixed=None,
            style={"padding": "0 0 0 0"},
        )

        footer = html.A(
            "Made with Fast Dash", href="https://fastdash.app/", target="_blank"
        )

        footer_container = dbc.Container(
            [footer], fluid=True, style={"padding": "0 0 0 2%"}, id="footer5265971"
        )

        return footer_container

    def generate_layout(self):
        if self.minimal:
            self.title = self.subtitle = self.navbar = self.footer = False

        layout = dbc.Container(
            [
                self.generate_navbar_container(),
                self.generate_header_component(),
                dbc.Row(
                    [self.generate_input_component(), self.generate_output_component()],
                    justify="evenly",
                    style={"padding": "2% 1% 0% 2%"},
                ),
                self.generate_footer_container(),
            ],
            fluid=True,
            style={"padding": "0 0 0 0"},
        )

        return layout

    def callbacks(self, app=None):
        "Optional callbacks specific to the layout"
        return


class SidebarLayout(BaseLayout):
    def __init__(self, **kwargs):
        self.unique_components = []

        self.col_style = {"text-align": "center"}
        self.row_style = {"text-align": "center"}

        super().__init__(**kwargs)

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
            class_name="p-1 bg-white flex-fill d-flex flex-column",
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

    def generate_input_component(self):
        return dbc.Col(
            children=[dmc.Stack(children=self.inputs)],
            id="input-group",
            sm=2,
            width=12,
            style={
                "background-color": "#F5F7F7",
                "display": "block",
                "padding": "2% 1% 0 2%",
                "height": f"{self.scale_height * 110}vh",
            },
            class_name="border border-right",
        )

    def generate_output_component(self):
        mosaic = self._normalize_grid_string(self.mosaic)
        mosaic_arr = self._make_array(mosaic)
        mosaic_shape = mosaic_arr.shape
        self.height_of_single_row = (80 * self.scale_height) / (mosaic_shape[0])

        # Check if the mosaic array makes rectangles for all elements
        self._check_if_rectangular(mosaic_arr)

        if self.outputs == []:
            self.output_component_mapper = {}

        else:
            unique_locations = np.unique(mosaic_arr)
            unique_locations.sort()
            self.output_component_mapper = {
                m: o for m, o in zip(unique_locations, self.outputs[:-1])
            }

        # Slice along the axis with the most number of unique elements first
        begin_axis = np.argmax(
            [
                max([len(np.unique(arr)) for arr in mosaic_arr]),
                max([len(np.unique(arr)) for arr in mosaic_arr.transpose()]),
            ]
        )

        begin = dbc.Row([], justify=True, class_name="g-1 d-flex")
        layout = self._do_mosaic(mosaic_arr, axis=1 - begin_axis, layout=begin)
        output_layout = dmc.LoadingOverlay(
            dbc.Col(
                [layout] + [self.outputs[-1]],
                class_name="g-1 d-flex flex-fill flex-column",
                style={"height": f"{80 * self.scale_height}vh"},
            ),
            loaderProps=dict(variant="bars"),
        )

        return output_layout

    def generate_footer_container(self):
        return dmc.Affix(
            dmc.Tooltip(
                label="Made with Fast Dash!",
                position="top",
                withArrow=True,
                transitionDuration=300,
                children=dcc.Link(
                    dmc.Button(
                        DashIconify(icon="ion:rocket-sharp", width=20), radius=500
                    ),
                    href="https://github.com/dkedar7/fast_dash",
                    target="_blank",
                ),
            ),
            position={"bottom": "20px", "right": "20px"},
            id="footer5265971",
        )

    def generate_layout(self):
        # There are four main components:
        # navbar, header, input, output, footer

        if self.minimal:
            self.title = self.subtitle = self.navbar = self.footer = False

        layout = dmc.MantineProvider(
            dbc.Container(
                [
                    self.generate_navbar_container(),
                    dbc.Row(
                        [
                            self.generate_input_component(),
                            dbc.Col(
                                [
                                    self.generate_header_component(),
                                    self.generate_output_component(),
                                ],
                                id="output-group-col",
                                style={"padding": "1% 2% 0 2%"},
                            ),
                        ],
                        class_name="d-flex",
                    ),
                    self.generate_footer_container(),
                ],
                fluid=True,
                style={"padding": "0 0 0 0", "height": "100vh"},
            )
        )

        return layout

    def callbacks(self, app):
        @app.callback(
            [Output("input-group", "style"), Output("output-group-col", "width")],
            [Input("sidebar-button", "opened")],
            [State("input-group", "style")],
        )
        def toggle_sidebar(opened, input_style):
            input_style = {} if input_style is None else input_style
            width = 10

            display = input_style.get("display", "block")

            # Condition to collapse the sidebar
            if not opened:
                input_style.update({"display": "none"})
                width = 12

            # Expand by default
            else:
                input_style.update({"display": "block"})
                width = 10

            return input_style, width


_map_types_to_readable_names = {
    str: "Text",
    float: "Numeric",
    int: "Numeric",
    complex: "Numeric",
    list: "Sequence",
    set: "Sequence",
    range: "Sequence",
    tuple: "Sequence",
    PIL.ImageFile.ImageFile: "Image",
    dict: "Dictionary",
    bool: "Boolean",
    datetime.date: "Date",
    datetime.datetime: "Timestamp",
}


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

    # If hint is not type, assume that the user specified an object. Change it to type
    if not isinstance(hint, type):
        hint = type(hint)

    _hint_type = _map_types_to_readable_names.get(hint)
    _default_value_type = _map_types_to_readable_names.get(type(default_value))

    # If the hint is a PIL Image
    if issubclass(hint, PIL.ImageFile.ImageFile):
        _hint_type = "Image"

    # If the default is a PIL Image
    if isinstance(default_value, PIL.ImageFile.ImageFile):
        _default_value_type = "Image"

    if _hint_type == "Text":
        if _default_value_type == "Text":
            component = Fastify(dbc.Input(value=default_value), "value")

        elif _default_value_type == "Numeric":
            component = Fastify(dbc.Input(value=default_value, type="number"), "value")

        elif _default_value_type == "Sequence":
            component = Fastify(dcc.Dropdown(options=default_value), "value")

        elif _default_value_type == "Dictionary":
            component = Fastify(dbc.Input(value=str(default_value)), "value")

        elif _default_value_type == "Boolean":
            component = Fastify(dbc.Input(value=str(default_value)), "value")

        elif _default_value_type == "Date":
            component = Fastify(dbc.Input(value=str(default_value)), "value")

        elif _default_value_type == "Timestamp":
            component = Fastify(dbc.Input(value=str(default_value)), "value")

        else:
            component = Text

    elif _hint_type == "Numeric":
        if _default_value_type == "Text":
            component = Fastify(
                dbc.Input(value=hint(default_value), type="number"), "value"
            )

        elif _default_value_type == "Numeric":
            component = Fastify(dbc.Input(value=default_value, type="number"), "value")

        elif _default_value_type == "Sequence":
            if isinstance(default_value, range):
                start, step, stop = (
                    default_value.start,
                    default_value.step,
                    default_value.stop,
                )

                component = Fastify(
                    dmc.Slider(min=start, max=stop, step=step),
                    "value",
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
            )

        else:
            component = Fastify(dbc.Input(type="number"), "value")

    elif _hint_type == "Sequence":
        if _default_value_type == "Text":
            component = Fastify(
                dbc.Input(value=[value.strip() for value in default_value.split(",")]),
                "value",
            )

        elif _default_value_type == "Sequence":
            component = Fastify(dcc.Dropdown(default_value, multi=True), "value")

        elif _default_value_type == "Dictionary":
            component = Fastify(dcc.Dropdown(default_value, multi=True), "value")

    elif _hint_type == "Dictionary":
        component = Fastify(dcc.Dropdown(default_value, multi=True), "value")

    elif _hint_type == "Boolean":
        if _default_value_type == "Boolean":
            component = Fastify(dbc.Checkbox(value=default_value), "value")

        else:
            component = Fastify(dbc.Checkbox(), "value")

    elif _hint_type == "Image":
        if _default_value_type == "Image":
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
                    contents=_pil_to_b64(default_value),
                ),
                component_property="contents",
                ack=acknowledge_image_component,
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
            )

        else:
            component = Fastify(
                dcc.DatePickerSingle(
                    display_format="MMM DD, YYYY",
                    date=datetime.date.today(),
                    style={"width": "100%"},
                ),
                "date",
            )

    else:
        if _default_value_type is not None:
            if _default_value_type == "Text":
                component = Fastify(dbc.Input(value=default_value), "value")

            elif _default_value_type == "Numeric":
                component = Fastify(
                    dbc.Input(value=default_value, type="number"), "value"
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
                    )

                else:
                    component = Fastify(dcc.Dropdown(options=default_value), "options")

            elif _default_value_type == "Dictionary":
                component = Fastify(dcc.Dropdown(options=default_value), "value")

            elif _default_value_type == "Boolean":
                component = Fastify(dbc.Checkbox(value=default_value), "value")

            elif _default_value_type == "Date":
                component = Fastify(
                    dcc.DatePickerSingle(
                        display_format="MMM DD, YYYY",
                        date=default_value,
                        style={"width": "100%"},
                    ),
                    "date",
                )

            elif _default_value_type == "Timestamp":
                component = Fastify(
                    dcc.DatePickerSingle(
                        display_format="MMM DD, YYYY",
                        date=default_value.date(),
                        style={"width": "100%"},
                    ),
                    "date",
                )

            elif _default_value_type == "Image":
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
                        contents=_pil_to_b64(default_value),
                    ),
                    component_property="contents",
                    ack=acknowledge_image_component,
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

    # If hint is not type, assume that the user specified an object. Change it to type
    if not isinstance(_hint_type, type):
        _hint_type = type(_hint_type)

    if issubclass(_hint_type, PIL.ImageFile.ImageFile):
        component = Image

    elif _hint_type == mpl.figure.Figure:
        component = Image

    else:
        component = Fastify(html.H1(), "children")

    return component


def _infer_input_components(func):
    signature = inspect.signature(func)
    components = []

    parameters = signature.parameters.items()
    for _, value in parameters:
        hint = value.annotation
        default = None if value.default == inspect._empty else value.default

        component = _get_component_from_input(hint, default)
        components.append(component)

    return components


def _infer_output_components(func, output_labels):
    signature = inspect.signature(func)
    components = []

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
        raise ValueError(
            "Length of output labels must be equal to the number of outputs."
        )

    for (_, hint), label in zip(parameters, output_labels):
        component = _get_output_components(hint)
        component.label_ = label
        components.append(copy.deepcopy(component))

    return components


###################################
# Define default components #
###################################

##### General components
Text = Fastify(component=dbc.Input(), component_property="value")

TextArea = Fastify(component=dbc.Textarea(), component_property="value")

Slider = Fastify(
    component=dcc.Slider(
        min=0,
        max=20,
        step=1,
        value=10,
        tooltip={"placement": "top", "always_visible": True},
    ),
    component_property="value",
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
)

acknowledge_image_component = Fastify(
    component=html.Img(width="100%", style={"padding": "1% 0% 0% 0%"}),
    component_property="src",
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
)


##### Output components
Image = Fastify(
    component=html.Img(
        style={"object-fit": "contain", "max-height": "80%", "height": "auto"}
    ),
    component_property="src",
)

Graph = Fastify(
    component=dcc.Graph(style=dict(height="100%", width="100%")),
    component_property="figure",
    placeholder=(
        go.Figure()
        .update_yaxes(visible=False, showticklabels=False)
        .update_xaxes(visible=False, showticklabels=False)
    ),
)
