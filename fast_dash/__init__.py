"""Top-level package for Fast Dash."""

__author__ = """Kedar Dabhadkar"""
__email__ = "kedar@fastdash.app"
__version__ = "0.6.9"

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
from fast_dash.agent_tools_config import RunPython
from fast_dash.dynamic import DynamicDash, render_spec, COMPONENT_REGISTRY
from fast_dash.chat import (
    ChatContext,
    canvas_tool_specs,
    app_tool_specs,
    apply_tool_call,
)


# The chat-agent toolkit entry points (agent_toolkit / FastDashMiddleware /
# app_prompt) live in fast_dash.agent_tools. That module is heavy-import-free at
# its top (langchain / langgraph are imported *inside* the functions that need
# them), so importing fast_dash never drags in the optional [agent] extra. We
# still expose these names lazily via PEP 562 __getattr__ so the import graph of
# `import fast_dash` stays minimal and the [agent] ImportError only surfaces when
# a toolkit function actually runs -- not at package import.
_LAZY_AGENT_EXPORTS = ("agent_toolkit", "FastDashMiddleware", "app_prompt")


def __getattr__(name):
    if name in _LAZY_AGENT_EXPORTS:
        from fast_dash import agent_tools
        return getattr(agent_tools, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "FastDash",
    "fastdash",
    "ChatContext",
    "canvas_tool_specs",
    "app_tool_specs",
    "apply_tool_call",
    "agent_toolkit",
    "FastDashMiddleware",
    "app_prompt",
    "Fastify",
    "depends_on",
    "from_step",
    "RunPython",
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
