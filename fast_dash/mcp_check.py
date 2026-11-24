"""``fastdash doctor --mcp URL``: smoke-test a running app's MCP surface (#341).

Connects to ``URL`` over streamable HTTP with the ``mcp`` SDK, the same
client path the AI-agents guide documents, and checks what an agent needs:
``initialize`` succeeds, the Fast Dash tools are listed, and ``describe_app``
returns a well-formed contract. ``mcp_test_client()`` covers the in-process
case; this covers a live local, containerized or remote server.

With ``invoke=True`` (``--invoke``, #357) it also runs the app once through
the ``invoke`` tool, so a callback that raises, or an app that can't run from
its current values, fails the check instead of passing on its contract alone.
That runs the real callback, side effects included, so it is opt-in.

With ``config=`` (``--config``, #383) a healthy check ends with the client
config for that exact URL, in each client's own shape (``mcpServers`` vs
``servers``), named after the app's title.
"""

import asyncio
import json
import re
import urllib.error
import urllib.request

# The tools every Fast Dash MCP app serves (DynamicDash adds none we require).
REQUIRED_TOOLS = ("describe_app", "invoke", "set_input", "set_inputs")

# --config choices; "all" prints every one. Shapes match the AI-agents guide.
CONFIG_CLIENTS = ("claude", "cursor", "vscode")
CONFIG_CHOICES = CONFIG_CLIENTS + ("all",)
DEFAULT_SERVER_NAME = "fast-dash-app"


class CheckFailed(Exception):
    """A step failed; the message says which and the likely cause."""


def _client():
    try:
        from mcp import ClientSession
    except ImportError:
        raise CheckFailed(
            "the 'mcp' package is needed to connect as an MCP client: "
            "pip install mcp"
        ) from None
    try:
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:          # older mcp releases spell it streamablehttp_client
        from mcp.client.streamable_http import (
            streamablehttp_client as streamable_http_client,
        )
    return ClientSession, streamable_http_client


