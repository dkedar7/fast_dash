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
from dash import Input, Output, State, ctx, clientside_callback, dcc
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
    from_step,
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

    # Per-process cache for step-pipeline outputs, keyed by browser session id.
    # Each session maps {step_index: result_value} so downstream from_step
    # parameters can resolve. Note: this is process-global; a server restart
    # or multi-worker deploy will lose state. Acceptable for prototyping.
    _step_cache = {}

    def __init__(
        self,
        callback_fn=None,
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
        steps=None,
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

            steps (list of funcs, optional): A linear pipeline of step functions. Each step gets its own \
                page in a stepper UI; outputs of earlier steps can feed downstream steps via ``from_step``. \
                When provided, ``callback_fn`` is ignored. Defaults to None.
        """

        # Detect pipeline (steps) mode
        self.is_steps = steps is not None
        self.steps = steps

        # callback_fn is required unless steps= is provided
        if callback_fn is None and not self.is_steps:
            raise TypeError(
                "FastDash requires either `callback_fn` (a function or list of "
                "functions) or `steps` (a list of step functions). Got neither."
            )

        # Detect multi-function mode (suppressed if steps mode is active)
        self.is_multi = isinstance(callback_fn, list) and not self.is_steps

        if self.is_steps:
            callback_fn = steps[0]  # Use first step for shared chrome
            self.callback_fns = list(steps)
            self.tab_titles = None
        elif self.is_multi:
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

        if self.is_steps:
            self._init_steps()
        elif self.is_multi:
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

    def _init_steps(self):
        """Initialize a linear multi-step pipeline app.

        For each step, separate parameters that take their value from a
        previous step (``from_step``) from parameters the user provides
        through the UI. Build component metadata for each step the same
        way single-function apps do, then hand off to the layout and
        callback registration.
        """
        import inspect as _inspect

        self.step_data = []
        self.fn_to_idx = {}

        for idx, fn in enumerate(self.steps):
            self.fn_to_idx[fn] = idx
            sig = _inspect.signature(fn)
            prefix = f"step{idx}_"

            # Split params into wired-from-cache vs user-facing
            from_step_params = {}
            user_params = []
            for pname, pobj in sig.parameters.items():
                default = (None if pobj.default == _inspect.Parameter.empty
                           else pobj.default)
                if isinstance(default, from_step):
                    from_step_params[pname] = default
                else:
                    user_params.append((pname, pobj))

            # Build a synthetic function whose signature contains only the
            # user-facing parameters, so the existing component-inference
            # pipeline works unchanged.
            if user_params:
                user_fn = self._make_user_params_fn(user_params)
                fn_inputs = _infer_input_components(user_fn)
            else:
                user_fn = lambda: None
                fn_inputs = []

            # Use a deterministic output label per step (avoids the inferred
            # label bug when a step has multiple visible outputs).
            step_title = re.sub("[^0-9a-zA-Z]+", " ", fn.__name__).title()
            fn_output_labels = [step_title + " Output"]
            fn_outputs = _infer_output_components(fn, None, fn_output_labels)

            inputs_with_ids = _assign_ids_to_inputs(fn_inputs, user_fn, prefix=prefix)
            outputs_with_ids = _assign_ids_to_outputs(fn_outputs, fn, prefix=prefix)

            step_desc = _parse_docstring_as_markdown(fn, title=step_title, get_short=True)

            self.step_data.append({
                "fn": fn,
                "idx": idx,
                "prefix": prefix,
                "title": step_title,
                "description": step_desc or "",
                "from_step_params": from_step_params,
                "user_params": user_params,
                "inputs": fn_inputs,
                "outputs": fn_outputs,
                "input_tags": [inp.tag for inp in fn_inputs],
                "output_tags": [out.tag for out in fn_outputs],
                "inputs_with_ids": inputs_with_ids,
                "outputs_with_ids": outputs_with_ids,
            })

        # Set references for backward compat with single-function plumbing
        self.inputs_with_ids = self.step_data[0]["inputs_with_ids"]
        self.outputs_with_ids = self.step_data[0]["outputs_with_ids"]

        self.app.title = self.title or ""
        self._set_steps_layout()
        self._register_steps_callbacks()

    @staticmethod
    def _make_user_params_fn(user_params):
        """Create a synthetic function with only the user-visible parameters.

        ``_infer_input_components`` reads ``inspect.signature(fn)`` to decide
        what UI components to build. For step functions, we want to skip
        parameters wired via ``from_step`` (those don't get UI). This helper
        rebuilds a fresh signature containing only the user-facing params,
        and returns a no-op function carrying it.
        """
        import inspect as _inspect

        params = []
        annotations = {}
        for pname, pobj in user_params:
            params.append(_inspect.Parameter(
                pname,
                kind=_inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=pobj.default,
                annotation=pobj.annotation,
            ))
            if pobj.annotation != _inspect.Parameter.empty:
                annotations[pname] = pobj.annotation

        def _user_fn(**kwargs):
            pass

        _user_fn.__signature__ = _inspect.Signature(params)
        _user_fn.__annotations__ = annotations
        _user_fn.__name__ = "user_params"
        return _user_fn

    def _set_steps_layout(self):
        """Build the multi-step pipeline layout.

        Reuses ``AppLayout`` for the surrounding chrome (header, theme,
        sidebar, dark-mode toggle, footer) by subclassing it and overriding
        the input and output region builders. Only the per-step content is
        steps-specific; everything else is shared with single-function apps.
        """
        from .Components import AppLayout

        # Build the per-step input containers (one Div per step, only the
        # active one is shown). Steps with no user inputs render a small
        # "no inputs needed" hint.
        step_input_containers = []
        for i, sd in enumerate(self.step_data):
            prefix = sd["prefix"]
            if sd["inputs_with_ids"]:
                input_groups = _make_input_groups(
                    sd["inputs_with_ids"], False, prefix=prefix, show_submit=False
                )
            else:
                input_groups = [dmc.Text("No inputs needed for this step.",
                                          c="dimmed", size="sm")]
            step_input_containers.append(
                dash_html.Div(
                    [
                        dmc.Text(sd["title"], fw=600, size="sm",
                                  style={"paddingBottom": "8px"}),
                        dmc.Stack(children=input_groups, gap="lg"),
                    ],
                    id=f"step-inputs-{i}",
                    style={"display": "block" if i == 0 else "none"},
                )
            )

        # Run / Back / Next buttons
        run_btn = dmc.Button(
            "Run", id="step-run-btn", fullWidth=True, size="sm",
            style={"marginTop": "16px"},
        )
        nav_group = dmc.Group(
            [
                dmc.Button("Back", id="step-back-btn", variant="light",
                            size="sm", disabled=True),
                dmc.Button("Next", id="step-next-btn", variant="filled",
                            size="sm", disabled=True),
            ],
            justify="space-between",
            style={"marginTop": "12px"},
        )

        sidebar_payload = dmc.Stack(
            [dash_html.Div(step_input_containers, id="step-inputs-wrapper"),
             run_btn, nav_group],
            gap="md",
        )

        # Build the per-step output containers
        step_output_containers = []
        for i, sd in enumerate(self.step_data):
            prefix = sd["prefix"]
            if sd["outputs_with_ids"]:
                output_content = _make_output_groups(
                    sd["outputs_with_ids"], False, prefix=prefix
                )
            else:
                output_content = []
            step_output_containers.append(
                dash_html.Div(
                    output_content,
                    id=f"step-outputs-{i}",
                    style={"display": "block" if i == 0 else "none"},
                )
            )

        # Stepper progress indicator above the per-step output area
        stepper_steps = [
            dmc.StepperStep(
                label=sd["title"],
                description=(sd["description"] or "")[:50],
            )
            for sd in self.step_data
        ]
        stepper_steps.append(
            dmc.StepperCompleted(
                children=dmc.Text("All steps complete!", c="green", fw=500)
            )
        )
        stepper = dmc.Stepper(
            id="pipeline-stepper",
            active=0,
            children=stepper_steps,
            allowNextStepsSelect=False,
            color="blue",
            size="sm",
            style={"padding": "0 0 16px 0"},
        )

        loading_overlay = dmc.LoadingOverlay(
            id="loading-overlay",
            loaderProps=dict(type=self.loader) if self.loader else {},
        )

        main_payload = dash_html.Div(
            [
                stepper,
                loading_overlay,
                dash_html.Div(step_output_containers, id="step-outputs-wrapper"),
            ]
        )

        # Subclass AppLayout to inject our pre-built sidebar / main content
        # while keeping all the standard chrome.
        class _StepsLayout(AppLayout):
            def generate_input_component(self_inner):
                return dmc.ScrollArea(
                    sidebar_payload,
                    style={"height": "100%"},
                    id="input-group-wrapper",
                )

            def generate_output_component(self_inner):
                return main_payload

        # Instantiate with empty inputs/outputs (we overrode the methods)
        # and a benign mosaic so the parent's __init__ doesn't try to infer one.
        layout_args = {
            "mosaic": "A",
            "inputs": [],
            "outputs": [step_output_containers[0]],  # at least one element
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
        self.layout_object = _StepsLayout(**layout_args)
        # Stores for step state — appended after AppShell so they're not
        # inside the navbar/main scroll regions.
        self.app.layout = self.layout_object.generate_layout(
            stream_event_names=["notification-container"],
        )
        # Add Dash stores to the layout's children
        self.app.layout.children.extend([
            dcc.Store(id="step-session-id", storage_type="session"),
            dcc.Store(id="step-current-idx", data=0),
            dcc.Store(id="step-completed-set", data=[]),
        ])

    def _register_steps_callbacks(self):
        """Register callbacks for the step pipeline: session init, run, next, back, visibility."""
        import uuid as _uuid

        total_steps = len(self.step_data)

        # ---- Session init: assign a UUID per browser session on first load ----
        @self.app.callback(
            Output("step-session-id", "data"),
            Input("step-session-id", "data"),
        )
        def init_session(current_id):
            if current_id:
                return current_id
            sid = str(_uuid.uuid4())
            FastDash._step_cache[sid] = {}
            return sid

        # ---- Layout chrome callbacks (dark mode, sidebar, about) ----
        if not self.minimal:
            self.layout_object.callbacks(self)

        # ---- Run: execute the current step ----
        all_output_targets = []
        for sd in self.step_data:
            for out in sd["outputs_with_ids"]:
                all_output_targets.append(
                    Output(out.id, out.component_property, allow_duplicate=True)
                )

        all_input_sources = []
        for sd in self.step_data:
            for inp in sd["inputs_with_ids"]:
                all_input_sources.append(State(inp.id, inp.component_property))

        @self.app.callback(
            all_output_targets + [
                Output("notification-container", "sendNotifications", allow_duplicate=True),
                Output("loading-overlay", "visible", allow_duplicate=True),
                Output("step-completed-set", "data", allow_duplicate=True),
            ],
            Input("step-run-btn", "n_clicks"),
            [State("step-current-idx", "data"),
             State("step-session-id", "data"),
             State("step-completed-set", "data")] + all_input_sources,
            prevent_initial_call=True,
            running=[(Output("step-run-btn", "disabled"), True, False)],
        )
        def run_step(n_clicks, current_idx, session_id, completed_set, *input_values):
            if not n_clicks or session_id is None:
                raise PreventUpdate

            sd = self.step_data[current_idx]
            fn = sd["fn"]
            kwargs = {}

            cache = FastDash._step_cache.setdefault(session_id, {})

            # 1) Inject from_step values from cache
            for pname, fs in sd["from_step_params"].items():
                source_idx = self.fn_to_idx.get(fs.source_fn)
                if source_idx is None or source_idx not in cache:
                    notification = _get_error_notification_component(
                        f"Step '{sd['title']}' depends on a previous step that hasn't been run yet."
                    )
                    return ([dash.no_update] * len(all_output_targets)
                            + [notification, False, completed_set])
                cached_val = cache[source_idx]
                kwargs[pname] = fs.transform(cached_val) if fs.transform else cached_val

            # 2) Slice the relevant input values out of the flat tuple
            input_offset = sum(
                len(s["inputs_with_ids"])
                for s in self.step_data[:current_idx]
            )
            user_input_vals = list(input_values[
                input_offset:input_offset + len(sd["inputs_with_ids"])
            ])
            user_input_vals = _transform_inputs(user_input_vals, sd["input_tags"])
            for (pname, _pobj), val in zip(sd["user_params"], user_input_vals):
                kwargs[pname] = val

            # 3) Execute and cache the result
            try:
                result = fn(**kwargs)
            except Exception as e:
                traceback.print_exc()
                notification = _get_error_notification_component(str(e))
                return ([dash.no_update] * len(all_output_targets)
                        + [notification, False, completed_set])
            cache[current_idx] = result

            # 4) Transform outputs for display
            output_vals = list(result) if isinstance(result, tuple) else [result]
            output_vals = _transform_outputs(
                output_vals, sd["output_tags"], sd["outputs_with_ids"], 0
            )

            # 5) Build the full output array (no_update for non-active steps)
            all_outputs = []
            for other_sd in self.step_data:
                if other_sd["idx"] == current_idx:
                    all_outputs.extend(output_vals)
                else:
                    all_outputs.extend([dash.no_update] * len(other_sd["outputs_with_ids"]))

            if current_idx not in completed_set:
                completed_set = list(completed_set) + [current_idx]
            return all_outputs + [[], False, completed_set]

        # ---- Next: advance to the next step ----
        @self.app.callback(
            Output("step-current-idx", "data", allow_duplicate=True),
            Output("pipeline-stepper", "active", allow_duplicate=True),
            Input("step-next-btn", "n_clicks"),
            State("step-current-idx", "data"),
            prevent_initial_call=True,
        )
        def step_next(n, current_idx):
            if not n:
                raise PreventUpdate
            if current_idx + 1 < total_steps:
                return current_idx + 1, current_idx + 1
            return total_steps, total_steps  # Completed

        # ---- Back: rewind one step, clearing downstream cached results ----
        @self.app.callback(
            Output("step-current-idx", "data", allow_duplicate=True),
            Output("pipeline-stepper", "active", allow_duplicate=True),
            Output("step-completed-set", "data", allow_duplicate=True),
            Input("step-back-btn", "n_clicks"),
            State("step-current-idx", "data"),
            State("step-completed-set", "data"),
            State("step-session-id", "data"),
            prevent_initial_call=True,
        )
        def step_back(n, current_idx, completed_set, session_id):
            if not n or current_idx <= 0:
                raise PreventUpdate
            cache = FastDash._step_cache.get(session_id, {})
            for k in [k for k in cache if k >= current_idx]:
                del cache[k]
            completed_set = [c for c in completed_set if c < current_idx]
            return current_idx - 1, current_idx - 1, completed_set

        # ---- Visibility: show the active step's inputs + outputs; toggle nav button states ----
        visibility_outputs = []
        for i in range(total_steps):
            visibility_outputs.append(Output(f"step-inputs-{i}", "style"))
            visibility_outputs.append(Output(f"step-outputs-{i}", "style"))
        visibility_outputs.extend([
            Output("step-back-btn", "disabled"),
            Output("step-next-btn", "disabled"),
        ])

        @self.app.callback(
            visibility_outputs,
            Input("step-current-idx", "data"),
            Input("step-completed-set", "data"),
        )
        def update_step_visibility(current_idx, completed_set):
            styles = []
            for i in range(total_steps):
                show = "block" if i == current_idx else "none"
                styles.append({"display": show})  # inputs
                styles.append({"display": show})  # outputs
            back_disabled = current_idx == 0
            next_disabled = current_idx not in (completed_set or [])
            return styles + [back_disabled, next_disabled]

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
        """Build a tabbed layout for multi-function mode using AppLayout.

        Reuses ``AppLayout`` for the surrounding chrome (header, theme,
        sidebar shell, dark-mode toggle, About modal, footer). Each tab
        gets its own input panel (rendered in the navbar) and its own
        output panel (rendered in the main pane). A ``dmc.Tabs`` strip
        sits at the top of the main pane and drives a callback that
        toggles the visibility of the per-tab panels.
        """
        from .Components import AppLayout

        all_streaming_components = ["notification-container"]
        tab_titles_resolved = []

        # Build per-tab input panels (one Div per tab; only the active
        # one is shown).
        per_tab_input_panels = []
        for idx, fd in enumerate(self.func_data):
            prefix = fd["prefix"]
            input_groups = _make_input_groups(
                fd["inputs_with_ids"], fd["update_live"], prefix=prefix
            )

            if self.tab_titles and idx < len(self.tab_titles):
                tab_title = self.tab_titles[idx]
            else:
                tab_title = re.sub("[^0-9a-zA-Z]+", " ", fd["fn"].__name__).title()
            tab_titles_resolved.append(tab_title)

            per_tab_input_panels.append(
                dash_html.Div(
                    [dmc.Stack(children=input_groups, gap="lg")],
                    id=f"{prefix}input-panel",
                    style={"display": "block" if idx == 0 else "none"},
                )
            )

        sidebar_payload = dmc.ScrollArea(
            dmc.Stack(per_tab_input_panels, gap="md", id="multi-input-wrapper"),
            style={"height": "100%"},
            id="input-group-wrapper",
        )

        # Build per-tab output panels (one Div per tab; only the active
        # one is shown). Each panel includes its own loading overlay so
        # the per-function callbacks can target it by prefix.
        per_tab_output_panels = []
        for idx, fd in enumerate(self.func_data):
            prefix = fd["prefix"]
            output_groups = _make_output_groups(
                fd["outputs_with_ids"], fd["update_live"], prefix=prefix
            )

            fn_subtitle = _parse_docstring_as_markdown(
                fd["fn"], title=tab_titles_resolved[idx], get_short=True
            )

            panel_children = []
            if fn_subtitle:
                panel_children.append(
                    dmc.Text(fn_subtitle, size="sm", c="dimmed",
                              style={"paddingBottom": "12px"})
                )
            panel_children.append(
                dmc.LoadingOverlay(
                    id=f"{prefix}loading-overlay",
                    loaderProps=dict(type=self.loader) if self.loader else {},
                )
            )
            panel_children.append(dash_html.Div(output_groups))

            per_tab_output_panels.append(
                dash_html.Div(
                    panel_children,
                    id=f"{prefix}output-panel",
                    style={"display": "block" if idx == 0 else "none"},
                )
            )

            for c in fd["outputs_with_ids"]:
                if getattr(c, "stream", False):
                    all_streaming_components.append(c.id)
                    if c.tag == "Chat":
                        for i in range(getattr(c, "stream_limit", 10)):
                            all_streaming_components.append(f"{c.id}_{i + 1}_response")

        # Tabs strip across the top of the main pane.
        tabs_strip = dmc.Tabs(
            [
                dmc.TabsList(
                    [
                        dmc.TabsTab(t, value=f"tab-{i}")
                        for i, t in enumerate(tab_titles_resolved)
                    ]
                )
            ],
            value="tab-0",
            id="multi-function-tabs",
            style={"marginBottom": "16px"},
        )

        main_payload = dash_html.Div(
            [
                tabs_strip,
                dash_html.Div(per_tab_output_panels, id="multi-output-wrapper"),
            ]
        )

        # Subclass AppLayout to inject our pre-built sidebar / main content.
        class _MultiLayout(AppLayout):
            def generate_input_component(self_inner):
                return sidebar_payload

            def generate_output_component(self_inner):
                return main_payload

        layout_args = {
            "mosaic": "A",
            "inputs": [],
            "outputs": [per_tab_output_panels[0]],
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
        self.layout_object = _MultiLayout(**layout_args)
        self.app.layout = self.layout_object.generate_layout(
            stream_event_names=all_streaming_components,
        )

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

        # Wire depends_on callbacks
        self._register_depends_on_callbacks()

    def _register_depends_on_callbacks(self, prefix=""):
        """Register callbacks for inputs that use depends_on."""
        # Build a parameter-name → component lookup. Component ids are
        # "input_<param_name>" (optionally prefixed), so strip both the
        # shared prefix and the "input_" marker.
        name_to_component = {}
        for inp in self.inputs_with_ids:
            key = inp.id
            if prefix and key.startswith(prefix):
                key = key[len(prefix):]
            if key.startswith("input_"):
                key = key[len("input_"):]
            name_to_component[key] = inp

        for inp in self.inputs_with_ids:
            if not hasattr(inp, "_depends_on_parent"):
                continue

            parent_name = inp._depends_on_parent
            resolver = inp._depends_on_resolver
            parent_component = name_to_component.get(parent_name)

            if parent_component is None:
                warnings.warn(
                    f"depends_on: parent '{parent_name}' not found in function parameters. "
                    f"Available: {list(name_to_component.keys())}"
                )
                continue

            self._register_single_dependency(
                parent_component.id,
                parent_component.component_property,
                inp.id,
                resolver,
            )

    @staticmethod
    def _apply_dependency_resolver(resolver, parent_value):
        """Apply a depends_on resolver and map the result to (data, value).

        Pure helper, extracted so tests can exercise the resolver contract
        without needing a Dash request context. Returns ``(data, value)``
        where each slot is either a concrete update or ``dash.no_update``.
        """
        import dash as _dash

        if parent_value is None:
            return _dash.no_update, _dash.no_update

        try:
            result = resolver(parent_value)
        except Exception:
            return _dash.no_update, _dash.no_update

        if isinstance(result, list):
            return result, None

        if isinstance(result, dict):
            data = result.get("data", _dash.no_update)
            value = result.get("value", _dash.no_update)
            return data, value

        return _dash.no_update, result

    def _register_single_dependency(self, parent_id, parent_prop, dependent_id, resolver):
        """Register a single dependency callback between two inputs."""
        @self.app.callback(
            Output(dependent_id, "data"),
            Output(dependent_id, "value"),
            Input(parent_id, parent_prop),
            prevent_initial_call=False,
        )
        def update_dependent(parent_value):
            return self._apply_dependency_resolver(resolver, parent_value)

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

        # Tab switcher: toggle visibility of per-tab input/output panels.
        n_tabs = len(self.func_data)
        prefixes = [fd["prefix"] for fd in self.func_data]

        @self.app.callback(
            [Output(f"{p}input-panel", "style") for p in prefixes]
            + [Output(f"{p}output-panel", "style") for p in prefixes],
            Input("multi-function-tabs", "value"),
        )
        def _switch_tabs(active):
            try:
                active_idx = int(str(active).replace("tab-", ""))
            except (TypeError, ValueError):
                active_idx = 0
            input_styles = [
                {"display": "block" if i == active_idx else "none"}
                for i in range(n_tabs)
            ]
            output_styles = list(input_styles)
            return input_styles + output_styles

        # Layout chrome callbacks (sidebar burger, dark mode). The About
        # modal callback inside AppLayout.callbacks() is unsafe in multi
        # mode because it expects a single callback_fn, so we register
        # only the chrome bits and supply our own About callback below.
        if not self.minimal:
            self._register_multi_chrome_callbacks()

        # About modal callback (combined docstrings across all functions).
        if self.about and not self.minimal:
            @self.app.callback(
                Output("about-modal", "opened"),
                Output("about-modal", "children"),
                Input("about-navlink", "n_clicks"),
                State("about-modal", "opened"),
                prevent_initial_call=True,
            )
            def toggle_about(n_clicks, opened):
                if n_clicks:
                    from dash import dcc
                    sections = []
                    for fd_ in self.func_data:
                        fn = fd_["fn"]
                        fn_title = re.sub("[^0-9a-zA-Z]+", " ", fn.__name__).title()
                        about_text = _parse_docstring_as_markdown(fn, title=fn_title)
                        sections.append(dcc.Markdown(about_text))
                        sections.append(dash_html.Hr())
                    return not opened, dash_html.Div(sections[:-1])
                raise PreventUpdate

    def _register_multi_chrome_callbacks(self):
        """Wire dark-mode toggle + sidebar burger for multi-function mode.

        Mirrors the relevant bits of ``AppLayout.callbacks`` but skips the
        single-function About modal handler (we register our own).
        """
        self.app.clientside_callback(
            """
            function(checked) {
                return checked ? "dark" : "light";
            }
            """,
            Output("mantine-provider", "forceColorScheme"),
            Input("theme-toggle", "checked"),
        )

        @self.app.callback(
            Output("appshell", "navbar"),
            Input("sidebar-button", "opened"),
        )
        def _toggle_sidebar(opened):
            collapsed = {"mobile": not opened, "desktop": not opened}
            return {
                "width": 300,
                "breakpoint": "sm",
                "collapsed": collapsed,
            }

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
