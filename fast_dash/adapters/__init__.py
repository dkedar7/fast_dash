"""Optional adapters that let ``chat=True`` accept non-callback agents.

Adapters are import-light: detection never imports the heavy extra, and the
builder raises a clear, ASCII ``ImportError`` naming the pip extra when the
dependency is missing. See :mod:`fast_dash.adapters.langstage`.
"""
