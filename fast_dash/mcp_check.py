"""``fastdash doctor --mcp URL``: smoke-test a running app's MCP surface (#341).

Connects to ``URL`` over streamable HTTP with the ``mcp`` SDK, the same
client path the AI-agents guide documents, and checks what an agent needs:
``initialize`` succeeds, the Fast Dash tools are listed, and ``describe_app``
returns a well-formed contract. ``mcp_test_client()`` covers the in-process
case; this covers a live local, containerized or remote server.
"""

import asyncio
import json
import urllib.error
import urllib.request

# The tools every Fast Dash MCP app serves (DynamicDash adds none we require).
REQUIRED_TOOLS = ("describe_app", "invoke", "set_input", "set_inputs")


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


async def _check(url, report):
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


def check_mcp(url, timeout=30.0):
    """Run the checks against ``url``. Return ``(ok, report)``; never raises."""
    report = {"url": url, "steps": []}
    try:
        asyncio.run(asyncio.wait_for(_check(url, report), timeout))
        report["ok"] = True
        return True, report
    except CheckFailed as e:
        error = str(e)
    except asyncio.TimeoutError:
        cause = _probe(url)
        error = f"no answer within {timeout:g}s" + (f": {cause}" if cause else "")
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:                         # noqa: BLE001
        error = _probe(url) or f"{type(e).__name__}: {_first_cause(e)}"
    report.update(ok=False, error=error)
    return False, report


def _first_cause(e):
    """The innermost message of an ExceptionGroup or chained error."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return str(e) or type(e).__name__


def print_report(ok, report):
    print(f"Connecting to {report['url']} (streamable HTTP) ...")
    for s in report.get("steps", []):
        print(f"  {s['step']:16} OK   {s['detail']}")
    if ok:
        print("MCP surface healthy.")
    else:
        print(f"Problem: {report['error']}")
