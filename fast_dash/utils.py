"""
Utility functions
"""
import base64
import copy
import functools
import inspect
from io import BytesIO

import dash
from dash import html, dcc, Patch
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash_iconify import DashIconify

import docstring_parser
import logging
import matplotlib as mpl
import matplotlib.pyplot as plt
import PIL
import plotly.graph_objects as go
import pandas as pd
import warnings
import re


def Fastify(component, component_property, ack=None, placeholder=None, label_=None, tag=None, stream=False, *args, **kwargs):
    """
    Modify a Dash component into a FastComponent.

    Args:
        component (Dash component): Dash component that needs to be modified
        component_property (str): Component property that's assigned the input or output values
        ack (Dash component, optional): Dash component that's displayed as an acknowledgement of the original component
        placeholder (str, optional): Placeholder value of the component.
        label_ (str, optional): Component title.
        tag (str, optional): Optional tag applied to the component.

    Returns:
        Fast component: Dash component modified to make it compatible with Fast Dash.
    """
    
    class FastComponent(type(component)):
        def __init__(self, component, component_property, ack=ack, placeholder=placeholder, label_=label_, tag=tag, stream=stream, *args, **kwargs):
            
            self.component = component
            self.component_property = component_property
            self.ack = ack
            self.label_ = label_
            self.placeholder = placeholder
            self.tag = tag
            self.stream = stream
            
            # Copy normal attributes
            for attr_name, attr_value in vars(component).items():
                setattr(self, attr_name, attr_value)

            # Copy the __doc__ attribute
            self.__doc__ = component.__doc__
            
            for key, value in kwargs.items():
                setattr(self, key, value)
                
        def __call__(self, **kwargs):            
            self_copy = copy.deepcopy(self)
            for key, value in kwargs.items():
                setattr(self_copy, key, value)
                
            return self_copy
        
    return FastComponent(component, component_property, ack=ack, placeholder=placeholder, label_=label_, tag=tag, stream=stream)


def Chatify(query_response_dict, component_id, counter, partial_update=False, stream=False):
    "Convert a dictionary into a Chat component"

    if not isinstance(query_response_dict, dict):
        raise TypeError("Chat component requires a dictionary output ('query': ..., 'response': ..., 'artifacts': ...).")
    
    artifacts = query_response_dict.get("artifacts", [])

    if artifacts and not isinstance(artifacts, list):
        raise TypeError("Artifacts should be a list of artifacts.")

    artifact_components = []
    for artifact in artifacts:
        if isinstance(artifact, go.Figure):
            component = dcc.Graph(figure=artifact, style=dict(height="100%", width="100%"))

        elif isinstance(artifact, pd.DataFrame):
            component = dash.dash_table.DataTable(
                            data=artifact.to_dict(orient="records"),
                            page_size=100,
                            page_action="native",
                            sort_action="native",
                            style_header={
                                "backgroundColor": "white",
                                "fontWeight": "bold",
                                "color": "black",
                                "textAlign": "center",
                                "border": "1px solid #f0f0f0",
                                "fontFamily": '"News Cycle","Arial Narrow Bold",sans-serif',
                            },
                            style_cell={
                                "backgroundColor": "white",
                                "color": "black",
                                "textAlign": "center",
                                "border": "1px solid #f0f0f0",
                                "fontFamily": '"News Cycle","Arial Narrow Bold",sans-serif',
                            },
                            style_table={
                                "border": "1px solid #f0f0f0",
                                "overflowY": "auto",
                                "fontFamily": '"News Cycle","Arial Narrow Bold",sans-serif',
                            },
                        )
            
        elif isinstance(artifact, PIL.Image.Image):
            component = html.Img(
                src=_pil_to_b64(artifact),
                style={
                    "object-fit": "contain",
                    "max-height": "90%",
                    "max-width": "100%",
                    "height": "auto",
                }
            )

        elif isinstance(artifact, mpl.figure.Figure):
            component = html.Img(
                src=_mpl_to_b64(artifact),
                style={
                    "object-fit": "contain",
                    "max-height": "90%",
                    "max-width": "100%",
                    "height": "auto",
                }
            )

        else:
            component = dmc.Text(
                artifact,
                style={
                    "padding": "1% 1%",
                    "max-width": "80%",
                    "backgroundColor": "#E8EBFA",
                },
                ta="left",
                className="border rounded shadow-sm m-3 col-auto",
            )

        artifact_components.append(component)

    ## Chat component
    input_component = dbc.Row(
        dmc.Text(
            [query_response_dict["query"]],
            id=f"{component_id}_{counter}_query",
            ta="right",
            style={
                "padding": "1% 1%",
                "max-width": "80%",
                "backgroundColor": "#E8EBFA",
            },
            className="border rounded shadow-sm m-3 col-auto",
        ),
        align="center",
        justify="end",
    )

    output_component = dbc.Row(
        [
            dmc.Text(
                [
                    dbc.Col(
                        DashIconify(
                            icon="ic:baseline-question-answer",
                            color="#910517",
                            width=30,
                        ),
                        class_name="pb-2",
                    ),
                    dcc.Markdown(query_response_dict["response"], id=f"{component_id}_{counter}_response"),
                ] + artifact_components,
                style={
                    "padding": "1% 1%",
                    "max-width": "98%",
                    "backgroundColor": "#F9F9F9",
                    "gap": "10px",  # Add gap between consecutive elements
                },
                ta="left",
                className="border rounded shadow-sm m-3",
            )
        ],
        align="start",
        justify="start",
    )


    chat_output_div = html.Div([input_component, output_component])

    # Variable 'partial_update' is an indication of which method requires the component
    # If component is used in the batch output of callback_fn, then partial_update is False
    # Whereas, if component is used in 'update', then partial_update is True

    if not partial_update and not stream:
        chat_output = Patch()
        chat_output.prepend(chat_output_div)
        return chat_output

    if partial_update:
        return chat_output_div
    
    if not partial_update and stream:
        chat_output = Patch()
        chat_output[0]['props']['children'] = [input_component, output_component]
        return chat_output   


