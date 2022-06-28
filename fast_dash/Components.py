from collections.abc import Iterable
import dash_bootstrap_components as dbc
import plotly.graph_objs as go
from dash import dcc, html
import inspect
import numbers
import warnings


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

        # Bring all containers together
        self.navbar_container = self.generate_navbar_container()
        self.header_container = self.generate_header_container()
        self.io_container = self.generate_io_container()
        self.footer_container = self.generate_footer_container()

        layput_components = [
            self.navbar_container,
            self.header_container,
            self.io_container,
            self.footer_container,
        ]

        self.layout = dbc.Container(
            [component for component in layput_components if component is not None],
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
            [navbar], fluid=True, style={"padding": "0 0 0 0"}
        )

        return navbar_container

    def generate_header_container(self):

        header_children = []

        if self.title is not None:
            header_children.append(
                dbc.Row(
                    html.H1(self.title, style={"textAlign": "center"}, id="app_title"),
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
                        html.H4(html.I(self.subtext), style={"textAlign": "center"}),
                        style={"padding": "2% 0% 2% 0%"},
                    )
                )
            )

        header_container = dbc.Container(header_children)

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
            style={"padding": "2% 1% 10% 2%"},
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
            [footer], fluid=True, style={"padding": "0 0 0 2%"}
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


def Fastify(component, assign_prop, ack=None, placeholder=None, label_=None):
    "Modify a Dash component to a FastComponent"

    component.assign_prop = assign_prop
    component.ack = ack
    component.label_ = label_
    component.placeholder = placeholder

    return component


def _infer_components(func, is_input=True):
    signature = inspect.signature(func)
    components = []
    
    if is_input == True:
        parameters = signature.parameters.items()
    else:
        parameters = enumerate(signature.return_annotation if isinstance(signature.return_annotation, Iterable) else [signature.return_annotation])

    for _, value in parameters:
        hint = value.annotation if is_input == True else value

        if hasattr(hint, 'assign_prop'): # Indicates that it is a FastComponent
            components.append(hint)

        elif isinstance(hint, range):
            slider_component = Fastify(dcc.Slider(min=hint.start, max=hint.stop, step=hint.step), assign_prop='value')
            components.append(slider_component)

        elif isinstance(hint, Iterable):
            slider_component = Fastify(dcc.Dropdown(hint), assign_prop='value')
            components.append(slider_component)
            
        elif hint in [int, float, complex]:
            number_input = Fastify(dbc.Input(type='number'), assign_prop='value')
            components.append(number_input)

        elif hint == str: # String indicates Text
            components.append(Text)
            
        elif hint == bool: # String indicates Text
            switch = Fastify(dbc.Switch(), assign_prop='value')
            components.append(switch)
            
        elif hint == inspect._empty: # String indicates Text
            warnings.warn("Unspecified type hint. Assuming Text. This could lead to unexpected results.")
            components.append(Text)

        else:
            raise Exception(f"Unsupported type {hint}. Explicitly specify a FastComponent or changing the data type.")            
    
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
    assign_prop="src"
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

