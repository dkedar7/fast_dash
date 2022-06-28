"""Top-level package for Fast Dash."""

__author__ = """Kedar Dabhadkar"""
__email__ = "kedar@fastdash.app"
__version__ = "0.1.6"

from fast_dash.Components import (
    Fastify,
    Text,
    TextArea,
    Slider,
    Upload,
    acknowledge_image_component,
    UploadImage,
    Image,
    Graph,
    dcc,
    dbc,
    html
)
from fast_dash.fast_dash import FastDash, fastdash

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
    "html"
]

