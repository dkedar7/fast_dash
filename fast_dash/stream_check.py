"""``fastdash doctor --stream URL``: check a running app really streams (#352).

The streaming unit tests capture ``emit`` in-process, so they prove the server
*sends* each partial value, not that a client *receives* them while the
callback is still running. #333 broke exactly that delivery (plain gunicorn:
no pushes, only the final value) while those tests stayed green.

This connects to the app the way the page does, on the transport the app
actually uses, presses Run once, and counts the pushes that arrive before the
final response:

* Flask (the default): a socket.io client (long-polling, so only ``requests``,
  which Dash already installs), then a POST to ``_dash-update-component`` with
  that socket's id, exactly as the page sends it.
* ``backend="fastapi"``: Dash's native ``_dash-ws-callback`` WebSocket, which
  carries both the Run and its ``set_props`` pushes.

It runs the app's callback once, with the inputs' current values.
"""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SUBMIT = ("submit_inputs", "n_clicks")


class CheckFailed(Exception):
    """A step failed; the message says which and the likely cause."""


# --- reading the app ---------------------------------------------------------


def _get_json(url, timeout):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        raise CheckFailed(f"{url} answered HTTP {e.code}. Is this the app's root URL?") from None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise CheckFailed(f"could not reach {url}: {reason}. Is the app running?") from None
    try:
        return json.loads(body)
    except ValueError:
        raise CheckFailed(f"{url} did not return JSON. Is this a Fast Dash app's root URL?") from None


def _run_callback(deps):
    """The server-side Run callback: the one ``submit_inputs.n_clicks`` triggers."""
    for cb in deps:
        if cb.get("clientside_function"):
            continue
        if any((i.get("id"), i.get("property")) == SUBMIT for i in cb.get("inputs", [])):
            return cb
    return None


