"""
Utility functions
"""
import inspect
from io import BytesIO
import base64
import copy

import dash_bootstrap_components as dbc
from dash import html


# Add themes mapper
def theme_mapper(theme_name):
    """
    Map theme name string ot a dbc theme object
    """

    theme_mapper_dict = {
        "CERULEAN": dbc.themes.CERULEAN,
        "COSMO": dbc.themes.COSMO,
        "CYBORG": dbc.themes.CYBORG,
        "DARKLY": dbc.themes.DARKLY,
        "FLATLY": dbc.themes.FLATLY,
        "JOURNAL": dbc.themes.JOURNAL,
        "LITERA": dbc.themes.LITERA,
        "LUMEN": dbc.themes.LUMEN,
        "LUX": dbc.themes.LUX,
        "MATERIA": dbc.themes.MATERIA,
        "MINTY": dbc.themes.MINTY,
        "MORPH": dbc.themes.MORPH,
        "PULSE": dbc.themes.PULSE,
        "QUARTZ": dbc.themes.QUARTZ,
        "SANDSTONE": dbc.themes.SANDSTONE,
        "SIMPLEX": dbc.themes.SIMPLEX,
        "SKETCHY": dbc.themes.SKETCHY,
        "SLATE": dbc.themes.SLATE,
        "SOLAR": dbc.themes.SOLAR,
        "SPACELAB": dbc.themes.SPACELAB,
        "SUPERHERO": dbc.themes.SUPERHERO,
        "UNITED": dbc.themes.UNITED,
        "VAPOR": dbc.themes.VAPOR,
        "YETI": dbc.themes.YETI,
        "ZEPHYR": dbc.themes.ZEPHYR,
    }

    theme = theme_mapper_dict.get(theme_name.upper(), dbc.themes.YETI)

    return theme


def pil_to_b64(img):
    """
    Utility to convert PIL image to a base64 string.

    Args:
        img (PIL.Image): Input image

    Returns:
        str: Base64 string of the input image
    """
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    img_str = f"data:image/png;base64,{img_str}"

    return img_str


# Input component utils
def get_input_names_from_callback_fn(callback_fn):
    """
    Returns the names of function arguments as a list of strings
    """
    signature = inspect.signature(callback_fn)
    parameters = signature.parameters
    parameter_list = list(parameters)

    return parameter_list


def assign_ids_to_inputs(inputs, callback_fn):
    """
    Modify the 'id' property of inputs.
    """
    if not isinstance(inputs, list):
        inputs = [inputs]

    inputs_with_ids = []

    for input_, parameter_name in zip(
        inputs, get_input_names_from_callback_fn(callback_fn)
    ):
        input_.id = parameter_name
        inputs_with_ids.append(copy.deepcopy(input_))

    return inputs_with_ids


def make_input_groups(inputs_with_ids):

    input_groups = []

    input_groups.append(html.H2("Input"))

    for idx, input_ in enumerate(inputs_with_ids):
        label = f"{input_.id}" if input_.label_ is None else input_.label_
        label = label.replace("_", " ").upper()
        input_groups.append(
            dbc.Col([dbc.Label(label, align="end"), input_], align="center",)
        )

    button_row = html.Div(
        [
            dbc.Button(
                "Submit",
                color="warning",
                className="me-1",
                id="submit_inputs",
                n_clicks=0,
            )
        ],
        style={"padding": "2% 1% 1% 2%"}
    )

    input_groups.append(button_row)

    return input_groups


# Output utils
def assign_ids_to_outputs(outputs):
    """
    Modify the 'id' property of inputs.
    """
    if not isinstance(outputs, list):
        outputs = [outputs]

    outputs_with_ids = []

    for idx, output_ in enumerate(outputs):
        output_.id = f"output-{idx + 1}"
        outputs_with_ids.append(copy.deepcopy(output_))

    return outputs_with_ids


def make_output_groups(outputs):

    output_groups = []
    output_groups.append(html.H2("Output"))

    for idx, output_ in enumerate(outputs):
        label = f"Output {idx + 1}" if output_.label_ is None else output_.label_
        label = label.replace("_", " ").upper()
        output_groups.append(
            dbc.Col([dbc.Label(label, align="end"), output_], align="center")
        )

    button_row = html.Div(
        [
            dbc.Button(
                "Clear",
                outline=True,
                color="primary",
                className="me-1",
                id="reset_inputs",
                n_clicks=0,
            )
        ]
    )

    output_groups.append(button_row)

    return output_groups
