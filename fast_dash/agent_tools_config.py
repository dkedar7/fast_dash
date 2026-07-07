"""Config objects for the chat agent toolkit (0.6.0).

Kept in its own tiny module with no heavy imports so both the public API
(``from fast_dash import RunPython``) and the Round 2b tool-building code can
import it without a circular dependency on ``agent_tools`` (which pulls in
langchain / langgraph lazily).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RunPython:
    """Allowlist entry configuring the ``run_python`` chat tool.

    Passed inside ``chat_tools=`` to enable code execution with a chosen
    approval policy, e.g. ``chat_tools=(..., RunPython(approval=False))``.

    * ``approval`` -- require a human-in-the-loop approval before executing
      (default True). Round 2b wires the actual interrupt/exec engine.
    * ``name`` -- the tool name this entry gates (always ``"run_python"``); a
      field so the allowlist resolver can key on it uniformly with str entries.
    """

    approval: bool = True
    name: str = "run_python"