# Add themes mapper
def theme_mapper(theme_name):
    """
    Map theme name string to a dbc theme object
    """

    theme_mapper_dict = {
        "BOOTSTRAP": dbc.themes.BOOTSTRAP,
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


# Data type conversion utilities
def _pil_to_b64(img):
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


def _b64_to_pil(img_str):
    """
    Utility to convert a base64 image  string to PIL image.

    Args:
        img_str (str): Input image base64 string

    Returns:
        PIL.Image: Pillow image formatted image
    """

    img_str = img_str.split(";base64,")[1]
    return PIL.Image.open(BytesIO(base64.b64decode(img_str)))


def _mpl_to_b64(fig):
    """
    Utility to convert Matplotlib figure to a base64 string.

    Args:
        fig (matplotlib.figure.Figure): Input matplotlib plot

    Returns:
        str: Base64 string of the input image
    """
    buffered = BytesIO()
    fig.savefig(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    img_str = f"data:image/png;base64,{img_str}"

    return img_str


# Input component utils
def _get_input_names_from_callback_fn(callback_fn):
    """
    Returns the names of function arguments as a list of strings
    """
    signature = inspect.signature(callback_fn)
    parameters = signature.parameters
    parameter_list = list(parameters)

    return parameter_list


# Fast Dash app utilities
def _assign_ids_to_inputs(inputs, callback_fn, prefix=""):
    """
    Modify the 'id' property of inputs.
    """
    if not isinstance(inputs, list):
        inputs = [inputs]

    inputs_with_ids = []

    for input_, parameter_name in zip(
        inputs, _get_input_names_from_callback_fn(callback_fn)
    ):
        input_.id = f"{prefix}{parameter_name}"
        inputs_with_ids.append(copy.deepcopy(input_))

    return inputs_with_ids


def _make_input_groups(inputs_with_ids, update_live, prefix=""):
    input_groups = []

    for idx, input_ in enumerate(inputs_with_ids):
        label = (
            f"{input_.id}"
            if (not hasattr(input_, "label_") or input_.label_ is None)
            else input_.label_
        )
        # Strip the prefix from the label display
        display_label = label
        if prefix and display_label.startswith(prefix):
            display_label = display_label[len(prefix):]
        display_label = display_label.replace("_", " ").title()

        ack_component = (
            Fastify(component=html.Div(), component_property="children")
            if (not hasattr(input_, "ack") or input_.ack is None)
            else input_.ack
        )
        ack_component.id = f"{input_.id}_ack"

        input_.ack = ack_component

        input_groups.append(
            dmc.Stack(
                [
                    dmc.Text(display_label, size="sm", fw=500),
                    input_,
                    ack_component,
                ],
                gap=4,
            )
        )

    button_row = html.Div(
        [
            dmc.Button(
                "Submit",
                id=f"{prefix}submit_inputs",
                n_clicks=0,
                fullWidth=True,
            ),
        ],
        style={"paddingTop": "8px"}
        if update_live is False
        else {"display": "none"},
    )

    input_groups.append(button_row)

    return input_groups


# Output utils
def _assign_ids_to_outputs(outputs, callback_fn, prefix=""):
    """
    Modify the 'id' property of outputs.
    """
    if not isinstance(outputs, list):
        outputs = [outputs]

    inferred = _infer_variable_names(callback_fn, upper_case=False)
    if not inferred or len(inferred) != len(outputs):
        inferred = [f"output_{i + 1}" for i in range(len(outputs))]

    outputs_with_ids = []

    for output_, output_name in zip(outputs, inferred):
        output_.id = f"{prefix}output_{output_name}"
        outputs_with_ids.append(copy.deepcopy(output_))

    return outputs_with_ids


def _make_output_groups(outputs, update_live, prefix=""):
    output_groups = []

    for idx, output_ in enumerate(outputs):
        label = f"Output {idx + 1}" if output_.label_ is None else output_.label_
        # Strip the prefix from the label display
        if prefix and label.startswith(prefix):
            label = label[len(prefix):]
        label = label.replace("_", " ").title()
        output_groups.append(
            dmc.Paper(
                [
                    dmc.Text(label, size="xs", fw=500, c="dimmed", mb=8),
                    html.Div(
                        output_,
                        style={"width": "100%", "overflow": "hidden", "flex": "1"},
                    ),
                ],
                p="md",
                radius="sm",
                withBorder=True,
                style={"width": "100%", "display": "flex", "flexDirection": "column", "flex": "1"},
            )
        )

    button_row = html.Div(
        [
            dmc.Button(
                "Clear",
                variant="outline",
                id=f"{prefix}reset_inputs",
                n_clicks=0,
                size="compact-sm",
            )
        ],
        style={"paddingTop": "8px"}
        if update_live is False
        else {"display": "none"},
    )

    output_groups.append(button_row)

    return output_groups


def _make_download_children(download_dict, component_id):
    """Convert a download dict into a button + hidden dcc.Download pair.

    The button click triggers a clientside callback that copies
    dcc.Store data into dcc.Download, so the browser download only
    fires when the user explicitly clicks.
    """
    if not isinstance(download_dict, dict) or "content" not in download_dict:
        return html.Div("No download available", style={"color": "#868e96", "fontSize": "13px"})

    filename = download_dict.get("filename", "download.txt")
    store_id = f"{component_id}_download_store"
    download_id = f"{component_id}_download_trigger"
    btn_id = f"{component_id}_download_btn"

    return html.Div([
        dcc.Store(id=store_id, data=download_dict),
        dcc.Download(id=download_id),
        dmc.Button(
            f"Download {filename}",
            id=btn_id,
            leftSection=DashIconify(icon="ic:baseline-download", width=18),
            variant="light",
            size="sm",
            fullWidth=True,
        ),
    ])


def _get_transform_function(output, tag, component_id, counter, partial_update=False, stream=False):
    "Utility for _transform_outputs. Defines the transform function to be applied to a Fast component's property."

    if tag == "Chat":
        chatify_partial = functools.partial(Chatify, component_id=component_id, counter=counter, partial_update=partial_update, stream=stream)
        return chatify_partial

    if tag == "Download":
        return functools.partial(_make_download_children, component_id=component_id)

    subclass = type(output)
    _transform_mapper = {plt.Figure: _mpl_to_b64,
                         PIL.Image.Image: _pil_to_b64,
                         pd.DataFrame: lambda x: x.to_dict(orient="records")}

    for class_ in _transform_mapper:
        if issubclass(subclass, class_):
            return _transform_mapper[class_]

    no_transform_fxn = lambda x: x

    return no_transform_fxn


def _transform_outputs(output_states, tags, outputs_with_ids, counter):
    "Transform outputs to fit in the desired components"

    return [
        _get_transform_function(o, tag, ot.id, counter, False, ot.stream)(o)
        for (o, tag, ot) in zip(output_states, tags, outputs_with_ids)
    ]


def _transform_inputs(inputs, tags):
    "Transform inputs to fit in the desired components"

    transformed_inputs = []
    for inp, tag in zip(inputs, tags):
        if inp is None:
            transformed_inputs.append(inp)

        elif tag == "Image":
            transformed_inputs.append(_b64_to_pil(inp))

        else:
            transformed_inputs.append(inp)

    return transformed_inputs


def _friendly_error_message(error_text):
    """Translate common Python errors into beginner-friendly messages."""
    lower = error_text.lower()

    # Type mismatch: function returned wrong number of values
    if "not enough values to unpack" in lower or "too many values to unpack" in lower:
        return "Your function returned a different number of values than expected. Check that the number of return values matches the number of output components."

    # Missing return
    if "'nonetype' object is not" in lower and ("subscriptable" in lower or "iterable" in lower):
        return "Your function returned None. Make sure it has a return statement that produces the expected output."

    # Chat component format
    if "chat component requires" in lower:
        return error_text  # Already a friendly message

    # Common attribute errors
    if "has no attribute" in lower:
        return f"A component or object is missing an expected attribute. Details: {error_text}"

    # File not found
    if "no such file or directory" in lower or "filenotfounderror" in lower:
        return f"A file could not be found. Details: {error_text}"

    # Import errors
    if "no module named" in lower:
        module = error_text.split("'")[1] if "'" in error_text else "unknown"
        return f"Missing dependency: '{module}'. Install it with: pip install {module}"

    # Fallback: capitalize first letter
    return error_text.capitalize() if error_text else "An unexpected error occurred."


def _get_error_notification_component(error_text):
    return [dict(
        title="Something went wrong",
        id="show-notify",
        action="show",
        color="red",
        message=_friendly_error_message(error_text),
        icon=DashIconify(icon="bxs:error"),
        autoClose=8000,
    )]


def _clean_text(string, upper_case=False):
    # Use regular expression to replace non-alphanumeric characters with underscores
    pattern_non_alpha_numeric = r"\W"  # \W matches any non-alphanumeric character
    replacement_non_alpha_numeric = "_"
    string = re.sub(pattern_non_alpha_numeric, replacement_non_alpha_numeric, string)

    # Use regular expression to remove consecutive underscores and boundary underscores
    pattern_consecutive_underscores = r"(^_+)|(_{2,})|(_+$)"
    replacement_consecutive_underscores = ""
    string = re.sub(
        pattern_consecutive_underscores, replacement_consecutive_underscores, string
    )

    if upper_case:
        return string.upper()
    
    return string


def _infer_variable_names(func, upper_case=False):
    try:
        s = inspect.getsource(func)
    except OSError:
        try:
            import dill.source
            s = dill.source.getsource(func)
        except OSError:
            return None

    final_line = s.split("return")[-1].strip()
    line_without_comment = final_line.split("#")[0].strip().split(",")

    variable_names = [_clean_text(s, upper_case=upper_case) for s in line_without_comment]

    return variable_names


def _get_default_property(component_type):
    """
    Define a list of all important Dash components and their main
    properties to use as default.
    """

    try:
        default_component_attributes = {
            # Dash Core Components
            dcc.DatePickerSingle: "date",
            dcc.Dropdown: "value",
            dcc.Graph: "figure",
            dcc.Input: "value",
            dcc.Link: "href",
            dcc.Markdown: "children",
            dcc.RangeSlider: "value",
            dcc.RadioItems: "value",
            dcc.Slider: "value",
            dcc.Textarea: "value",
            dcc.Upload: "contents",
            # Dash Bootstrap Components
            dbc.Alert: "children",
            dbc.Badge: "children",
            dbc.Checkbox: "value",
            dbc.Col: "children",
            dbc.Collapse: "is_open",
            dbc.Container: "children",
            dbc.DropdownMenu: "children",
            dbc.Form: "children",
            dbc.Input: "value",
            dbc.ListGroup: "children",
            dbc.ListGroupItem: "children",
            dbc.Modal: "is_open",
            dbc.Row: "children",
            dbc.Table: "children",
            # Dash HTML Components
            html.H1: "children",
            html.H2: "children",
            html.H3: "children",
            html.H4: "children",
            html.H5: "children",
            html.H6: "children",
            html.I: "children",
            html.Iframe: "srcdoc",
            html.Img: "src",
            html.Table: "children",
            html.Tbody: "children",
            html.Td: "children",
            html.Textarea: "value",
            html.Tfoot: "children",
            html.Th: "children",
            html.Thead: "children",
            html.Title: "children",
            html.Video: "src",
            # Dash mantine components
            dmc.Checkbox: "checked",
            dmc.Chip: "checked",
            dmc.ChipGroup: "value",
            dmc.ColorPicker: "value",
            dmc.DatePicker: "value",
            dmc.JsonInput: "value",
            dmc.MultiSelect: "value",
            dmc.NumberInput: "value",
            dmc.PasswordInput: "value",
            dmc.RadioGroup: "value",
            dmc.SegmentedControl: "value",
            dmc.Select: "value",
            dmc.Slider: "value",
            dmc.Switch: "checked",
            dmc.TextInput: "value",
            dmc.Textarea: "value",
            dmc.TimeInput: "value",
            dmc.Blockquote: "children",
            dmc.Code: "children",
            dmc.List: "children",
            dmc.Text: "children",
            dmc.Title: "children",
        }

        default_property = default_component_attributes.get(component_type, "value")

    except Exception as e:
        warnings.warn(str(e))
        default_property = "value"

    return default_property


def _parse_docstring_as_markdown(func, title=None, get_short=False):
    """
    Generate markdown documentation from the docstring of a function.

    Args:
        func (function): The function to document.
        title (str, optional): Title of the text. If None, it is evaluated. Defaults to None.
        get_short (bool, optional): If True, returns only the short description. Defaults to False.

    Returns:
        str: Markdown documentation string.
    """
    logging.warning("Parsing function docstring is still an experimental feature. To reduce uncertainty, consider setting `about` to `False`.")

    parsed = docstring_parser.parse(func.__doc__)

    if get_short == True:
        return parsed.short_description

    # Start with the function description
    md_list = [
        f"#### {func.__name__.replace('_', ' ').title() if not title else title}",
        "",
        parsed.short_description or "",
        "",
        parsed.long_description or "",
        "",
    ]

    # Add parameters in table format
    if parsed.params:
        md_list.extend(
            [
                "##### Parameters",
                "| Name | Type | Mandatory | Default | Description |",
                "| ---- | ---- | --------- | ------- | ----------- |",
            ]
        )

        for param in parsed.params:
            param_line = (
                f"| {param.arg_name} "
                f"| {param.type_name or 'Not specified'} "
                f"| {'No' if param.is_optional else 'Yes'} "
                f"| {param.default or 'None'} "
                f"| {param.description or 'No description provided'} |"
            )
            md_list.append(param_line)

    md_list.extend(["# ", "# "])

    # Add return values in table format
    if parsed.returns:
        md_list.extend(
            ["", "##### Returns", "| Type | Description |", "| ---- | ----------- |"]
        )

        return_line = (
            f"| {parsed.returns.type_name or 'Not specified'} "
            f"| {parsed.returns.description or 'No description provided'} |"
        )
        md_list.append(return_line)

    # Join all and return markdown string
    return "\n".join(md_list)
