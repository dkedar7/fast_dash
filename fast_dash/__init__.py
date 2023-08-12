"""Top-level package for Fast Dash."""

__author__ = """Kedar Dabhadkar"""
__email__ = "kedar@fastdash.app"
__version__ = "4"

from fast_dash.Components import (
    Graph,
    Image,
    Slider,
    Text,
    TextArea,
    Upload,
    UploadImage,
    acknowledge_image_component,
    dbc,
    dcc,
    dmc,
    html,
)
import dash
from fast_dash.fast_dash import FastDash, fastdash
from fast_dash.utils import Fastify

__all__ = [
    "FastDash",
    "fastdash",
    "Fastify",
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
    "dash"
]
