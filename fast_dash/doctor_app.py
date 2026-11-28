"""``fastdash doctor --app TARGET``: boot an app, check its MCP surface, stop it (#395).

The parent (``AppProcess``) picks a free loopback port and starts the app as a
child process with ``python -m fast_dash.doctor_app``. That child bootstrap
(``main``) wraps ``FastDash.run``/``DynamicDash.run`` so whatever ``run()``
the app calls serves on that port and host, without the reloader, and then
runs the target:

- ``app.py``: the script, as ``python app.py`` would (``__name__ == "__main__"``).
- ``app.py:app``: the script as a module, then ``app.run()``.
- ``mypkg.server:app``: ``import mypkg.server``, then ``app.run()``.

Booting in a child keeps the app's server, and Dash's process-wide MCP
registry, out of doctor's own process. No new library API is involved: the
app runs exactly as its own ``run()`` would, only on doctor's port.
"""

import os
import socket
import subprocess
import sys
import tempfile

LOOPBACK = "127.0.0.1"
LOG_TAIL_LINES = 15


def parse_target(target):
    """``(kind, path_or_module, attr)`` for ``--app``; raises ``ValueError``."""
    head, sep, attr = target.rpartition(":")
    is_attr = sep and head and all(p.isidentifier() for p in attr.split("."))
    if is_attr and not (len(head) == 1 and head.isalpha()):     # not a bare drive "C:"
        if os.path.isfile(head):
            return "file", head, attr
        if head.endswith(".py"):
            raise ValueError(f"--app: no such file: {head}")
        if all(p.isidentifier() for p in head.split(".")):
            return "module", head, attr
    if os.path.isfile(target):
        return "file", target, None
    if target.endswith(".py"):
        raise ValueError(f"--app: no such file: {target}")
    raise ValueError(
        "--app takes a script (app.py), a script and its app object "
        f"(app.py:app) or a module and its app object (mypkg.server:app); got {target!r}"
    )


def free_port():
    with socket.socket() as s:
        s.bind((LOOPBACK, 0))
        return s.getsockname()[1]


class AppProcess:
    """The app under test, as a child process; a context manager that always stops it."""

    def __init__(self, target, port=None):
        self.target = target
        self.kind, self.where, self.attr = parse_target(target)
        self.port = port or free_port()
        self.url = f"http://{LOOPBACK}:{self.port}/mcp"
        self.proc = None
        self._log = None

    def __enter__(self):
        self._log = tempfile.TemporaryFile()
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "fast_dash.doctor_app",
             self.kind, self.where, self.attr or "", str(self.port)],
            stdin=subprocess.DEVNULL, stdout=self._log, stderr=subprocess.STDOUT,
            env=env,
        )
        return self

    def __exit__(self, *exc):
        self.stop()
        if self._log is not None:
            self._log.close()
            self._log = None
        return False

    def stop(self):
        """Terminate the child if it is still running; True if it had to be."""
        if self.proc is None or self.proc.poll() is not None:
            return False
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        return True

    def log_tail(self, n=LOG_TAIL_LINES):
        """The child's last ``n`` output lines, ASCII-safe for any console."""
        if self._log is None:
            return []
        self._log.flush()
        self._log.seek(0)
        text = self._log.read().decode("utf-8", "replace")
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        return [ln.encode("ascii", "backslashreplace").decode("ascii") for ln in lines[-n:]]

    def died(self):
        """Why the app can't come up any more (it exited), else None.

        Passed to ``check_mcp(give_up=)`` so a crashed app ends the wait at
        once with its exit code and output, instead of a bare "connection
        refused" after the whole window.
        """
        code = self.proc.poll() if self.proc else None
        if code is None:
            return None
        msg = f"the app exited with code {code} before /mcp answered"
        if code == 0:
            msg += (". Does it call .run() (for example under if __name__ == "
                    "'__main__')? If it only defines the app, name it: --app "
                    f"{self.where}:app")
        tail = self.log_tail()
        if tail:
            msg += ". Its last output:\n" + "\n".join(f"    {ln}" for ln in tail)
        return msg

    def info(self):
        """For the report. ``running`` is the state when the check ended; a
        running app is stopped right after."""
        code = self.proc.poll() if self.proc else None
        return {"target": self.target, "url": self.url, "port": self.port,
                "pid": self.proc.pid if self.proc else None,
                "exit_code": code, "running": self.proc is not None and code is None}


# --- the child side ---------------------------------------------------------

def _pin_run(cls, port):
    """Make ``cls.run`` serve on ``port`` at loopback, without the reloader."""
    import inspect

    orig = cls.run
    params = inspect.signature(orig).parameters
    names = [n for n, p in params.items()
             if n != "self" and p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD]

    def run(self, *args, **kwargs):
        kwargs.update(zip(names, args))
        kwargs.update(port=port, host=LOOPBACK, use_reloader=False)
        return orig(self, **kwargs)

    cls.run = run


def _user_traceback(e):
    """Print ``e`` from the app's first frame on, without this bootstrap's frames."""
    import traceback

    tb = e.__traceback__
    while tb is not None and (tb.tb_frame.f_code.co_filename == __file__
                              or "runpy" in tb.tb_frame.f_code.co_filename):
        tb = tb.tb_next
    traceback.print_exception(type(e), e, tb or e.__traceback__)


def main(argv=None):
    try:
        return _main(argv)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:                       # noqa: BLE001
        _user_traceback(e)
        return 1


def _main(argv=None):
    import importlib
    import runpy

    kind, where, attr, port = (argv or sys.argv[1:])[:4]
    port = int(port)
    from fast_dash import FastDash
    from fast_dash.dynamic import DynamicDash

    _pin_run(FastDash, port)
    _pin_run(DynamicDash, port)

    if kind == "file":
        path = os.path.abspath(where)
        sys.argv = [path]
        sys.path[0] = os.path.dirname(path)          # as `python app.py` would
        namespace = runpy.run_path(path, run_name="__main__" if not attr else "__fastdash_app__")
        if not attr:
            return 0
        obj = namespace
        first, *rest = attr.split(".")
        if first not in obj:
            print(f"fastdash doctor --app: {where} defines no {first!r}", file=sys.stderr)
            return 2
        obj = obj[first]
    else:
        if "" not in sys.path and os.getcwd() not in sys.path:
            sys.path.insert(0, os.getcwd())
        obj = importlib.import_module(where)
        rest = attr.split(".")
    for name in rest:
        obj = getattr(obj, name)
    if not hasattr(obj, "run"):
        print(f"fastdash doctor --app: {attr} is a {type(obj).__name__}, "
              "not an app with .run()", file=sys.stderr)
        return 2
    obj.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
