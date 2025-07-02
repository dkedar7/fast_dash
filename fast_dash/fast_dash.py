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

from .Components import (
    BaseLayout,
    SidebarLayout,
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
        layout="sidebar",
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
        branding=True,
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
        Args:
            callback_fn (func): Python function that Fast Dash deploys. \
                This function guides the behavior of and interaction between input and output components.

            layout (str, optional): App layout style. Currently supports 'base' and 'sidebar'. Defaults to sidebar.

            mosaic (str, optional): Mosaics array layout, if sidebar layout is selected.

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
                
            branding (bool, optional): Display Fast Dash branding component in the footer. Defaults to True. \
            
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
        """

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
        self.layout_pattern = layout
        self.mosaic = mosaic
        self.output_labels = output_labels

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
            "app": self,
        }

        if self.layout_pattern == "sidebar":
            app_layout = SidebarLayout(**layout_args)

        else:
            app_layout = BaseLayout(**layout_args)

        self.layout_object = app_layout
        notification_components = ["notification-container"]

        streaming_components = [c.id for c in self.outputs_with_ids if c.stream == True]
        streaming_components.extend(notification_components)
        
        # Add responses of chat components if present
        chat_components = [c for c in self.outputs_with_ids if c.tag == "Chat" and c.stream == True]

        for component in chat_components:
            [streaming_components.append(f"{component.id}_{i + 1}_response") for i in range(getattr(component, "stream_limit", 10))]
        
        self.app.layout = app_layout.generate_layout(stream_event_names=streaming_components)

    def register_callback_fn(self):

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
                Input(component_id="submit_inputs", component_property="n_clicks"),
                State("socketio", "socketId"),
            ],
            running=[(Output("submit_inputs", "disabled"), True, False)],
            prevent_initial_callback=True,
            prevet_initial_call=True
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

    # Define a stream handler function
    def stream_handler(self, component_id, data, property=None, socket_id=None, notification=True):
        """A simple handler that prints to console and returns a response"""

        if self.stream == False:
            return

        if notification:
            emit(component_id, {"value": data, "append": False}, namespace="/", to=socket_id)
            return f"Notification: {data}"

        component = [c for c in self.outputs_with_ids if c.id == f"output_{component_id}"]

        if not component:
            raise ValueError(f"Component with id {component_id} not found in outputs.")

        component = component[0]
        component_id = component.id

        if component.tag == "Chat" and not property:
            raise ValueError("Argument 'property' must be specified for chat components. Allowed 'property' values are 'query' and 'response'.")

        if component.tag == "Chat" and property  not in ["query", "response"]:
            raise ValueError("Invalid 'property' value for chat component. Allowed 'property' values are 'query' and 'response'.")
    
        component_state_func = _get_transform_function(output=data, 
                                                       tag=component.tag, 
                                                       component_id=component.id, 
                                                       counter=self.state_counter,
                                                       partial_update=True)


        if component.tag == "Chat" and property == "query":

            # Add a new component to the chat response
            data = dict(query=data, response="")
            component_state = json.loads(to_json_plotly(component_state_func(data)))
            # component.stream = True

            emit(component_id, {"value": component_state, "append": True}, namespace="/", to=socket_id)

        elif component.tag == "Chat" and property == "response":
            component_id = f"{component_id}_{self.state_counter}_response"

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

        for component in self.outputs_with_ids:

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
    layout="sidebar",
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
    branding=True,
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

    Args:
        callback_fn (func): Python function that Fast Dash deploys. \
            This function guides the behavior of and interaction between input and output components.

        layout (str, optional): App layout style. Currently supports 'base' and 'sidebar'. Defaults to sidebar.

        mosaic (str): Mosaic array layout, if sidebar layout is selected.

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
                
        branding (bool, optional): Display Fast Dash branding component in the footer. Defaults to True. \
        
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
            layout=layout,
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
