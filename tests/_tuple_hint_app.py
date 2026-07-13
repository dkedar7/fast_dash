"""A plain module using `from __future__ import annotations` (#156).

Under future annotations every hint reaches fast_dash as a *string*, so a
`Tuple[...]` return hint is not even recognizably a tuple until it's resolved.
Lives in its own module because a function defined inside a test can't have its
annotations resolved against that test's locals.
"""

from __future__ import annotations

from typing import Tuple

import plotly.graph_objects as go


def chart_and_caption(n: int = 3) -> Tuple[go.Figure, str]:
    """Chart n bars and caption it."""
    return go.Figure(go.Bar(x=list(range(n)), y=list(range(n)))), f"{n} bars"
