import dash
from dash.dependencies import Input, Output
import flask
import functools
import inspect
import re
import warnings

from .Components import DefaultLayout, Text, _infer_components
from .utils import (
    _assign_ids_to_inputs,
    _assign_ids_to_outputs,
    _make_input_groups,
    _make_output_groups,
    theme_mapper,
)


class FastDash:
    def __init__(
        self,
        callback_fn,
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
        minimal=False,
    ):

        self.callback_fn = callback_fn
        self.inputs = _infer_components(callback_fn, is_input=True) if inputs is None else inputs
        self.outputs = _infer_components(callback_fn, is_input=False) if outputs is None else outputs
        self.update_live = update_live
        self.mode = mode

        if title is None:
            title = re.sub('[^0-9a-zA-Z]+', ' ', callback_fn.__name__).title()

        self.title = title
        self.title_image_path = title_image_path
        self.subtext = subheader if subheader is not None else callback_fn.__doc__
        self.github_url = github_url
        self.linkedin_url = linkedin_url
        self.twitter_url = twitter_url
        self.navbar = navbar
        self.footer = footer

        # If minimal layout is requested, disable all additional layout options
        if minimal is True:
            self.title = ''
            self.title_image_path = None
            self.subtext = ''
            self.navbar = False
            self.footer = False

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
                warning.warn('Ignoring mode argument')

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


    def run(self, **args):
        self.server.run(**args) if self.mode is None else self.app.run_server(mode=self.mode, **args)

    def run_server(self, **args):
        self.app.run_server(**args) if self.mode is None else self.app.run_server(mode=self.mode, **args)

    def set_layout(self):

        if self.inputs is not None:
            input_groups = _make_input_groups(self.inputs_with_ids, self.update_live)

        if self.outputs is not None:
            output_groups = _make_output_groups(self.outputs_with_ids, self.update_live)

        default_layout = DefaultLayout(
            inputs=input_groups,
            outputs=output_groups,
            title=self.title,
            title_image_path=self.title_image_path,
            subtext=self.subtext,
            github_url=self.github_url,
            linkedin_url=self.linkedin_url,
            twitter_url=self.twitter_url,
            navbar=self.navbar,
            footer=self.footer,
        )

        self.app.layout = default_layout.layout

    def register_callback_fn(self):
        @self.app.callback(
            [
                Output(component_id=output_.id, component_property=output_.assign_prop)
                for output_ in self.outputs_with_ids
            ]
            + [
                Output(
                    component_id=input_.ack.id,
                    component_property=input_.ack.assign_prop,
                )
                for input_ in self.inputs_with_ids
            ],
            [
                Input(component_id=input_.id, component_property=input_.assign_prop)
                for input_ in self.inputs_with_ids
            ]
            + [
                Input(component_id="reset_inputs", component_property="n_clicks"),
                Input(component_id="submit_inputs", component_property="n_clicks"),
            ],
        )
        def process_input(*args):

            reset_button = args[-2]
            submit_button = args[-1]
            ack_components = [
                ack if mask is True else None
                for mask, ack in zip(self.ack_mask, list(args[:-2]))
            ]

            if submit_button > self.submit_clicks or (
                self.update_live == True and None not in args
            ):
                self.app_initialized = True
                self.submit_clicks = submit_button
                output_state = self.callback_fn(*args[:-2])

                if isinstance(output_state, tuple):
                    self.output_state = list(output_state)
                    return self.output_state + ack_components

                self.output_state = [output_state]
                return self.output_state + ack_components

            elif reset_button > self.reset_clicks:
                self.reset_clicks = reset_button
                self.output_state = self.output_state_default
                return self.output_state + ack_components

            elif self.app_initialized:
                return self.output_state + ack_components

            else:
                return self.output_state_default + ack_components


def fastdash(_callback_fn=None, 
             *, 
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
            minimal=False):
    """
    Decorator for the Fast Dash class. Can decorate any Python function.
    
    Args:
        Replica of arguments to FastDash. Refer to docs of the class FastDash.
        If the decorator is given no arguments, inputs and outputs are autoinferred from type hints.
        In absence of type hints, inputs and outputs are each to be `Text` 
    """

    def decorator_fastdash(callback_fn):
        "Decorator for callback_fn"

        @functools.wraps(callback_fn)
        def wrapper_fastdash(**args):
            app = FastDash(callback_fn=callback_fn, **args)
            app.run()
            return callback_fn

        return wrapper_fastdash(inputs=inputs,
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
                            minimal=minimal)

    # If the decorator is called with arguments
    if _callback_fn is None:
        return decorator_fastdash
    # If the decorator is called without arguments. Use default input and output values
    else:
        return decorator_fastdash(_callback_fn)
