import functools
import logging
import re
import traceback
import uuid
import warnings

from plotly.io.json import to_json_plotly
import json

import dash
import flask
from flask_socketio import SocketIO, emit
from dash import Input, Output, State, ctx, clientside_callback
from dash.exceptions import PreventUpdate
from dash_socketio import DashSocketIO

import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import html as dash_html

from .Components import (
    AppLayout,
    _infer_input_components,
    _infer_output_components,
)

from .utils import (
    _assign_ids_to_inputs,
    _assign_ids_to_outputs,
    _get_transform_function,
    _make_input_groups,
    _make_output_groups,
    _transform_inputs,
    _transform_outputs,
    theme_mapper,
    _infer_variable_names,
    _parse_docstring_as_markdown,
    _get_error_notification_component,
)

import contextvars
import functools
import asyncio
from types import GeneratorType

# Create context variable to hold the stream handler
stream_handler_var = contextvars.ContextVar('stream_handler', default=None)
    
# Context manager for easier usage
class StreamContext:
    def __init__(self, handler_func, chat_handler_func=None):
        self.handler_func = handler_func
        self.token = None
        
    def __enter__(self):
        self.token = stream_handler_var.set(self.handler_func)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token is not None:
            stream_handler_var.reset(self.token)

def update(component, data, property=None):
    """When called in user code, invokes the current context's handler"""
    handler = stream_handler_var.get()

    if handler is not None:
        return handler(component, data, property=property, notification=False)
    
def notify(data, action="show"):
    """When called in user code, invokes the current context's handler"""
    handler = stream_handler_var.get()
    component = "notification-container"

    if handler is not None:
        data = [{
            "action": action,
            "id": f"show_notification_to_the_web_app_{str(uuid.uuid4())}",
            "message": data
        }]
        return handler(component, data, notification=True)
    

