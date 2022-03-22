import dash
import flask
from dash.dependencies import Input, Output

from .Components import DefaultLayout, Text
from .utils import (
    assign_ids_to_inputs,
    assign_ids_to_outputs,
    make_input_groups,
    make_output_groups,
    theme_mapper,
)


class FastDash(object):
    def __init__(
        self,
        callback_fn=None,
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
        theme="ZEPHYR",
    ):

        self.callback_fn = callback_fn
        self.inputs = inputs
        self.outputs = outputs

        if outputs is None:
            self.outputs = [Text()]

        self.title = 'Prototype' if title is None else title
        self.title_image_path = title_image_path
        self.subtext = subheader
        self.github_url = github_url
        self.linkedin_url = linkedin_url
        self.twitter_url = twitter_url
        self.navbar = navbar
        self.footer = footer

        # Assign IDs to components
        self.inputs_with_ids = assign_ids_to_inputs(self.inputs, self.callback_fn)
        self.outputs_with_ids = assign_ids_to_outputs(self.outputs)
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
        self.app = dash.Dash(
            __name__,
            external_stylesheets=external_stylesheets,
            server=server,
            meta_tags=[
                {
                    "name": "viewport",
                    "content": "width=device-width, initial-scale=1.0, maximum-scale=1.8, minimum-scale=0.5,",
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

    def run(self, port=None):
        self.app.server.run(port=port)

    def set_layout(self):

        if self.inputs is not None:
            input_groups = make_input_groups(self.inputs_with_ids)

        if self.outputs is not None:
            output_groups = make_output_groups(self.outputs_with_ids)

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
                Output(
                    component_id=output_.id,
                    component_property=output_.modify_property,
                )
                for output_ in self.outputs_with_ids
            ]
            + [
                Output(
                    component_id=input_.ack.id,
                    component_property=input_.ack.modify_property,
                )
                for input_ in self.inputs_with_ids
            ],
            [
                Input(
                    component_id=input_.id,
                    component_property=input_.modify_property,
                )
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

            if submit_button > self.submit_clicks:
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
