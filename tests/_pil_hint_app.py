"""PEP-563 module returning a PIL image via the loose `-> Image` spelling (#156).

`from PIL import Image` binds a *module* to the name, and the output inference
has a by-name fallback for exactly this spelling. Resolving the annotation
string must not hand that fallback a module object — a returned picture would
render as an <h1>.
"""

from __future__ import annotations

from PIL import Image


def make_thumb(size: int = 64) -> Image:
    """Solid square thumbnail."""
    return Image.new("RGB", (size, size), "red")
