from collections.abc import Sequence, Iterable
import dash_bootstrap_components as dbc
import plotly.graph_objs as go
from dash import dcc, html
import inspect
import numbers
import warnings

import PIL
from PIL import ImageFile
import datetime

from .utils import _pil_to_b64, Fastify


class DefaultLayout:
    def __init__(
        self,
        inputs=None,
        outputs=None,
        title=None,
        title_image_path=None,
        subtext=None,
        github_url=None,
        linkedin_url=None,
        twitter_url=None,
        navbar=True,
        footer=True,
        minimal=False
    ):

        self.inputs = inputs
        self.outputs = outputs
        self.title = title
        self.title_image_path = title_image_path
        self.subtext = subtext
        self.github_url = github_url
        self.linkedin_url = linkedin_url
        self.twitter_url = twitter_url
        self.navbar = navbar
        self.footer = footer
        self.minimal = minimal

        # Bring all containers together
        self.navbar_container = self.generate_navbar_container()
        self.header_container = self.generate_header_container()
        self.io_container = self.generate_io_container()
        self.footer_container = self.generate_footer_container()

        layout_components = [
            self.navbar_container,
            self.header_container,
            self.io_container,
            self.footer_container,
        ]

        self.layout = dbc.Container(
            [component for component in layout_components if component is not None] if minimal == False else [self.io_container],
            fluid=True,
            style={"padding": "0 0 0 0"},
        )

    def generate_navbar_container(self):

        if self.navbar is False:
            return None

        # 1. Navbar
        social_media_navigation = []
        if self.github_url is not None:
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

        if self.linkedin_url is not None:
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

        if self.twitter_url is not None:
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
            brand=self.title,
            color="primary",
            dark=True,
            fluid=True,
            fixed=None,
            style={"padding": "0 0 0 0"},
        )

        navbar_container = dbc.Container(
            [navbar], fluid=True, style={"padding": "0 0 0 0"}, id="navbar3260780"
        )

        return navbar_container

    def generate_header_container(self):

        header_children = []

        if self.title is not None:
            header_children.append(
                dbc.Row(
                    html.H1(self.title, style={"textAlign": "center"}, id="title8888928"),
                    style={"padding": "2% 0% 2% 0%"},
                )
            )

        if self.title_image_path is not None:
            header_children.append(
                dbc.Row(
                    dbc.Row(
                        html.Img(src=self.title_image_path, style={"width": "250px"}),
                        justify="center",
                    )
                )
            )

        if self.subtext is not None:
            header_children.append(
                dbc.Row(
                    dbc.Row(
                        html.H4(html.I(self.subtext), id="subheader6904007", style={"textAlign": "center"}),
                        style={"padding": "2% 0% 2% 0%"},
                    )
                )
            )

        header_container = dbc.Container(header_children, id="header1162572")

        return header_container

    def generate_io_container(self):

        input_output_components = dbc.Row(
            [
                dbc.Col(
                    self.inputs,
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
                ),
                dbc.Col(
                    self.outputs,
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
                ),
            ],
            justify="evenly",
            style={"padding": "2% 1% 10% 2%"} if self.minimal == False else {"padding": "0% 0% 0% 0%"},
        )

        io_container = dbc.Container([input_output_components], fluid=True)

        return io_container

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

    def refresh_layout(self):

        layout = dbc.Container(
            [
                self.navbar_container,
                self.header_container,
                self.io_container,
                self.footer_container,
            ],
            fluid=True,
        )

        self.layout = layout


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

    # If hint has the attribute "assign_prop", it indicates that hint is a FastComponent, return it
    if hasattr(hint, "assign_prop"):
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
            component = Fastify(dcc.Dropdown(options=default_value), "options")

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
            component = Fastify(
                dcc.Dropdown(default_value, multi=True), "value"
            )

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
                assign_prop="src",
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
                assign_prop="contents",
                ack=acknowledge_image_component,
            )

        else:
            acknowledge_image_component = Fastify(
                component=html.Img(width="100%", style={"padding": "1% 0% 0% 0%"}),
                assign_prop="src",
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
                assign_prop="contents",
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
                component = Fastify(dbc.Input(value=default_value, type="number"), "value")

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
                assign_prop="src")
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
                    assign_prop="contents",
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

    if hasattr(_hint_type, "assign_prop"):
        return _hint_type

    # If hint is not type, assume that the user specified an object. Change it to type
    if not isinstance(_hint_type, type):
        _hint_type = type(_hint_type)

    if issubclass(_hint_type, PIL.ImageFile.ImageFile):
        component = Image

    else:
        component = Fastify(html.H1(), "children")

    return component


def _infer_components(func, is_input=True):
    signature = inspect.signature(func)
    components = []

    if is_input == True:
        parameters = signature.parameters.items()
        for _, value in parameters:
            hint = value.annotation
            default = None if value.default == inspect._empty else value.default

            component = _get_component_from_input(hint, default)
            components.append(component)

    else:
        parameters = enumerate(
            signature.return_annotation
            if isinstance(signature.return_annotation, tuple)
            else [signature.return_annotation]
        )

        for _, hint in parameters:
            components.append(_get_output_components(hint))

    return components


###################################
# Define default components #
###################################

##### General components
Text = Fastify(component=dbc.Input(), assign_prop="value")

TextArea = Fastify(component=dbc.Textarea(), assign_prop="value")

Slider = Fastify(
    component=dcc.Slider(
        min=0,
        max=20,
        step=1,
        value=10,
        tooltip={"placement": "top", "always_visible": True},
    ),
    assign_prop="value",
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
    assign_prop="contents",
)

acknowledge_image_component = Fastify(
    component=html.Img(width="100%", style={"padding": "1% 0% 0% 0%"}),
    assign_prop="src",
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
    assign_prop="contents",
    ack=acknowledge_image_component,
)


##### Output components
Image = Fastify(component=html.Img(width="100%"), assign_prop="src")

Graph = Fastify(
    component=dcc.Graph(),
    assign_prop="figure",
    placeholder=(
        go.Figure()
        .update_yaxes(visible=False, showticklabels=False)
        .update_xaxes(visible=False, showticklabels=False)
    ),
)

