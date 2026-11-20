"""#371: invoke streams a yielding callback's frames as MCP progress."""

import json
import threading
import time

import pytest
from werkzeug.serving import make_server

from fast_dash import FastDash, PasswordInput, connect
from fast_dash.mcp import PROGRESS_MESSAGE_MAX_CHARS


def slow_count(n: int = 3) -> str:
    """Count to n, one line at a time."""
    out = ""
    for i in range(1, n + 1):
        out += f"tick {i}\n"
        time.sleep(0.3)
        yield out


FRAMES = ["tick 1\n", "tick 1\ntick 2\n", "tick 1\ntick 2\ntick 3\n"]


@pytest.mark.parametrize("backend", [None, "fastapi"])
def test_frames_arrive_as_progress_and_the_result_is_unchanged(backend):
    if backend:
        pytest.importorskip("fastapi")
    kw = {"backend": backend} if backend else {}
    with FastDash(callback_fn=slow_count, stream=True, mcp_server=True,
                  **kw).mcp_test_client() as app:
        seen = []
        run = app.invoke(inputs={"n": 3}, on_progress=seen.append)
        assert seen == FRAMES
        assert run["ok"] is True and run["outputs"] == {"output_output_1": FRAMES[-1]}
        # Same history as a call without progress.
        assert app.get_invocation(index=run["history_index"])["outputs"] == run["outputs"]
        # Without on_progress: one JSON answer, exactly as before.
        assert app.invoke(inputs={"n": 2})["outputs"] == {"output_output_1": FRAMES[1]}


def test_non_generator_callback_just_returns():
    def double(n: int = 2) -> int:
        """Double."""
        return n * 2
    with FastDash(callback_fn=double, mcp_server=True).mcp_test_client() as app:
        seen = []
        assert app.invoke(inputs={"n": 4}, on_progress=seen.append)["outputs"] == {
            "output_output_1": 8}
        assert seen == []


def test_rejected_inputs_answer_over_the_stream():
    with FastDash(callback_fn=slow_count, mcp_server=True).mcp_test_client() as app:
        seen = []
        r = app.invoke(inputs={"n": "lots"}, on_progress=seen.append)
        assert r["ok"] is False and "n" in r["errors"] and seen == []


def test_multi_output_frames_name_each_output():
    def two(n: int = 2):
        """Two outputs."""
        for i in range(1, n + 1):
            yield f"step {i}", i * 10

    with FastDash(callback_fn=two, mcp_server=True,
                  outputs=["Text", "Text"]).mcp_test_client() as app:
        seen = []
        app.invoke(inputs={"n": 2}, on_progress=seen.append)
        frames = [json.loads(m) for m in seen]
        assert len(frames) == 2
        assert list(frames[-1].values()) == ["step 2", 20]


def test_a_secret_never_rides_a_progress_frame():
    def echo(key: PasswordInput = "", n: int = 2) -> str:
        """Leaks the key on purpose."""
        for i in range(n):
            yield f"{i}: using {key}"

    with FastDash(callback_fn=echo, mcp_server=True).mcp_test_client() as app:
        seen = []
        app.invoke(inputs={"key": "hunter2-secret", "n": 2}, on_progress=seen.append)
        assert len(seen) == 2
        assert "hunter2-secret" not in json.dumps(seen)


def test_a_long_frame_keeps_its_newest_text():
    def big(n: int = 1) -> str:
        """One huge frame."""
        yield "a" * 5000 + "END"

    with FastDash(callback_fn=big, mcp_server=True).mcp_test_client() as app:
        seen = []
        app.invoke(on_progress=seen.append)
        assert len(seen[0]) == PROGRESS_MESSAGE_MAX_CHARS
        assert seen[0].startswith("...") and seen[0].endswith("END")


def test_progress_is_live_over_the_wire():
    fd = FastDash(callback_fn=slow_count, stream=True, mcp_server=True)
    srv = make_server("127.0.0.1", 0, fd.app.server, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with connect(f"http://127.0.0.1:{srv.server_port}/mcp") as app:
            arrivals = []
            t0 = time.time()
            run = app.invoke(inputs={"n": 3},
                             on_progress=lambda m: arrivals.append((time.time() - t0, m)))
            total = time.time() - t0
        assert [m for _, m in arrivals] == FRAMES
        # The first frame came well before the run ended: streamed, not buffered.
        assert arrivals[0][0] < total - 0.4
        assert run["outputs"] == {"output_output_1": FRAMES[-1]}
    finally:
        srv.shutdown()
