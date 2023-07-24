"""Top-level package for Fast Dash."""

__author__ = """Kedar Dabhadkar"""
__email__ = "kedar@fastdash.app"
__version__ = "0.2.1"

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
    html,
)
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
    "html",
]