def _walk(node, found):
    """Collect ``{id: props}`` for every component with a string id in a layout tree."""
    if isinstance(node, dict):
        props = node.get("props")
        if isinstance(props, dict):
            cid = props.get("id")
            if isinstance(cid, str):
                found[cid] = props
            for v in props.values():
                _walk(v, found)
        else:
            for v in node.values():
                _walk(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk(v, found)
    return found


def _split_outputs(output):
    """Dash's multi-output string ``..a.children...b.value..`` as dependency dicts."""
    parts = output[2:-2].split("...") if output.startswith("..") else [output]
    outs = []
    for p in parts:
        cid, _, prop = p.rpartition(".")
        outs.append({"id": cid, "property": prop.split("@")[0]})
    return outs


def _payload(cb, layout_props, socket_id=None):
    def value(dep):
        if (dep["id"], dep["property"]) == SUBMIT:
            return 1
        if dep["id"] == "socketio" and dep["property"] == "socketId":
            return socket_id
        return layout_props.get(dep["id"], {}).get(dep["property"])

    output = cb["output"]
    outs = _split_outputs(output)
    return {
        "output": output,
        "outputs": outs if output.startswith("..") else outs[0],
        "inputs": [{**d, "value": value(d)} for d in cb["inputs"]],
        "changedPropIds": ["submit_inputs.n_clicks"],
        "state": [{**d, "value": value(d)} for d in cb.get("state", [])],
    }


# --- the two transports -------------------------------------------------------


def _check_socketio(base, cb, layout_props, timeout, report, step):
    try:
        import socketio
    except ImportError:          # pragma: no cover - flask-socketio brings it
        raise CheckFailed("the python-socketio client is missing: pip install python-socketio") from None
    try:
        import requests  # noqa: F401  (the polling transport needs it)
    except ImportError:          # pragma: no cover - Dash brings it
        raise CheckFailed("the socket.io client needs requests: pip install requests") from None

    frames = []
    t0 = time.monotonic()
    sio = socketio.Client(reconnection=False)

    @sio.on("*")
    def _any(event, data=None):          # every push: emit(<output id>, {...})
        if isinstance(data, dict) and "value" in data:
            frames.append({"t": round(time.monotonic() - t0, 3), "id": event,
                           "value": data.get("value")})

    try:
        sio.connect(base, transports=["polling"], wait_timeout=timeout)
    except Exception as e:                # noqa: BLE001
        raise CheckFailed(f"socket.io connect to {base} failed: {e}") from None
    try:
        # The namespace sid (what the page's socketId holds and emit(to=) targets),
        # not sio.sid, which is the engine.io session.
        sid = sio.get_sid("/")
        step("transport", f"socket.io (Flask backend), socket {sid}")
        body = json.dumps(_payload(cb, layout_props, socket_id=sid)).encode()
        req = urllib.request.Request(
            urllib.parse.urljoin(base, "_dash-update-component"), data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status = r.status
                r.read()
        except urllib.error.HTTPError as e:
            raise CheckFailed(f"the Run request failed with HTTP {e.code}: "
                              f"{e.read()[:200].decode('utf-8', 'replace')}") from None
        done = round(time.monotonic() - t0, 3)
        # A push emitted just before the response can land a moment after it.
        time.sleep(0.3)
    finally:
        sio.disconnect()
    step("run", f"Run returned HTTP {status} after {done:g}s")
    return frames, done


def _check_native(base, cb, layout_props, timeout, report, step):
    try:
        from websockets.sync.client import connect
    except ImportError:
        raise CheckFailed(
            "a WebSocket client is needed for backend='fastapi' apps: pip install websockets"
        ) from None
    parsed = urllib.parse.urlsplit(base)
    ws_url = urllib.parse.urlunsplit(
        ("wss" if parsed.scheme == "https" else "ws", parsed.netloc,
         parsed.path.rstrip("/") + "/_dash-ws-callback", "", ""))
    origin = f"{parsed.scheme}://{parsed.netloc}"
    frames = []
    t0 = time.monotonic()
    try:
        ws = connect(ws_url, origin=origin, open_timeout=timeout)
    except Exception as e:                # noqa: BLE001
        raise CheckFailed(f"WebSocket connect to {ws_url} failed: {e}") from None
    with ws:
        step("transport", "native WebSocket (FastAPI backend)")
        ws.send(json.dumps({"type": "callback_request", "requestId": "doctor-1",
                            "rendererId": "fastdash-doctor",
                            "payload": _payload(cb, layout_props)}))
        deadline = t0 + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise CheckFailed(f"no Run response within {timeout:g}s")
            try:
                raw = ws.recv(timeout=left)
            except TimeoutError:
                continue
            msgs = json.loads(raw)
            for m in msgs if isinstance(msgs, list) else [msgs]:
                kind = m.get("type")
                if kind == "set_props":
                    p = m.get("payload", {})
                    for prop, v in (p.get("props") or {}).items():
                        if prop in ("children", "value", "figure", "data", "src"):
                            frames.append({"t": round(time.monotonic() - t0, 3),
                                           "id": p.get("componentId"), "value": v})
                elif kind == "callback_response":
                    done = round(time.monotonic() - t0, 3)
                    p = m.get("payload") or {}
                    if isinstance(p, dict) and p.get("status") == "error":
                        raise CheckFailed(f"the Run failed on the server: {p.get('message')}")
                    step("run", f"Run returned after {done:g}s")
                    return frames, done


# --- the check ----------------------------------------------------------------


def _short(v, n=40):
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[: n - 3] + "..."


def _check(url, timeout, report):
    def step(name, detail):
        report["steps"].append({"step": name, "ok": True, "detail": detail})

    base = url if url.endswith("/") else url + "/"
    deps = _get_json(urllib.parse.urljoin(base, "_dash-dependencies"), timeout)
    cb = _run_callback(deps)
    if cb is None:
        raise CheckFailed("found no Run button callback. Is this a single-function "
                          "Fast Dash app? (chat=True and multi-function apps aren't "
                          "covered yet.)")
    states = {(s.get("id"), s.get("property")) for s in cb.get("state", [])}
    native = bool(cb.get("websocket"))
    if not native and ("socketio", "socketId") not in states:
        raise CheckFailed("this app doesn't stream: its Run has no socket.io or "
                          "WebSocket channel. Build it with stream=True.")
    layout_props = _walk(_get_json(urllib.parse.urljoin(base, "_dash-layout"), timeout), {})

    run = _check_native if native else _check_socketio
    frames, done = run(base, cb, layout_props, timeout, report, step)
    early = [f for f in frames if f["t"] < done]
    report["frames"] = frames
    report["transport"] = "websocket" if native else "socket.io"
    if not early:
        hint = (
            "Under gunicorn's default sync worker the server can't push while the "
            "callback runs: deploy with backend='fastapi' and uvicorn, or a single "
            "eventlet/gevent worker (see the deployment guide, 'Streaming and chat apps')."
            if not native else
            "Check that the callback yields (or calls update()) before it returns."
        )
        raise CheckFailed(f"the Run finished but no update arrived while it ran "
                          f"({len(frames)} after). {hint}")
    shown = " / ".join(_short(f["value"]) for f in early[:3])
    more = " / ..." if len(early) > 3 else ""
    step("streaming", f"{len(early)} update{'s' * (len(early) != 1)} arrived while the "
                      f"Run was in flight, {early[0]['t']:g}s to {early[-1]['t']:g}s ({shown}{more})")


def check_stream(url, timeout=30.0):
    """Run the check against ``url``. Return ``(ok, report)``; never raises."""
    report = {"url": url, "steps": []}
    result = {}

    def target():
        try:
            _check(url, timeout, report)
            result["ok"] = True
        except CheckFailed as e:
            result["error"] = str(e)
        except BaseException as e:              # noqa: BLE001
            result["error"] = f"{type(e).__name__}: {e}"

    # A hard overall cap, so a server that accepts and then hangs can't wedge
    # a HEALTHCHECK.
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout + 2)
    if t.is_alive():
        result["error"] = f"no answer within {timeout:g}s"
        if any(s["step"] == "transport" for s in report["steps"]):
            # Connected, then the Run never came back: the server can't serve
            # the socket and the Run at once, as under a single sync worker.
            result["error"] += (
                ": the Run never returned while the socket was open. A single "
                "sync worker can't serve both; deploy with backend='fastapi' and "
                "uvicorn, or a single eventlet/gevent worker (see the deployment "
                "guide, 'Streaming and chat apps')."
            )
    if result.get("ok"):
        report["ok"] = True
        return True, report
    report.update(ok=False, error=result.get("error", "unknown failure"))
    return False, report


def print_report(ok, report):
    print(f"Connecting to {report['url']} ...")
    for s in report.get("steps", []):
        print(f"  {s['step']:16} OK   {s['detail']}")
    if ok:
        print("Streaming wire healthy.")
    else:
        print(f"Problem: {report['error']}")
