import functools
import logging
import re
import warnings

import dash
import flask
from dash.dependencies import Input, Output

from .Components import DefaultLayout, Text, _infer_components, SidebarLayout, MosaicLayout
from .utils import (
    _assign_ids_to_inputs,
    _assign_ids_to_outputs,
    _make_input_groups,
    _make_output_groups,
    _transform_outputs,
    theme_mapper,
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
        layout='mosaic',
        mosaic=None,
        inputs=None,
        outputs=None,
        title=None,
        title_image_path=None,
        subheader=None,
        github_url=None,
        linkedin_url=None,
        twitter_url=None,
        navbar=True,
        footer=True,
        theme="JOURNAL",
        update_live=False,
        port=8080,
        mode=None,
        minimal=False,
        disable_logs=False,
        scale_height=1,
        **kwargs
    ):
        """
        Args:
            callback_fn (func): Python function that Fast Dash deploys.
                This function guides the behavior of and interaction between input and output components.

            layout (str, optional): App layout style. Current supports 'default', 'sidebar', and 'mosaic' (default).

            mosaic (str): Mosaic array layout, if mosaic layout is selected.

            inputs (Fast component, list of Fast components, optional): Components to represent inputs of the callback function.
                Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type
                hints and default values. In the absence of type hints, default components are all `Text`.

            outputs (Fast component, list of Fast components, optional): Components to represent outputs of the callback function.
                Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type hints.
                In the absence of type hints, default components are all `Text`.

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
        """

        self.callback_fn = callback_fn
        self.layout_pattern = layout
        self.mosaic = mosaic
        self.inputs = (
            _infer_components(callback_fn, is_input=True) if inputs is None else inputs
        )
        self.outputs = (
            _infer_components(callback_fn, is_input=False)
            if outputs is None
            else outputs
        )
        self.update_live = update_live
        self.mode = mode
        self.disable_logs = disable_logs
        self.scale_height = scale_height
        self.port = port
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
        self.subtext = subheader if subheader is not None else callback_fn.__doc__
        self.github_url = github_url
        self.linkedin_url = linkedin_url
        self.twitter_url = twitter_url
        self.navbar = navbar
        self.footer = footer
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
            theme_mapper(theme),
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
            meta_tags=[
                {
                    "name": "viewport",
                    "content": "width=device-width, initial-scale=1.0, maximum-scale=1.8, minimum-scale=0.5",
                }
            ],
        )
        # Define app title
        self.app.title = self.title

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

    def run(self, **kwargs):
        self.server.run(port=self.port, **kwargs) if self.mode is None else self.app.run_server(
            mode=self.mode, port=self.port, **kwargs
        )

    def run_server(self, **kwargs):
        self.app.run_server(port=self.port, **kwargs) if self.mode is None else self.app.run_server(
            mode=self.mode, port=self.port, **kwargs
        )

    def set_layout(self):

        if self.inputs is not None:
            input_groups = _make_input_groups(self.inputs_with_ids, self.update_live)

        if self.outputs is not None:
            output_groups = _make_output_groups(self.outputs_with_ids, self.update_live)

        layout_args = {
            'mosaic': self.mosaic,
            'inputs': input_groups,
            'outputs': output_groups,
            'title': self.title,
            'title_image_path': self.title_image_path,
            'subtext': self.subtext,
            'github_url': self.github_url,
            'linkedin_url': self.linkedin_url,
            'twitter_url': self.twitter_url,
            'navbar': self.navbar,
            'footer': self.footer,
            'minimal': self.minimal,
            'scale_height': self.scale_height
        }

        if self.layout_pattern == 'mosaic':
            app_layout = MosaicLayout(**layout_args)

        elif self.layout_pattern == 'sidebar':
            app_layout = SidebarLayout(**layout_args)

        else:
            app_layout = DefaultLayout(**layout_args)

        self.layout_object = app_layout
        # app_layout.callbacks()
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
            prevent_initial_callback=True
        )
        def process_input(*args):

            reset_button = args[-2]
            submit_button = args[-1]
            ack_components = [
                ack if mask is True else None
                for mask, ack in zip(self.ack_mask, list(args[:-2]))
            ]

            if submit_button > self.submit_clicks or (
                self.update_live is True and None not in args
            ):
                self.app_initialized = True
                self.submit_clicks = submit_button
                output_state = self.callback_fn(*args[:-2])

                if isinstance(output_state, tuple):
                    self.output_state = list(output_state)

                else:
                    self.output_state = [output_state]

                # Transform outputs to fit in the desired components
                self.output_state = _transform_outputs(self.output_state)

                return self.output_state + ack_components

            elif reset_button > self.reset_clicks:
                self.reset_clicks = reset_button
                self.output_state = self.output_state_default
                return self.output_state + ack_components

            elif self.app_initialized:
                return self.output_state + ack_components

            else:
                return self.output_state_default + ack_components
            
        # Set layout callbacks
        self.layout_object.callbacks(self.app)


def fastdash(
    _callback_fn=None,
    *,
    layout='mosaic',
    mosaic=None,
    inputs=None,
    outputs=None,
    title=None,
    title_image_path=None,
    subheader=None,
    github_url=None,
    linkedin_url=None,
    twitter_url=None,
    navbar=True,
    footer=True,
    theme="JOURNAL",
    update_live=False,
    mode=None,
    port=8080,
    minimal=False,
    disable_logs=False,
    scale_height=1,
    **run_kwargs
):
    """
    Decorator for the `FastDash` class.

    Use the decorated Python callback functions and deployes it using the chosen mode.

    Args:
        callback_fn (func): Python function that Fast Dash deploys.
            This function guides the behavior of and interaction between input and output components.

        inputs (Fast component, list of Fast components, optional): Components to represent inputs of the callback function.
            Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type
            hints and default values. In the absence of type hints, default components are all `Text`.

        outputs (Fast component, list of Fast components, optional): Components to represent outputs of the callback function.
            Defaults to None. If `None`, Fast Dash attempts to infer the best components from callback function's type hints.
            In the absence of type hints, default components are all `Text`.

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

        mode (str, optional): Mode in which to launch the app. Acceptable options are `None`, `jupyterlab`, `inline`, 'external`.
            Defaults to None.

        port (int, optional): Port to which the app should be deployed. Defauts to 8080.

        minimal (bool, optional): Display minimal version by hiding navbar, title, title image, subheader and footer.
            Defaults to False.

        disable_logs (bool, optional): Hide app logs. Sets logger level to `ERROR`. Defaults to False.
    """

    def decorator_fastdash(callback_fn):
        "Decorator for callback_fn"

        @functools.wraps(callback_fn)
        def wrapper_fastdash(**kwargs):
            app = FastDash(callback_fn=callback_fn, **kwargs)
            app.run(**run_kwargs)
            return callback_fn

        return wrapper_fastdash(
            layout=layout,
            mosaic=mosaic,
            inputs=inputs,
            outputs=outputs,
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
            **run_kwargs
        )

    # If the decorator is called with arguments
    if _callback_fn is None:
        return decorator_fastdash
    # If the decorator is called without arguments. Use default input and output values
    else:
        return decorator_fastdash(_callback_fn)