class FastDash:
    """
    Fast Dash app object containing automatically generated UI components and callbacks.

    This is the primary Fast Dash data structure. Can be thought of as a wrapper around
    a flask WSGI application. It has in-built support for automated UI generation and
    sets all parameters required for Fast Dash app deployment.
    """

    def __init__(
        self,
        callback_fn,
        mosaic=None,
        inputs=None,
        outputs=None,
        output_labels="infer",
        title=None,
        title_image_path=None,
        subheader=None,
        github_url=None,
        linkedin_url=None,
        twitter_url=None,
        navbar=True,
        footer=True,
        loader="bars",
        branding=False,
        stream=False,
        about=True,
        theme=None,
        update_live=False,
        port=8080,
        mode=None,
        minimal=False,
        disable_logs=False,
        scale_height=1,
        run_kwargs=dict(),
        tab_titles=None,
        **kwargs
    ):
        """
        Args:
            callback_fn (func or list of funcs): Python function (or list of functions) that Fast Dash deploys. \
                This function guides the behavior of and interaction between input and output components. \
                Passing a list of functions creates a tabbed multi-function app, one tab per function.

            mosaic (str, optional): Mosaic string specifying how output components are arranged in the main area.

            inputs (Fast component, list of Fast components, optional): Components to represent inputs of the callback function.\
                Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type \
                hints and default values. In the absence of type hints, default components are all `Text`.

            outputs (Fast component, list of Fast components, optional): Components to represent outputs of the callback function.\
                Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type hints.\
                In the absence of type hints, default components are all `Text`.

            output_labels(list of string labels or "infer" or None, optional): Labels given to the output components. If None, inputs are\
                set labeled integers starting at 1 (Output 1, Output 2, and so on). If "infer", labels are inferred from the function\
                signature. Defaults to infer.

            title (str, optional): Title given to the app. If `None`, function name (assumed to be in snake case)\
                is converted to title case. Defaults to None.

            title_image_path (str, optional): Path (local or URL) of the app title image. Defaults to None.

            subheader (str, optional): Subheader of the app, displayed below the title image and title\
                If `None`, Fast Dash tries to use the callback function's docstring instead. Defaults to None.
                
            github_url (str, optional): GitHub URL for branding. Displays a GitHub logo in the navbar, which takes users to the\
                specified URL. Defaults to None.

            linkedin_url (str, optional): LinkedIn URL for branding Displays a LinkedIn logo in the navbar, which takes users to the\
                specified URL. Defaults to None.

            twitter_url (str, optional): Twitter URL for branding. Displays a Twitter logo in the navbar, which takes users to the\
                specified URL. Defaults to None.

            navbar (bool, optional): Display navbar. Defaults to True.

            footer (bool, optional): Display footer. Defaults to True.

            loader (str or bool, optional): Type of loader to display when the app is loading. If `None`, no loader is displayed. \
                If `True`, a default loader is displayed. If `str`, the loader is set to the specified type. \
                
            branding (bool, optional): Display Fast Dash branding component in the footer. Defaults to False. \
            
            stream (bool, optional): Enable streaming functionality. If True, the app will use DashSocketIO to handle streaming data. \
                If False, streaming is disabled. Defaults to False. \

            about (Union[str, bool], optional): App description to display on clicking the `About` button. If True, content is inferred from\
                the docstring of the callback function. If string, content is used directly as markdown. \
                `About` is hidden if False or None. Defaults to True.

            theme (str, optional): Apply theme to the app.All available themes can be found at https://bootswatch.com/. Defaults to JOURNAL. 

            update_live (bool, optional): Enable hot reloading. If the number of inputs is 0, this is set to True automatically. Defaults to False.

            port (int, optional): Port to which the app should be deployed. Defaults to 8080.

            mode (str, optional): Mode in which to launch the app. Acceptable options are `None`, `jupyterlab`, `inline`, 'external`.\
                Defaults to None.

            minimal (bool, optional): Display minimal version by hiding navbar, title, title image, subheader and footer. Defaults to False.

            disable_logs (bool, optional): Hide app logs. Sets logger level to `ERROR`. Defaults to False.

            scale_height (float, optional): Height of the app container is enlarged as a multiple of this. Defaults to 1.

            run_kwargs (dict, optional): All values from this variable are passed to Dash's `.run` method.

            tab_titles (list of str, optional): Tab titles when ``callback_fn`` is a list of functions. \
                If None, tab titles are derived from the function names. Ignored for single-function apps. Defaults to None.
        """

        # Detect multi-function mode
        self.is_multi = isinstance(callback_fn, list)
        if self.is_multi:
            self.callback_fns = callback_fn
            self.tab_titles = tab_titles
            callback_fn = callback_fn[0]  # Use first function for shared chrome
        else:
            self.callback_fns = [callback_fn]
            self.tab_titles = None

        self.mode = mode
        self.disable_logs = disable_logs
        self.scale_height = scale_height
        self.port = port
        self.run_kwargs = run_kwargs
        self.run_kwargs.update(dict(port=port))
        self.kwargs = kwargs

        if self.disable_logs is True:
            log = logging.getLogger("werkzeug")
            log.setLevel(logging.ERROR)

        else:
            log = logging.getLogger("werkzeug")
            log.setLevel(logging.DEBUG)

        if title is None:
            title = re.sub("[^0-9a-zA-Z]+", " ", callback_fn.__name__).title()

        self.title = title

        self.title_image_path = title_image_path
        self.subtitle = (
            subheader
            if subheader is not None
            else _parse_docstring_as_markdown(
                callback_fn, title=self.title, get_short=True
            )
        )
        self.github_url = github_url
        self.linkedin_url = linkedin_url
        self.twitter_url = twitter_url
        self.navbar = navbar
        self.footer = footer
        self.loader = loader
        self.branding = branding
        self.stream = stream
        self.about = about
        self.theme = theme or "JOURNAL"
        self.minimal = minimal

        # Define Flask server
        server = flask.Flask(__name__)
        external_stylesheets = [
            theme_mapper(self.theme),
            "https://use.fontawesome.com/releases/v5.9.0/css/all.css",
        ]

        source = dash.Dash
        self.app = source(
            __name__,
            external_stylesheets=external_stylesheets,
            server=server,
            **self.kwargs,
        )

        # Allow easier access to Dash server
        self.server = self.app.server
        self.callback = self.app.callback

        if stream == True:
            socketio = SocketIO(self.app.server)

        # Define other attributes
        self.callback_fn = callback_fn
        self.mosaic = mosaic
        self.output_labels = output_labels
        self.update_live = update_live

        if self.is_multi:
            self._init_multi_function()
        else:
            self._init_single_function(callback_fn, inputs, outputs, output_labels, update_live)

    def _init_single_function(self, callback_fn, inputs, outputs, output_labels, update_live):
        """Initialize a single-function Fast Dash app (original behavior)."""

        # Initialize state indicators
        self.state_counter = 0

        if output_labels == "infer":
            self.output_labels = _infer_variable_names(callback_fn, upper_case=True)

        self.inputs = (
            _infer_input_components(callback_fn)
            if inputs is None
            else inputs if isinstance(inputs, list) else [inputs]
        )
        self.outputs = _infer_output_components(
            callback_fn, outputs, self.output_labels
        )
        self.update_live = (
            True
            if (isinstance(self.inputs, list) and len(self.inputs) == 0)
            else update_live
        )

        # Extract input tags
        self.input_tags = [inp.tag for inp in self.inputs]
        self.output_tags = [inp.tag for inp in self.outputs]

        # Assign IDs to components
        self.inputs_with_ids = _assign_ids_to_inputs(self.inputs, self.callback_fn)
        self.outputs_with_ids = _assign_ids_to_outputs(self.outputs, self.callback_fn)
        self.ack_mask = [
            False if (not hasattr(input_, "ack") or (input_.ack is None)) else True
            for input_ in self.inputs_with_ids
        ]

        # Default state of outputs
        self.output_state_default = [
            output_.placeholder if hasattr(output_, "placeholder") else None
            for output_ in self.outputs_with_ids
        ]
        self.output_state = self.output_state_default

        self.output_state_blank = [None for output_ in self.outputs_with_ids]
        self.latest_output_state = self.output_state_blank

        # Intialize layout
        self.app.title = self.title or ""
        self.set_layout()

        # Register callbacks
        self.register_callback_fn()
        self.add_streaming()

        # Keep track of the number of clicks
        self.submit_clicks = 0
        self.reset_clicks = 0
        self.app_initialized = False

    def _init_multi_function(self):
        """Initialize a multi-function tabbed Fast Dash app."""
        self.func_data = []

        for idx, fn in enumerate(self.callback_fns):
            prefix = f"func{idx}_"

            fn_output_labels = _infer_variable_names(fn, upper_case=True)
            fn_inputs = _infer_input_components(fn)
            fn_outputs = _infer_output_components(fn, None, fn_output_labels)

            fn_update_live = (
                True if (isinstance(fn_inputs, list) and len(fn_inputs) == 0)
                else self.update_live
            )

            input_tags = [inp.tag for inp in fn_inputs]
            output_tags = [out.tag for out in fn_outputs]

            inputs_with_ids = _assign_ids_to_inputs(fn_inputs, fn, prefix=prefix)
            outputs_with_ids = _assign_ids_to_outputs(fn_outputs, fn, prefix=prefix)

            ack_mask = [
                False if (not hasattr(input_, "ack") or (input_.ack is None)) else True
                for input_ in inputs_with_ids
            ]

            output_state_default = [
                output_.placeholder if hasattr(output_, "placeholder") else None
                for output_ in outputs_with_ids
            ]

            self.func_data.append({
                "fn": fn,
                "prefix": prefix,
                "inputs": fn_inputs,
                "outputs": fn_outputs,
                "input_tags": input_tags,
                "output_tags": output_tags,
                "inputs_with_ids": inputs_with_ids,
                "outputs_with_ids": outputs_with_ids,
                "ack_mask": ack_mask,
                "output_state_default": list(output_state_default),
                "output_state": list(output_state_default),
                "output_state_blank": [None for _ in outputs_with_ids],
                "latest_output_state": [None for _ in outputs_with_ids],
                "update_live": fn_update_live,
                "state_counter": 0,
                "app_initialized": False,
            })

        # Set references for backward compat
        self.inputs_with_ids = self.func_data[0]["inputs_with_ids"]
        self.outputs_with_ids = self.func_data[0]["outputs_with_ids"]

        self.app.title = self.title or ""
        self.set_layout()
        self.register_callback_fn()
        self.add_streaming()

    def run(self):
        self.app.run(**self.run_kwargs) if self.mode is None else self.app.run(
            jupyter_mode=self.mode, **self.run_kwargs
        )

    def run_server(self):
        self.app.run(
            **self.run_kwargs
        ) if self.mode is None else self.app.run(
            jupyter_mode=self.mode, **self.run_kwargs
        )

    def set_layout(self):
        if self.is_multi:
            self._set_multi_layout()
            return

        if self.inputs is not None:
            input_groups = _make_input_groups(self.inputs_with_ids, self.update_live)

        if self.outputs is not None:
            output_groups = _make_output_groups(self.outputs_with_ids, self.update_live)

        layout_args = {
            "mosaic": self.mosaic,
            "inputs": input_groups,
            "outputs": output_groups,
            "title": self.title,
            "title_image_path": self.title_image_path,
            "subtitle": self.subtitle,
            "github_url": self.github_url,
            "linkedin_url": self.linkedin_url,
            "twitter_url": self.twitter_url,
            "navbar": self.navbar,
            "footer": self.footer,
            "loader": self.loader,
            "branding": self.branding,
            "about": self.about,
            "minimal": self.minimal,
            "scale_height": self.scale_height,
            "theme": self.theme,
            "app": self,
        }

        app_layout = AppLayout(**layout_args)
        self.layout_object = app_layout
        notification_components = ["notification-container"]

        streaming_components = [c.id for c in self.outputs_with_ids if c.stream == True]
        streaming_components.extend(notification_components)

        # Add responses of chat components if present
        chat_components = [c for c in self.outputs_with_ids if c.tag == "Chat" and c.stream == True]

        for component in chat_components:
            [streaming_components.append(f"{component.id}_{i + 1}_response") for i in range(getattr(component, "stream_limit", 10))]

        self.app.layout = app_layout.generate_layout(stream_event_names=streaming_components)

    def _set_multi_layout(self):
        """Build a tabbed layout for multi-function mode."""
        from dash_iconify import DashIconify as _DashIconify
        from dash import dcc as _dcc

        tabs = []
        all_streaming_components = ["notification-container"]

        for idx, fd in enumerate(self.func_data):
            prefix = fd["prefix"]
            input_groups = _make_input_groups(fd["inputs_with_ids"], fd["update_live"], prefix=prefix)
            output_groups = _make_output_groups(fd["outputs_with_ids"], fd["update_live"], prefix=prefix)

            # Tab title and subtitle from function
            if self.tab_titles and idx < len(self.tab_titles):
                tab_title = self.tab_titles[idx]
            else:
                tab_title = re.sub("[^0-9a-zA-Z]+", " ", fd["fn"].__name__).title()

            fn_subtitle = _parse_docstring_as_markdown(
                fd["fn"], title=tab_title, get_short=True
            )

            # Per-tab header (title + subtitle)
            tab_header_children = [
                dbc.Row(
                    dash_html.H2(tab_title, style={"textAlign": "center"}),
                    style={"padding": "1% 0% 0% 0%"},
                ),
            ]
            if fn_subtitle:
                tab_header_children.append(
                    dbc.Row(
                        dash_html.H5(fn_subtitle, style={"textAlign": "center", "color": "#666"}),
                        style={"padding": "0% 0% 1% 0%"},
                    )
                )

            tab_header = dbc.Container(tab_header_children)

            # Build sidebar-style content for this tab
            tab_content = dbc.Row([
                dbc.Col(
                    children=[dmc.Stack(children=input_groups)],
                    id=f"{prefix}input-group",
                    xs=12, md=2,
                    style={
                        "background-color": "#F5F7F7",
                        "display": "block",
                        "padding": "2% 20px 0 20px",
                        "height": f"{self.scale_height * 80}vh",
                    },
                    class_name="border border-right",
                ),
                dbc.Col([
                    tab_header,
                    dmc.LoadingOverlay(
                        id=f"{prefix}loading-overlay",
                        loaderProps=dict(type=self.loader) if self.loader else {},
                    ),
                    dash_html.Div(id=f"{prefix}dummy-div", style={"display": "none"}),
                    dbc.Col(
                        output_groups,
                        class_name="g-1 d-flex flex-fill flex-column",
                        style={"height": f"{self.scale_height * 65}vh"},
                    ),
                ], style={"padding": "1% 2% 0 2%"}),
            ], class_name="d-flex")

            tabs.append(dbc.Tab(tab_content, label=tab_title, tab_id=f"tab-{idx}"))

            # Collect streaming components
            for c in fd["outputs_with_ids"]:
                if getattr(c, "stream", False):
                    all_streaming_components.append(c.id)
                    if c.tag == "Chat":
                        for i in range(getattr(c, "stream_limit", 10)):
                            all_streaming_components.append(f"{c.id}_{i + 1}_response")

        tabs_component = dbc.Tabs(tabs, id="multi-function-tabs", active_tab="tab-0")

        # Build navbar
        navbar_components = []
        if self.about:
            navbar_components.append(
                dbc.NavLink("About", id="about-navlink",
                            style={"cursor": "pointer", "color": "white"})
            )

        social_links = []
        if self.github_url:
            social_links.append(
                dbc.NavLink(dash_html.I(className="fab fa-github fa-lg"),
                            href=self.github_url, target="_blank")
            )
        if self.linkedin_url:
            social_links.append(
                dbc.NavLink(dash_html.I(className="fab fa-linkedin fa-lg"),
                            href=self.linkedin_url, target="_blank")
            )
        if self.twitter_url:
            social_links.append(
                dbc.NavLink(dash_html.I(className="fab fa-twitter fa-lg"),
                            href=self.twitter_url, target="_blank")
            )
        navbar_components.extend(social_links)

        app_navbar = dbc.NavbarSimple(
            children=navbar_components,
            brand=self.title or "",
            color="primary",
            dark=True,
            fluid=True,
            expand=True,
            style={"padding": "0 0 0 0"},
        ) if self.navbar and not self.minimal else dash_html.Div()

        # About modal
        about_modal = dbc.Modal(
            id="about-modal", is_open=False, size="lg",
        ) if self.about else dash_html.Div(id="about-modal", style={"display": "none"})

        # Footer (rocket icon)
        if self.branding and self.footer and not self.minimal:
            footer = dmc.Affix(
                dmc.Tooltip(
                    label="Made with Fast Dash!",
                    position="top",
                    withArrow=True,
                    transitionProps={"duration": 300},
                    children=_dcc.Link(
                        dmc.Button(
                            _DashIconify(icon="ion:rocket-sharp", width=20), radius=500
                        ),
                        href="https://github.com/dkedar7/fast_dash",
                        target="_blank",
                    ),
                ),
                position={"bottom": "20px", "right": "20px"},
            )
        else:
            footer = dash_html.Div()

        self.app.layout = dmc.MantineProvider([
            dmc.NotificationContainer(id="notification-container", position="bottom-right"),
            dash_html.Div(id="dummy-div", style={"display": "none"}),
            dbc.Container([
                dbc.Row([app_navbar], style={"padding": "0 0 0 0"}),
                about_modal,
                tabs_component,
                footer,
                DashSocketIO(id="socketio", eventNames=all_streaming_components) if self.stream else dash_html.Div(id="socketio", style={"display": "none"}),
            ], fluid=True, style={"height": "100vh", "width": "100%"}),
        ])

    def register_callback_fn(self):
        if self.is_multi:
            self._register_multi_callbacks()
            return

        self.app.clientside_callback(
            f"""
            function updateLoadingState(n_clicks) {{
                return {"true" if self.loader else "false"};
            }}
            """,
            Output("loading-overlay", "visible", allow_duplicate=True),
            Input("submit_inputs", "n_clicks"),
            prevent_initial_call=True,
        )

        @self.app.callback(
            [
                Output(
                    component_id=output_.id,
                    component_property=output_.component_property,
                )
                for output_ in self.outputs_with_ids
            ]
            + [Output("notification-container", "sendNotifications"), Output("loading-overlay", "visible")],
            [
                Input(
                    component_id=input_.id, component_property=input_.component_property
                )
                for input_ in self.inputs_with_ids
            ]
            + [
                Input(component_id="reset_inputs", component_property="n_clicks"),
                Input(component_id="submit_inputs", component_property="n_clicks")
            ]
            + [
                State("socketio", "socketId") if self.stream == True else []
            ],
            running=[(Output("submit_inputs", "disabled"), True, False)],
            prevent_initial_call=False
        )
        def process_input(*args):
            if (
                ctx.triggered_id not in ["submit_inputs", "reset_inputs"]
                and self.update_live is False
            ):
                raise PreventUpdate

            default_notification = []
            self.state_counter += 1

            try:
                inputs = _transform_inputs(args[:-3], self.input_tags)

                if ctx.triggered_id == "submit_inputs" or (
                    self.update_live is True and None not in args
                ):
                    self.app_initialized = True

                    stream_handler_func = functools.partial(self.stream_handler, socket_id=args[-1])
                    with StreamContext(stream_handler_func):
                        output_state = self.callback_fn(*inputs)

                    if isinstance(output_state, tuple):
                        self.output_state = list(output_state)

                    else:
                        self.output_state = [output_state]

                    # Transform outputs to fit in the desired components
                    self.output_state = _transform_outputs(
                        self.output_state, self.output_tags, self.outputs_with_ids, self.state_counter
                    )

                    # Log the latest output state
                    self.latest_output_state = self.output_state

                    return self.output_state + [default_notification, False]

                elif ctx.triggered_id == "reset_inputs":
                    self.output_state = self.output_state_default
                    return self.output_state + [default_notification, False]

                elif self.app_initialized:
                    return self.output_state + [default_notification, False]

                else:
                    return self.output_state_default + [default_notification, False]

            except Exception as e:
                traceback.print_exc()
                notification = _get_error_notification_component(str(e))

                return self.output_state_default + [notification, False]

        @self.app.callback(
            [
                Output(
                    component_id=input_.ack.id,
                    component_property=input_.ack.component_property,
                )
                for input_ in self.inputs_with_ids
            ]
            + [Output("dummy-div", "children")],
            [
                Input(
                    component_id=input_.id, component_property=input_.component_property
                )
                for input_ in self.inputs_with_ids
            ]
            + [Input("dummy-div", "children")],
        )
        def process_ack_outputs(*args):
            ack_components = [
                ack if mask is True else None
                for mask, ack in zip(self.ack_mask, list(args)[:-1])
            ]
            return ack_components + [[]]

        # Set layout callbacks
        if not self.minimal:
            self.layout_object.callbacks(self)

        # Wire download buttons: click -> copy Store data to dcc.Download
        for c in self.outputs_with_ids:
            if c.tag == "Download":
                self._register_download_callback(c.id)

    def _register_download_callback(self, component_id, prefix=""):
        """Register a clientside callback that triggers dcc.Download on button click."""
        store_id = f"{component_id}_download_store"
        download_id = f"{component_id}_download_trigger"
        btn_id = f"{component_id}_download_btn"

        self.app.clientside_callback(
            """
            function(n_clicks, data) {
                if (!n_clicks || !data) { return dash_clientside.no_update; }
                return data;
            }
            """,
            Output(download_id, "data"),
            Input(btn_id, "n_clicks"),
            State(store_id, "data"),
            prevent_initial_call=True,
        )

    def _register_multi_callbacks(self):
        """Register per-function callbacks for multi-function mode."""
        for idx, fd in enumerate(self.func_data):
            self._register_fn_callback(idx, fd)

        # About modal callback
        if self.about and not self.minimal:
            @self.app.callback(
                Output("about-modal", "is_open"),
                Output("about-modal", "children"),
                Input("about-navlink", "n_clicks"),
                State("about-modal", "is_open"),
                prevent_initial_call=True,
            )
            def toggle_about(n_clicks, is_open):
                if n_clicks:
                    sections = []
                    for fd_ in self.func_data:
                        fn = fd_["fn"]
                        fn_title = re.sub("[^0-9a-zA-Z]+", " ", fn.__name__).title()
                        about_text = _parse_docstring_as_markdown(fn, title=fn_title)
                        from dash import dcc
                        sections.append(dcc.Markdown(about_text))
                        sections.append(dash_html.Hr())
                    return not is_open, dash_html.Div(sections[:-1])  # Remove trailing Hr
                raise PreventUpdate

    def _register_fn_callback(self, idx, fd):
        """Register callbacks for a single function in multi-function mode."""
        prefix = fd["prefix"]

        # Loading state callback
        self.app.clientside_callback(
            f"""
            function updateLoadingState(n_clicks) {{
                return {"true" if self.loader else "false"};
            }}
            """,
            Output(f"{prefix}loading-overlay", "visible", allow_duplicate=True),
            Input(f"{prefix}submit_inputs", "n_clicks"),
            prevent_initial_call=True,
        )

        # Main process callback
        @self.app.callback(
            [
                Output(o.id, o.component_property)
                for o in fd["outputs_with_ids"]
            ]
            + [
                Output("notification-container", "sendNotifications", allow_duplicate=True),
                Output(f"{prefix}loading-overlay", "visible"),
            ],
            [
                Input(i.id, i.component_property)
                for i in fd["inputs_with_ids"]
            ]
            + [
                Input(f"{prefix}reset_inputs", "n_clicks"),
                Input(f"{prefix}submit_inputs", "n_clicks"),
            ]
            + ([State("socketio", "socketId")] if self.stream else []),
            running=[(Output(f"{prefix}submit_inputs", "disabled"), True, False)],
            prevent_initial_call="initial_duplicate",
        )
        def process_input(*args, _fd=fd, _prefix=prefix):
            submit_id = f"{_prefix}submit_inputs"
            reset_id = f"{_prefix}reset_inputs"

            if ctx.triggered_id not in [submit_id, reset_id] and _fd["update_live"] is False:
                raise PreventUpdate

            default_notification = []
            _fd["state_counter"] += 1

            try:
                num_extra = 3 if self.stream else 2
                inputs = _transform_inputs(args[:-num_extra], _fd["input_tags"])

                if ctx.triggered_id == submit_id or (
                    _fd["update_live"] is True and None not in args
                ):
                    _fd["app_initialized"] = True

                    if self.stream:
                        stream_handler_func = functools.partial(
                            self.stream_handler, socket_id=args[-1], func_data=_fd
                        )
                    else:
                        stream_handler_func = lambda *a, **kw: None

                    with StreamContext(stream_handler_func):
                        output_state = _fd["fn"](*inputs)

                    if isinstance(output_state, tuple):
                        _fd["output_state"] = list(output_state)
                    else:
                        _fd["output_state"] = [output_state]

                    _fd["output_state"] = _transform_outputs(
                        _fd["output_state"], _fd["output_tags"],
                        _fd["outputs_with_ids"], _fd["state_counter"]
                    )
                    _fd["latest_output_state"] = _fd["output_state"]
                    return _fd["output_state"] + [default_notification, False]

                elif ctx.triggered_id == reset_id:
                    _fd["output_state"] = list(_fd["output_state_default"])
                    return _fd["output_state"] + [default_notification, False]

                elif _fd["app_initialized"]:
                    return _fd["output_state"] + [default_notification, False]

                else:
                    return _fd["output_state_default"] + [default_notification, False]

            except Exception as e:
                traceback.print_exc()
                notification = _get_error_notification_component(str(e))
                return _fd["output_state_default"] + [notification, False]

        # Ack callback
        ack_inputs = [i for i in fd["inputs_with_ids"] if hasattr(i, "ack") and i.ack is not None]
        if ack_inputs or fd["inputs_with_ids"]:
            @self.app.callback(
                [
                    Output(i.ack.id, i.ack.component_property)
                    for i in fd["inputs_with_ids"]
                ]
                + [Output(f"{prefix}dummy-div", "children")],
                [
                    Input(i.id, i.component_property)
                    for i in fd["inputs_with_ids"]
                ]
                + [Input(f"{prefix}dummy-div", "children")],
            )
            def process_ack(*args, _fd=fd):
                ack_components = [
                    ack if mask else None
                    for mask, ack in zip(_fd["ack_mask"], list(args)[:-1])
                ]
                return ack_components + [[]]

    # Define a stream handler function
    def stream_handler(self, component_id, data, property=None, socket_id=None, notification=True, func_data=None):
        """A simple handler that prints to console and returns a response"""

        if self.stream == False:
            return

        if notification:
            emit(component_id, {"value": data, "append": False}, namespace="/", to=socket_id)
            return f"Notification: {data}"

        outputs_to_search = func_data["outputs_with_ids"] if func_data else self.outputs_with_ids
        prefix = func_data["prefix"] if func_data else ""
        component = [c for c in outputs_to_search if c.id == f"{prefix}output_{component_id}"]

        if not component:
            raise ValueError(f"Component with id {component_id} not found in outputs.")

        component = component[0]
        component_id = component.id

        if component.tag == "Chat" and not property:
            raise ValueError("Argument 'property' must be specified for chat components. Allowed 'property' values are 'query' and 'response'.")

        if component.tag == "Chat" and property  not in ["query", "response"]:
            raise ValueError("Invalid 'property' value for chat component. Allowed 'property' values are 'query' and 'response'.")
    
        counter = func_data["state_counter"] if func_data else self.state_counter
        component_state_func = _get_transform_function(output=data,
                                                       tag=component.tag,
                                                       component_id=component.id,
                                                       counter=counter,
                                                       partial_update=True)


        if component.tag == "Chat" and property == "query":

            # Add a new component to the chat response
            data = dict(query=data, response="")
            component_state = json.loads(to_json_plotly(component_state_func(data)))
            # component.stream = True

            emit(component_id, {"value": component_state, "append": True}, namespace="/", to=socket_id)

        elif component.tag == "Chat" and property == "response":
            component_id = f"{component_id}_{counter}_response"

            emit(component_id, {"value": data, "append": False}, namespace="/", to=socket_id)

        else:
            emit(component_id, {"value": data, "append": False}, namespace="/", to=socket_id)

        return f"Received: {data}"
    

    def add_streaming(self):
        """Add streaming functionality to the app."""

        update_func = """
            function(payload, current_value) {
                if (!payload) {
                    return dash_clientside.no_update;
                }

                const { value, append } = payload;

                if (value === null || value === undefined) {
                    return dash_clientside.no_update;
                }

                let new_value;

                // Parse the incoming value if it's a string
                if (typeof value === 'string' && value !== '') {
                    try {
                        new_value = JSON.parse(value);
                    } catch (e) {
                        new_value = value;
                    }
                } else {
                    new_value = value;
                }

                // If append is true, combine with current value
                if (append) {
                    const current = current_value || [];
                    const current_array = Array.isArray(current) ? current : [current];

                    if (Array.isArray(new_value)) {
                        return [...new_value, ...current_array];
                    } else {
                        return [new_value, ...current_array];
                    }
                }

                return new_value;
            }
            """

        # Collect all output components (multi or single)
        if self.is_multi:
            all_outputs = []
            for fd in self.func_data:
                all_outputs.extend(fd["outputs_with_ids"])
        else:
            all_outputs = self.outputs_with_ids

        for component in all_outputs:

            if getattr(component, "stream") == False:
                continue

            # All clientside callbacks
            self.app.clientside_callback(
                update_func,
                Output(component.id, component.component_property, allow_duplicate=True),
                Input("socketio", f"data-{component.id}"),
                State(component.id, component.component_property),
                prevent_initial_call=True,
            )

            if component.tag == "Chat":
                for i in range(getattr(component, "stream_limit", 10)):
                    c_id = f"{component.id}_{i + 1}_response"
                    self.app.clientside_callback(
                            update_func,
                            Output(c_id, "children", allow_duplicate=True),
                            Input("socketio", f"data-{c_id}"),
                            State(c_id, "children"),
                            prevent_initial_call=True,
                        )

        component_id = "notification-container"
        component_property = "sendNotifications"
        self.app.clientside_callback(
                update_func,
                Output(component_id, component_property, allow_duplicate=True),
                Input("socketio", f"data-{component_id}"),
                State(component_id, component_property),
                prevent_initial_call=True,
            )


