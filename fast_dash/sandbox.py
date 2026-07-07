"""Run LLM-written Python in an isolated subprocess, safely (0.6.0).

A generalized port of DataChat's analysis sandbox. Each call to :func:`run_code`
spawns a fresh subprocess with a **scrubbed environment** (no API keys or
tokens leak in), a wall-clock timeout, and -- inside the child -- a function-level
network block plus CPU/memory ceilings (POSIX only). Injected variables are
handed over by pickle; the child returns any last-expression value, printed
output, a produced plotly figure, a produced table, or an error.

Unlike DataChat's engine (which always injected a DataFrame ``df``), this one is
data-agnostic: pass whatever picklable objects the code needs via ``inject``.

Everything the child returns is JSON-safe: the figure is a plotly JSON string
and the table is a list of records, so the result crosses the wire (and reaches
an LLM) without any custom serialization.
"""

from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Environment variable names carrying anything secret are dropped before the
# child sees the environment (defense in depth; the child also blocks network).
_SENSITIVE = (
    "KEY", "TOKEN", "SECRET", "PASSWORD",
    "OPENROUTER", "OPENAI", "ANTHROPIC",
)


def _scrubbed_env() -> dict:
    """A copy of the environment with every secret-looking variable removed."""
    return {
        k: v
        for k, v in os.environ.items()
        if not any(s in k.upper() for s in _SENSITIVE)
    }


# The runner is embedded (written to the temp workdir per call) rather than
# shipped as a sibling module, so the sandbox stays a single self-contained file
# and the child's import surface is exactly what it reads from disk.
_RUNNER_SRC = r'''
"""Executes one snippet of code in an isolated subprocess (fast_dash sandbox).

Invoked as ``python _sandbox_runner.py <workdir>``. Reads ``inject.pkl`` (a dict
of variables) and ``code.py`` from the workdir, runs the code with those
variables in scope, and writes ``result.json`` with any last-expression value,
printed output, produced plotly figure, produced table, or error.

Hardening (defense in depth -- the parent also scrubs secrets from the env):
network is disabled at the socket-function level, and CPU/address-space limits
are set where supported (POSIX).
"""

import ast
import io
import json
import pickle
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path


def _lock_down():
    # Disable network from inside the sandbox. Block the connection *functions*
    # + the connect() method rather than replacing the socket class itself,
    # which breaks stdlib imports (http.client etc.).
    import socket

    def _blocked(*a, **k):
        raise OSError("Network access is disabled in the sandbox.")

    socket.getaddrinfo = _blocked          # no DNS -> no hostname connections
    socket.create_connection = _blocked
    try:
        socket.socket.connect = lambda self, *a, **k: _blocked()
        socket.socket.connect_ex = lambda self, *a, **k: _blocked()
    except (TypeError, AttributeError):
        pass
    # CPU + memory ceilings (POSIX only; a no-op on Windows dev).
    if sys.platform != "win32":
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (12, 12))
            two_gb = 2 * 1024 * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (two_gb, two_gb))
        except Exception:
            pass


def _jsonable(value):
    "Best-effort: keep JSON-native values, stringify the rest."
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    try:
        json.dumps(value)
        return value
    except Exception:
        return repr(value)


def _run(workdir):
    ns = {"__name__": "__sandbox__"}
    inject_path = workdir / "inject.pkl"
    if inject_path.exists():
        with open(inject_path, "rb") as fh:
            ns.update(pickle.load(fh))
    # pandas / numpy / plotly are convenience globals when installed, matching a
    # notebook cell. Missing ones simply aren't injected (the code may not need
    # them); an import inside the code still works.
    for name, mod in (("pd", "pandas"), ("np", "numpy"),
                      ("px", "plotly.express"), ("go", "plotly.graph_objects")):
        if name in ns:
            continue
        try:
            ns[name] = __import__(mod, fromlist=["*"]) if "." in mod \
                else __import__(mod)
        except Exception:
            pass

    code = (workdir / "code.py").read_text(encoding="utf-8")
    out = {"stdout": "", "result": None, "figure": None, "table": None, "error": None}
    buf = io.StringIO()
    last_val = None
    try:
        tree = ast.parse(code)
        with redirect_stdout(buf):
            if tree.body and isinstance(tree.body[-1], ast.Expr):
                # Run everything but the trailing expression, then eval it so a
                # bare ``px.bar(...)`` last line is captured like a notebook cell.
                exec(compile(ast.Module(tree.body[:-1], []), "<code>", "exec"), ns)
                last_val = eval(
                    compile(ast.Expression(tree.body[-1].value), "<code>", "eval"), ns
                )
            else:
                exec(compile(tree, "<code>", "exec"), ns)
    except Exception:
        out["error"] = traceback.format_exc(limit=3)[-1500:]
    out["stdout"] = buf.getvalue()[-4000:]

    # Capture a produced plotly figure: a ``fig`` variable, else a last-expr Figure.
    try:
        import plotly.graph_objects as go

        fig = ns.get("fig")
        if not isinstance(fig, go.Figure):
            fig = last_val if isinstance(last_val, go.Figure) else None
        if isinstance(fig, go.Figure):
            out["figure"] = fig.to_json()
    except Exception:
        pass

    # Capture a produced table: a ``result`` DataFrame/Series, else a last-expr one.
    try:
        import pandas as pd

        tbl = ns.get("result")
        if not isinstance(tbl, (pd.DataFrame, pd.Series)):
            tbl = last_val if isinstance(last_val, (pd.DataFrame, pd.Series)) else None
        if isinstance(tbl, pd.Series):
            tbl = tbl.rename(tbl.name or "value").reset_index()
        if isinstance(tbl, pd.DataFrame):
            out["table"] = {
                "records": tbl.head(200).to_dict("records"),
                "shape": list(tbl.shape),
            }
    except Exception:
        pass

    # A scalar / text last-expression value (only when it isn't a figure/table
    # already surfaced above) is echoed as ``result`` so the caller sees it.
    if out["figure"] is None and out["table"] is None and last_val is not None:
        out["result"] = _jsonable(last_val)
    return out


def main():
    workdir = Path(sys.argv[1])
    _lock_down()
    try:
        result = _run(workdir)
    except Exception:
        result = {"stdout": "", "result": None, "figure": None, "table": None,
                  "error": traceback.format_exc(limit=2)[-1000:]}
    (workdir / "result.json").write_text(
        json.dumps(result, default=str), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
'''


