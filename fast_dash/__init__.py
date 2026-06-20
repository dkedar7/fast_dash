"""Top-level package for Fast Dash."""

__author__ = """Kedar Dabhadkar"""
__email__ = "kedar@fastdash.app"
__version__ = "0.4.0"

from fast_dash.Components import (
    Graph,
    Image,
    Slider,
    Text,
    TextArea,
    NumberInput,
    DateInput,
    ColorInput,
    MultiSelect,
    DateRange,
    Switch,
    PasswordInput,
    Markdown,
    Upload,
    UploadImage,
    acknowledge_image_component,
    dbc,
    dcc,
    dmc,
    html,
    PIL,
    Chat,
    Download,
    Table
)
import dash
from dash import Output, Input, State, callback, no_update
from fast_dash.fast_dash import FastDash, fastdash, update, notify
from fast_dash.utils import Fastify, depends_on, from_step
from fast_dash.dynamic import DynamicDash, render_spec, COMPONENT_REGISTRY

__all__ = [
    "FastDash",
    "fastdash",
    "Fastify",
    "depends_on",
    "from_step",
    "Text",
    "TextArea",
    "Slider",
    "Upload",
    "acknowledge_image_component",
    "UploadImage",
    "Image",
    "Graph",
    "dcc",
    "dbc",
    "dmc",
    "html",
    "dash",
    "PIL",
    "Chat",
    "Download",
    "NumberInput",
    "DateInput",
    "ColorInput",
    "MultiSelect",
    "DateRange",
    "Switch",
    "PasswordInput",
    "Markdown",
    "Table",
    "DynamicDash",
    "render_spec",
    "COMPONENT_REGISTRY",
]
