import dash_bootstrap_components as dbc
import plotly.graph_objs as go
from dash import dcc, html


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
        footer=True
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

        self.layout = dbc.Container([component for component in layput_components if component is not None], fluid=True,)

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
            fixed="top",
        )

        navbar_container = dbc.Container([navbar], fluid=True)

        return navbar_container

    def generate_header_container(self):

        header_children = []

        if self.title is not None:
            header_children.append(
                dbc.Row(
                    html.H1(self.title, style={"textAlign": "center"}),
                    style={"padding": "8% 0% 2% 0%"},
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
            brand_href="https://dkedar7.github.io/fast_dash/",
            color="primary",
            dark=True,
            fluid=True,
            fixed="bottom",
        )

        footer_container = dbc.Container([footer], fluid=True)

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


def Fastify(DashComponent, modify_property, label_=None, placeholder=None, **kwargs):
    """
    Component utility to convert any Dash component into a FastComponent.    
    """

    class FastComponent(DashComponent):
        """
        Extends component
        """

        def __init__(
            self,
            modify_property=modify_property,
            label_=label_,
            placeholder=placeholder,
            **kwargs
        ):
            super().__init__(**kwargs)
            self.modify_property = modify_property
            self.placeholder = placeholder
            self.label_ = label_

    return FastComponent(
        modify_property, label_=label_, placeholder=placeholder, **kwargs
    )


###################################
# Define default components #
###################################

Text = Fastify(DashComponent=dbc.Input, modify_property="value")

Slider = Fastify(
    DashComponent=dcc.Slider,
    modify_property="value",
    min=0,
    max=20,
    step=1,
    value=10,
    tooltip={"placement": "top", "always_visible": True},
)

Upload = Fastify(
    DashComponent=dcc.Upload,
    modify_property="contents",
    children=dbc.Col(["Click to upload"]),
    style={
        "lineHeight": "60px",
        "borderWidth": "1px",
        "borderStyle": "dashed",
        "borderRadius": "5px",
        "textAlign": "center",
    },
)

TextArea = Fastify(DashComponent=dbc.Textarea, modify_property="value")

Image = Fastify(DashComponent=html.Img, modify_property="src", width="100%")

Graph = Fastify(
    DashComponent=dcc.Graph,
    modify_property="figure",
    placeholder=(
        go.Figure()
        .update_yaxes(visible=False, showticklabels=False)
        .update_xaxes(visible=False, showticklabels=False)
    ),
)