def run_code(
    code: str,
    inject: dict[str, Any] | None = None,
    timeout: int = 25,
) -> dict:
    """Execute ``code`` in a locked-down subprocess and return its result.

    ``inject`` maps variable names to values made available in the code's scope
    (values must be picklable; DataFrames are fine). ``timeout`` is the wall
    clock in seconds after which the child is killed.

    Returns a JSON-safe dict with keys:

    * ``stdout`` -- captured print output (str),
    * ``result`` -- a scalar/text last-expression value, else None,
    * ``figure`` -- a produced plotly figure as a JSON string, else None,
    * ``table``  -- ``{"records": [...], "shape": [rows, cols]}``, else None,
    * ``error``  -- a traceback string if the code raised, else None.
    """
    with tempfile.TemporaryDirectory(prefix="fastdash_sandbox_") as tmp:
        work = Path(tmp)
        (work / "_sandbox_runner.py").write_text(_RUNNER_SRC, encoding="utf-8")
        (work / "code.py").write_text(code, encoding="utf-8")
        if inject:
            with open(work / "inject.pkl", "wb") as fh:
                pickle.dump(dict(inject), fh, protocol=pickle.HIGHEST_PROTOCOL)
        try:
            proc = subprocess.run(
                [sys.executable, str(work / "_sandbox_runner.py"), str(work)],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_scrubbed_env(),
                cwd=str(work),
            )
        except subprocess.TimeoutExpired:
            return {
                "stdout": "", "result": None, "figure": None, "table": None,
                "error": "The code took longer than %ss and was stopped." % timeout,
            }
        out_file = work / "result.json"
        if out_file.exists():
            return json.loads(out_file.read_text(encoding="utf-8"))
        return {
            "stdout": (proc.stdout or "")[-2000:],
            "result": None, "figure": None, "table": None,
            "error": (proc.stderr or "").strip()[-1200:] or "No result was produced.",
        }
