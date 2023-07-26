import functools
import logging
import re
import warnings

import dash
import dash_bootstrap_components as dbc
import flask
from dash import Input, Output, ctx
from dash.exceptions import PreventUpdate

from .Components import (
    BaseLayout,
    SidebarLayout,
    Text,
    _infer_input_components,
    _infer_output_components,
)
from .utils import (
    _assign_ids_to_inputs,
    _assign_ids_to_outputs,
    _make_input_groups,
    _make_output_groups,
    _transform_outputs,
    theme_mapper,
    _infer_variable_names,
)


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
            callback_fn (func): Python function that Fast Dash deploys.
                This function guides the behavior of and interaction between input and output components.

            layout (str, optional): App layout style. Currently supports 'base' and 'sidebar' (default).

            mosaic (str): Mosaic array layout, if sidebar layout is selected.

            inputs (Fast component, list of Fast components, optional): Components to represent inputs of the callback function.
                Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type
                hints and default values. In the absence of type hints, default components are all `Text`.

            outputs (Fast component, list of Fast components, optional): Components to represent outputs of the callback function.
                Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type hints.
                In the absence of type hints, default components are all `Text`.

            output_labels(list of string labels or "infer" or None, optional): Labels given to the output components. If None, inputs are
                set labeled integers starting at 1 (Output 1, Output 2, and so on). If "infer", labels are inferred from the function
                signature.

            title (str, optional): Title given to the app. Defaults to None. If `None`, function name (assumed to be in snake case)
                is converted to title case.

            title_image_path (str, optional): Path (local or URL) of the app title image. Defaults to None.

            subheader (str, optional): Subheader of the app, displayed below the title image and title. Defaults to None.
                If `None`, Fast Dash tries to use the callback function's docstring instead.

            github_url (str, optional): GitHub URL for branding. Displays a GitHub logo in the navbar, which takes users to the
                specified URL. Defaults to None.

            linkedin_url (str, optional): LinkedIn URL for branding Displays a LinkedIn logo in the navbar, which takes users to the
                specified URL. Defaults to None.

            twitter_url (str, optional): Twitter URL for branding. Displays a Twitter logo in the navbar, which takes users to the
                specified URL. Defaults to None.

            navbar (bool, optional): Display navbar. Defaults to True.

            footer (bool, optional): Display footer. Defaults to True.

            theme (str, optional): Apply theme to the app. Defaults to "JOURNAL". All available themes can be found
                at https://bootswatch.com/.

            update_live (bool, optional): Enable hot reloading. Defaults to False.

            port (int, optional): Port to which the app should be deployed. Defauts to 8080.

            mode (str, optional): Mode in which to launch the app. Acceptable options are `None`, `jupyterlab`, `inline`, 'external`.
                Defaults to None.

            minimal (bool, optional): Display minimal version by hiding navbar, title, title image, subheader and footer.
                Defaults to False.

            disable_logs (bool, optional): Hide app logs. Sets logger level to `ERROR`. Defaults to False.

            scale_height (float, optional): Height of the app container is enlarged as a multiple of this. Defaults to 1.

            run_kwargs (dict, optional): All values from this variable are passed to Dash's `.run` method.
        """

        self.callback_fn = callback_fn
        self.layout_pattern = layout
        self.mosaic = mosaic
        self.output_labels = output_labels

        if output_labels:
            self.output_labels = _infer_variable_names(callback_fn)

        self.inputs = _infer_input_components(callback_fn) if inputs is None else inputs
        self.outputs = (
            _infer_output_components(callback_fn, self.output_labels)
            if outputs is None
            else outputs
        )
        self.update_live = update_live
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
        self.subtitle = subheader if subheader is not None else callback_fn.__doc__
        self.github_url = github_url
        self.linkedin_url = linkedin_url
        self.twitter_url = twitter_url
        self.navbar = navbar
        self.footer = footer
        self.theme = theme or "JOURNAL"
        self.minimal = minimal

        # Assign IDs to components
        self.inputs_with_ids = _assign_ids_to_inputs(self.inputs, self.callback_fn)
        self.outputs_with_ids = _assign_ids_to_outputs(self.outputs)
        self.ack_mask = [
            True if input_.ack is not None else False for input_ in self.inputs_with_ids
        ]

        # Default state of outputs
        self.output_state_default = [
            output_.placeholder for output_ in self.outputs_with_ids
        ]

        # Define Flask server
        server = flask.Flask(__name__)
        external_stylesheets = [
            theme_mapper(self.theme),
            "https://use.fontawesome.com/releases/v5.9.0/css/all.css",
        ]

        source = dash.Dash
        if self.mode is not None:
            try:
                from jupyter_dash import JupyterDash

                source = JupyterDash

            except ImportError as e:
                self.mode = None
                warnings.warn(str(e))
                warnings.warn("Ignoring mode argument")

        self.app = source(
            __name__,
            external_stylesheets=external_stylesheets,
            server=server,
            **self.kwargs
        )
        # Define app title
        self.app.title = self.title or ""

        # Intialize layout
        self.set_layout()

        # Register callbacks
        self.register_callback_fn()

        # Keep track of the number of clicks
        self.submit_clicks = 0
        self.reset_clicks = 0
        self.app_initialized = False

        # Allow easier access to Dash server
        self.server = self.app.server

    def run(self):
        self.server.run(
            **self.run_kwargs
        ) if self.mode is None else self.app.run_server(
            mode=self.mode, **self.run_kwargs
        )

    def run_server(self):
        self.app.run_server(
            **self.run_kwargs
        ) if self.mode is None else self.app.run_server(
            mode=self.mode, **self.run_kwargs
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
            "minimal": self.minimal,
            "scale_height": self.scale_height,
        }

        if self.layout_pattern == "sidebar":
            app_layout = SidebarLayout(**layout_args)

        else:
            app_layout = BaseLayout(**layout_args)

        self.layout_object = app_layout
        self.app.layout = app_layout.generate_layout()

    def register_callback_fn(self):
        @self.app.callback(
            [
                Output(
                    component_id=output_.id,
                    component_property=output_.component_property,
                )
                for output_ in self.outputs_with_ids
            ]
            + [
                Output(
                    component_id=input_.ack.id,
                    component_property=input_.ack.component_property,
                )
                for input_ in self.inputs_with_ids
            ],
            [
                Input(
                    component_id=input_.id, component_property=input_.component_property
                )
                for input_ in self.inputs_with_ids
            ]
            + [
                Input(component_id="reset_inputs", component_property="n_clicks"),
                Input(component_id="submit_inputs", component_property="n_clicks"),
            ],
            prevent_initial_callback=True,
        )
        def process_input(*args):
            # if ctx.triggered_id not in ["submit_inputs", "reset_inputs"]:
            #     raise PreventUpdate

            ack_components = [
                ack if mask is True else None
                for mask, ack in zip(self.ack_mask, list(args[:-2]))
            ]

            if ctx.triggered_id == "submit_inputs" or (
                self.update_live is True and None not in args
            ):
                self.app_initialized = True
                output_state = self.callback_fn(*args[:-2])

                if isinstance(output_state, tuple):
                    self.output_state = list(output_state)

                else:
                    self.output_state = [output_state]

                # Transform outputs to fit in the desired components
                self.output_state = _transform_outputs(self.output_state)

                return self.output_state + ack_components

            elif ctx.triggered_id == "reset_inputs":
                self.output_state = self.output_state_default
                return self.output_state + ack_components

            elif self.app_initialized:
                return self.output_state + ack_components

            else:
                return self.output_state_default + ack_components

        # Set layout callbacks
        if not self.minimal:
            self.layout_object.callbacks(self.app)


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
        callback_fn (func): Python function that Fast Dash deploys.
            This function guides the behavior of and interaction between input and output components.

        layout (str, optional): App layout style. Currently supports 'base' and 'sidebar' (default).

        mosaic (str): Mosaic array layout, if sidebar layout is selected.

        inputs (Fast component, list of Fast components, optional): Components to represent inputs of the callback function.
            Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type
            hints and default values. In the absence of type hints, default components are all `Text`.

        outputs (Fast component, list of Fast components, optional): Components to represent outputs of the callback function.
            Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type hints.
            In the absence of type hints, default components are all `Text`.

        output_labels(list of string labels or "infer" or None, optional): Labels given to the output components. If None, inputs are
            set labeled integers starting at 1 (Output 1, Output 2, and so on). If "infer", labels are inferred from the function
            signature.

        title (str, optional): Title given to the app. Defaults to None. If `None`, function name (assumed to be in snake case)
            is converted to title case.

        title_image_path (str, optional): Path (local or URL) of the app title image. Defaults to None.

        subheader (str, optional): Subheader of the app, displayed below the title image and title. Defaults to None.
            If `None`, Fast Dash tries to use the callback function's docstring instead.

        github_url (str, optional): GitHub URL for branding. Displays a GitHub logo in the navbar, which takes users to the
            specified URL. Defaults to None.

        linkedin_url (str, optional): LinkedIn URL for branding Displays a LinkedIn logo in the navbar, which takes users to the
            specified URL. Defaults to None.

        twitter_url (str, optional): Twitter URL for branding. Displays a Twitter logo in the navbar, which takes users to the
            specified URL. Defaults to None.

        navbar (bool, optional): Display navbar. Defaults to True.

        footer (bool, optional): Display footer. Defaults to True.

        theme (str, optional): Apply theme to the app. Defaults to "JOURNAL". All available themes can be found
            at https://bootswatch.com/.

        update_live (bool, optional): Enable hot reloading. Defaults to False.

        port (int, optional): Port to which the app should be deployed. Defauts to 8080.

        mode (str, optional): Mode in which to launch the app. Acceptable options are `None`, `jupyterlab`, `inline`, 'external`.
            Defaults to None.

        minimal (bool, optional): Display minimal version by hiding navbar, title, title image, subheader and footer.
            Defaults to False.

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