def fastdash(
    _callback_fn=None,
    *,
    mosaic=None,
    inputs=None,
    outputs=None,
    output_labels="infer",
    title=None,
    title_image_path=None,
    subheader=None,
    github_url=None,
    linkedin_url=None,
    twitter_url=None,
    navbar=True,
    footer=True,
    loader="bars",
    branding=False,
    stream=False,
    about=True,
    theme=None,
    update_live=False,
    port=8080,
    mode=None,
    minimal=False,
    disable_logs=False,
    scale_height=1,
    run_kwargs=dict(),
    **kwargs
):
    """
    Function decorator / wrapper for Fast Dash.

    Decorates a single Python function and launches a Fast Dash app immediately.
    For multi-function tabbed apps, use ``FastDash([fn_a, fn_b, ...], tab_titles=[...]).run()`` directly.

    Args:
        callback_fn (func): Python function that Fast Dash deploys. \
            This function guides the behavior of and interaction between input and output components.

        mosaic (str, optional): Mosaic string specifying how output components are arranged in the main area.

        inputs (Fast component, list of Fast components, optional): Components to represent inputs of the callback function.\
            Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type \
            hints and default values. In the absence of type hints, default components are all `Text`.

        outputs (Fast component, list of Fast components, optional): Components to represent outputs of the callback function.\
            Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type hints.\
            In the absence of type hints, default components are all `Text`.

        output_labels(list of string labels or "infer" or None, optional): Labels given to the output components. If None, inputs are\
            set labeled integers starting at 1 (Output 1, Output 2, and so on). If "infer", labels are inferred from the function\
            signature. Defaults to infer.

        title (str, optional): Title given to the app. If `None`, function name (assumed to be in snake case)\
            is converted to title case. Defaults to None.

        title_image_path (str, optional): Path (local or URL) of the app title image. Defaults to None.

        subheader (str, optional): Subheader of the app, displayed below the title image and title\
            If `None`, Fast Dash tries to use the callback function's docstring instead. Defaults to None.
            

        github_url (str, optional): GitHub URL for branding. Displays a GitHub logo in the navbar, which takes users to the\
            specified URL. Defaults to None.

        linkedin_url (str, optional): LinkedIn URL for branding Displays a LinkedIn logo in the navbar, which takes users to the\
            specified URL. Defaults to None.

        twitter_url (str, optional): Twitter URL for branding. Displays a Twitter logo in the navbar, which takes users to the\
            specified URL. Defaults to None.

        navbar (bool, optional): Display navbar. Defaults to True.

        footer (bool, optional): Display footer. Defaults to True.

        loader (str or bool, optional): Type of loader to display when the app is loading. If `None`, no loader is displayed. \
                If `True`, a default loader is displayed. If `str`, the loader is set to the specified type. \
                
        branding (bool, optional): Display Fast Dash branding component in the footer. Defaults to False. \
        
        stream (bool, optional): Enable streaming functionality. If True, the app will use DashSocketIO to handle streaming data. \
            If False, streaming is disabled. Defaults to False.

        about (Union[str, bool], optional): App description to display on clicking the `About` button. If True, content is inferred from\
            the docstring of the callback function. If string, content is used directly as markdown. \
            `About` is hidden if False or None. Defaults to True.

        theme (str, optional): Apply theme to the app.All available themes can be found at https://bootswatch.com/. Defaults to JOURNAL. 

        update_live (bool, optional): Enable hot reloading. If the number of inputs is 0, this is set to True automatically. Defaults to False.

        port (int, optional): Port to which the app should be deployed. Defaults to 8080.

        mode (str, optional): Mode in which to launch the app. Acceptable options are `None`, `jupyterlab`, `inline`, 'external`.\
            Defaults to None.

        minimal (bool, optional): Display minimal version by hiding navbar, title, title image, subheader and footer. Defaults to False.

        disable_logs (bool, optional): Hide app logs. Sets logger level to `ERROR`. Defaults to False.

        scale_height (float, optional): Height of the app container is enlarged as a multiple of this. Defaults to 1.

        run_kwargs (dict, optional): All values from this variable are passed to Dash's `.run` method.
        """

    def decorator_fastdash(callback_fn):
        "Decorator for callback_fn"

        @functools.wraps(callback_fn)
        def wrapper_fastdash(**kwargs):
            app = FastDash(callback_fn=callback_fn, **kwargs)
            app.run()
            return callback_fn

        return wrapper_fastdash(
            mosaic=mosaic,
            inputs=inputs,
            outputs=outputs,
            output_labels=output_labels,
            title=title,
            title_image_path=title_image_path,
            subheader=subheader,
            github_url=github_url,
            linkedin_url=linkedin_url,
            twitter_url=twitter_url,
            navbar=navbar,
            footer=footer,
            loader=loader,
            branding=branding,
            stream=stream,
            about=about,
            theme=theme,
            update_live=update_live,
            mode=mode,
            port=port,
            minimal=minimal,
            disable_logs=disable_logs,
            scale_height=scale_height,
            run_kwargs=run_kwargs,
            **kwargs
        )

    # If the decorator is called with arguments
    if _callback_fn is None:
        return decorator_fastdash
    # If the decorator is called without arguments. Use default input and output values
    else:
        return decorator_fastdash(_callback_fn)