def _probe(url, timeout=5):
    """Why ``url`` isn't an MCP endpoint, from a plain GET, else None."""
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream, */*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = r.headers.get("Content-Type", "")
            head = r.read(512).decode("utf-8", "replace").lower()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return (f"{url} answered 404: nothing is mounted there. Was the app "
                    "built with mcp_server=True, and is the path /mcp?")
        return f"{url} answered HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        return f"could not reach {url}: {reason}. Is the app running?"
    if "text/html" in ctype or "<html" in head or "<!doctype" in head:
        return (f"{url} returned the web page, not an MCP stream. Was the app "
                "built with mcp_server=True? Multi-function and steps apps "
                "skip the MCP surface.")
    return None


def _field(obj, snake, camel):
    """A result field under mcp 2.x (snake_case) or 1.x (camelCase) spelling."""
    value = getattr(obj, snake, None)
    return value if value is not None else getattr(obj, camel, None)


def _summarize_fields(fields, key):
    """``id:type`` for inputs, ``id:tag`` for outputs (``Graph`` says more than ``object``)."""
    return ", ".join(f"{f.get('id')}:{f.get(key) or f.get('type') or '?'}" for f in fields)


async def _check(url, report, invoke=False, invoke_inputs=None):
    ClientSession, streamable_http_client = _client()

    def step(name, detail):
        report["steps"].append({"step": name, "ok": True, "detail": detail})

    async with streamable_http_client(url) as (read, write, *_):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            info = _field(init, "server_info", "serverInfo")
            step("initialize", f"protocol {_field(init, 'protocol_version', 'protocolVersion') or '?'}, "
                               f"server {getattr(info, 'name', '?')} {getattr(info, 'version', '')}".strip())

            tools = [t.name for t in (await session.list_tools()).tools]
            missing = [t for t in REQUIRED_TOOLS if t not in tools]
            if missing:
                raise CheckFailed(
                    "connected, but the Fast Dash drive tools are not registered "
                    f"(missing: {', '.join(missing)}; listed: {', '.join(tools) or 'none'})"
                )
            report["tools"] = tools
            step("list_tools", ", ".join(tools))

            try:
                resources = [str(r.uri) for r in (await session.list_resources()).resources]
                report["resources"] = resources
                step("list_resources", ", ".join(resources) or "none")
            except Exception:                         # noqa: BLE001 - optional
                report["resources"] = None
                step("list_resources", "not served (optional)")

            result = await session.call_tool("describe_app", {})
            if _field(result, "is_error", "isError"):
                text = " ".join(getattr(b, "text", "") for b in result.content)
                raise CheckFailed(f"describe_app failed: {text or 'no message'}")
            contract = (_field(result, "structured_content", "structuredContent") or {}).get("result")
            if contract is None:
                text = "".join(getattr(b, "text", "") for b in result.content)
                try:
                    contract = json.loads(text)
                except ValueError:
                    raise CheckFailed("describe_app did not return JSON") from None
            if not (isinstance(contract, dict)
                    and isinstance(contract.get("inputs"), list)
                    and isinstance(contract.get("outputs"), list)):
                raise CheckFailed("describe_app returned no inputs/outputs lists")
            report["contract"] = contract
            ins, outs = contract["inputs"], contract["outputs"]
            step("describe_app",
                 f"{contract.get('title') or 'untitled'}: "
                 f"{len(ins)} input{'s' * (len(ins) != 1)} ({_summarize_fields(ins, 'type')}), "
                 f"{len(outs)} output{'s' * (len(outs) != 1)} ({_summarize_fields(outs, 'tag')})")

            if invoke:
                await _check_invoke(session, contract, invoke_inputs or {}, report, step)


def _tool_payload(result):
    """A tool result's JSON, from structured content or the text block."""
    structured = _field(result, "structured_content", "structuredContent")
    if isinstance(structured, dict) and "result" in structured:
        return structured["result"]
    text = "".join(getattr(b, "text", "") or "" for b in result.content)
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}


def _short(value, n=40):
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[: n - 3] + "..."


async def _check_invoke(session, contract, inputs, report, step):
    """Run the app once through ``invoke`` and require ``ok: true``."""
    known = [i.get("id") for i in contract["inputs"]]
    unknown = [k for k in inputs if k not in known]
    if unknown:
        raise CheckFailed(f"--invoke-input names no input of this app: {', '.join(unknown)} "
                          f"(its inputs: {', '.join(map(str, known)) or 'none'})")
    result = await session.call_tool("invoke", {"inputs": inputs} if inputs else {})
    payload = _tool_payload(result)
    report["invoke"] = payload
    if _field(result, "is_error", "isError"):
        text = payload.get("text") if isinstance(payload, dict) else None
        raise CheckFailed(f"invoke failed over MCP: {text or payload}")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        payload = payload if isinstance(payload, dict) else {"error": payload}
        if payload.get("missing"):
            names = ", ".join(map(str, payload["missing"]))
            raise CheckFailed(f"invoke can't run from the current values: {names} "
                              f"{'has' if len(payload['missing']) == 1 else 'have'} no value. "
                              f"Pass one with --invoke-input NAME=VALUE.")
        if payload.get("errors"):
            errs = "; ".join(f"{k}: {v}" for k, v in payload["errors"].items())
            raise CheckFailed(f"invoke rejected the inputs: {errs}")
        raise CheckFailed(f"invoke ran and the callback failed: {payload.get('error') or payload}")
    outputs = payload.get("outputs") or {}
    shown = ", ".join(f"{k}={_short(v)}" for k, v in list(outputs.items())[:3])
    more = ", ..." if len(outputs) > 3 else ""
    took = payload.get("duration_ms")
    step("invoke", f"ran{f' in {took:g} ms' if isinstance(took, (int, float)) else ''}: "
                   f"{shown or 'no outputs'}{more}")


def server_name(title):
    """A config key from the app's title: ``"Plot Bars"`` -> ``plot-bars``."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")
    return slug or DEFAULT_SERVER_NAME


def client_configs(url, name, which="all"):
    """``{client: config}`` for ``url``; ``which`` is a client or ``"all"``."""
    shapes = {
        "claude": {"mcpServers": {name: {"type": "http", "url": url}}},
        "cursor": {"mcpServers": {name: {"url": url}}},
        "vscode": {"servers": {name: {"type": "http", "url": url}}},
    }
    clients = CONFIG_CLIENTS if which == "all" else (which,)
    return {c: shapes[c] for c in clients}


def check_mcp(url, timeout=30.0, invoke=False, invoke_inputs=None, config=None):
    """Run the checks against ``url``. Return ``(ok, report)``; never raises.

    ``invoke=True`` also runs the app once with its current values, updated by
    ``invoke_inputs`` (``{input_id: value}``). ``config`` (a client or
    ``"all"``) adds ``report["config"]`` when the check passes.
    """
    report = {"url": url, "steps": []}
    try:
        asyncio.run(asyncio.wait_for(
            _check(url, report, invoke=invoke, invoke_inputs=invoke_inputs), timeout))
        report["ok"] = True
        if config:
            # Only for a healthy surface: a config for a broken one wastes a paste.
            name = server_name((report.get("contract") or {}).get("title"))
            report["config"] = client_configs(url, name, config)
        return True, report
    except CheckFailed as e:
        error = str(e)
    except asyncio.TimeoutError:
        cause = _probe(url)
        error = f"no answer within {timeout:g}s" + (f": {cause}" if cause else "")
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:                         # noqa: BLE001
        inner = _innermost(e)
        if isinstance(inner, CheckFailed):             # raised inside the session's task group
            error = str(inner)
        else:
            error = _probe(url) or f"{type(e).__name__}: {_first_cause(e)}"
    report.update(ok=False, error=error)
    return False, report


def _innermost(e):
    """The first leaf exception of an ExceptionGroup (or ``e`` itself)."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return e


def _first_cause(e):
    """The innermost message of an ExceptionGroup or chained error."""
    e = _innermost(e)
    return str(e) or type(e).__name__


def print_report(ok, report):
    print(f"Connecting to {report['url']} (streamable HTTP) ...")
    for s in report.get("steps", []):
        print(f"  {s['step']:16} OK   {s['detail']}")
    if ok:
        print("MCP surface healthy.")
        _print_configs(report.get("config"))
    else:
        print(f"Problem: {report['error']}")


_CONFIG_WHERE = {
    "claude": "Claude Code (.mcp.json)",
    "cursor": "Cursor (.cursor/mcp.json or ~/.cursor/mcp.json)",
    "vscode": "VS Code (.vscode/mcp.json)",
}


def _print_configs(configs):
    for client, cfg in (configs or {}).items():
        print()
        print(f"Client config for {_CONFIG_WHERE[client]}:")
        print(f"  {json.dumps(cfg)}")
        if client == "claude":
            (name, entry), = cfg["mcpServers"].items()
            print(f"Or run: claude mcp add --transport http {name} {entry['url']}")
