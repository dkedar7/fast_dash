# fast_dash/cli.py

import os
import sys
import argparse
from pathlib import Path

def create_project(project_name, port=8080, backend="flask"):
    """
    Create a new project folder with required files:
    - Dockerfile
    - requirements.txt
    - app.py with FastDash import

    ``backend="fastapi"`` scaffolds an ASGI app served by uvicorn, which
    streams ``stream=True`` and ``chat=`` updates in production; the default
    Flask app under plain gunicorn can't (#333).
    """
    fastapi = backend == "fastapi"
    # Create project directory
    project_dir = Path(os.getcwd()) / project_name
    
    # Check if directory already exists
    if project_dir.exists():
        print(f"Error: Project directory '{project_name}' already exists.")
        return 1
    
    # Create the directory
    project_dir.mkdir()
    print(f"Created project directory: {project_name}/")
    
    # Create Dockerfile
    serve = (
        f"uvicorn app:server --host 0.0.0.0 --port ${{PORT:-{port}}}" if fastapi
        else f"gunicorn app:server --bind :${{PORT:-{port}}}"
    )
    dockerfile_content = f"""FROM python:3.13-slim
ADD . /app
WORKDIR /app
RUN pip install --no-cache-dir -r requirements.txt
CMD {serve}
"""
    
    with open(project_dir / "Dockerfile", "w") as f:
        f.write(dockerfile_content)
    print(f"Created Dockerfile: {project_name}/Dockerfile")
    
    # Create empty requirements.txt
    with open(project_dir / "requirements.txt", "w") as f:
        if fastapi:
            f.write("fast-dash[fastapi]\n")      # brings fastapi and uvicorn
        else:
            f.write("fast-dash\n")
            f.write("gunicorn\n")
    print(f"Created requirements.txt: {project_name}/requirements.txt")
    
    # Create app.py with FastDash import
    with open(project_dir / "app.py", "w") as f:
        f.write("from fast_dash import FastDash\n\n")
        f.write("# Write the main callback function here\n")
        f.write("def simple_text_to_text(input_text: str) -> str:\n")
        f.write("    return input_text\n\n\n")
        f.write("# Initialize your FastDash application here\n")
        extra = ', backend="fastapi"' if fastapi else ""
        f.write(f"app = FastDash(simple_text_to_text, port={port}{extra})\n\n")
        f.write("server = app.server\n\n")
        f.write("if __name__ == '__main__':\n")
        f.write("    app.run()\n")
    print(f"Created app.py: {project_name}/app.py")
    
    print(f"\nProject '{project_name}' created successfully!")
    print(f"To get started, run:\n  cd {project_name}\n  pip install -r requirements.txt")
    
    return 0

def doctor():
    """Print the versions a Fast Dash web UI depends on, and any known clash.

    A blank page with no server error is usually a dash-mantine-components /
    React mismatch (#318); this names it.
    """
    from importlib.metadata import PackageNotFoundError, version

    from fast_dash.utils import _served_react_version, react_mismatch

    import fast_dash

    print(f"{'fast-dash':28} {fast_dash.__version__}")
    for pkg in ("dash", "dash-mantine-components", "dash-bootstrap-components"):
        try:
            v = version(pkg)
        except PackageNotFoundError:
            v = "not installed"
        print(f"{pkg:28} {v}")
    print(f"{'React (served by Dash)':28} {_served_react_version() or 'unknown'}")

    problem = react_mismatch()
    if problem:
        print(f"\nProblem: {problem}")
        return 1
    print("\nNo known version conflicts.")
    return 0


def _parse_invoke_inputs(pairs):
    """``["n=7", "label=hi"]`` as ``{"n": 7, "label": "hi"}``: JSON if it parses, else text."""
    import json

    inputs = {}
    for pair in pairs or []:
        name, sep, raw = pair.partition("=")
        if not sep or not name:
            raise ValueError(f"--invoke-input takes NAME=VALUE, got {pair!r}")
        try:
            inputs[name] = json.loads(raw)
        except ValueError:
            inputs[name] = raw
    return inputs


def doctor_mcp(url, as_json=False, timeout=30.0, invoke=False, invoke_inputs=None,
               config=None, write=False, config_path=None, force=False, wait=None):
    """Smoke-test the MCP surface of the app running at ``url`` (#341).

    Exits 0 when an MCP client can initialize, list the Fast Dash tools and
    read a well-formed ``describe_app`` contract; 1 otherwise, so it works as
    a container HEALTHCHECK or a CI step. ``invoke=True`` also runs the app
    once through ``invoke`` and requires it to succeed (#357). ``config``
    (``claude``, ``cursor``, ``vscode`` or ``all``) prints the client config
    for ``url`` after a healthy check (#383); ``write=True`` merges it into
    the client's config file instead, and exits 1 if that was refused (#389).
    ``wait`` (seconds) polls until an app that is still starting comes up,
    so the check works as a startup gate (#392).
    """
    import json
    import sys

    from fast_dash.mcp_check import check_mcp, print_report, wait_banner

    if wait and not as_json:
        print(wait_banner(url, wait))
        sys.stdout.flush()                      # visible in logs while polling
    ok, report = check_mcp(url, timeout=timeout, invoke=invoke,
                           invoke_inputs=invoke_inputs, config=config,
                           write=write, config_path=config_path, force=force,
                           wait=wait)
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(ok, report, header=not wait)
    return 0 if ok and "write_error" not in report else 1


def main():
    """Main entry point for the CLI"""
    parser = argparse.ArgumentParser(
        description="FastDash CLI - Tools for creating and managing FastDash projects"
    )
    
    # Create subparsers for different commands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Create command
    create_parser = subparsers.add_parser("create", help="Create a new FastDash project")
    create_parser.add_argument("project_name", help="Name of the project to create")
    create_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port number for the FastDash app (default: 8080)"
    )
    create_parser.add_argument(
        "--backend",
        choices=["flask", "fastapi"],
        default="flask",
        help="Server backend: flask (gunicorn, the default) or fastapi "
             "(uvicorn; needed to stream stream=True / chat= apps in production)",
    )
    
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check the installed versions for known conflicts, or with --mcp "
             "a running app's MCP surface",
    )
    doctor_parser.add_argument(
        "--mcp",
        metavar="URL",
        help="Connect to a running app's MCP endpoint (e.g. "
             "http://127.0.0.1:8080/mcp) as an MCP client and check it. "
             "Needs the mcp package.",
    )
    doctor_parser.add_argument(
        "--json", action="store_true",
        help="With --mcp: print the report, contract included, as JSON",
    )
    doctor_parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="With --mcp: seconds to wait for the whole check (default: 30); "
             "with --wait, for each attempt",
    )
    doctor_parser.add_argument(
        "--wait", type=float, nargs="?", const=30.0, default=None, metavar="SECONDS",
        help="With --mcp: if the app isn't up yet, keep retrying for up to "
             "SECONDS (default: 30) instead of failing at once",
    )
    doctor_parser.add_argument(
        "--invoke", action="store_true",
        help="With --mcp: also run the app once through the invoke tool, with "
             "its current values, and fail if that fails. Runs the real callback.",
    )
    doctor_parser.add_argument(
        "--invoke-input", action="append", metavar="NAME=VALUE", default=[],
        help="With --mcp: an input value for the --invoke run (implies "
             "--invoke; repeatable; VALUE is JSON if it parses, else text)",
    )
    doctor_parser.add_argument(
        "--config", choices=("claude", "cursor", "vscode", "all"), default=None,
        help="With --mcp: after a healthy check, print the paste-ready MCP "
             "client config for the URL (all = every client)",
    )
    doctor_parser.add_argument(
        "--write", action="store_true",
        help="With --config CLIENT: merge the server into that client's config "
             "file (.mcp.json, .cursor/mcp.json or .vscode/mcp.json), keeping "
             "the servers already there",
    )
    doctor_parser.add_argument(
        "--config-path", metavar="PATH", default=None,
        help="With --write: the config file to merge into instead",
    )
    doctor_parser.add_argument(
        "--force", action="store_true",
        help="With --write: replace an existing server of the same name",
    )

    # Parse arguments
    args = parser.parse_args()

    if args.command == "doctor":
        if (args.invoke or args.invoke_input) and not args.mcp:
            parser.error("--invoke needs --mcp")
        if args.config and not args.mcp:
            parser.error("--config needs --mcp")
        if args.wait is not None and not args.mcp:
            parser.error("--wait needs --mcp")
        if args.wait is not None and not args.wait > 0:
            parser.error("--wait takes a positive number of seconds")
        if args.write and not args.config:
            parser.error("--write needs --config CLIENT")
        if args.write and args.config == "all":
            parser.error("--write takes one client: --config claude, cursor or vscode")
        if (args.config_path or args.force) and not args.write:
            parser.error("--config-path and --force need --write")
        if args.mcp:
            try:
                invoke_inputs = _parse_invoke_inputs(args.invoke_input)
            except ValueError as e:
                parser.error(str(e))
            return doctor_mcp(args.mcp, as_json=args.json, timeout=args.timeout,
                              invoke=args.invoke or bool(invoke_inputs),
                              invoke_inputs=invoke_inputs, config=args.config,
                              write=args.write, config_path=args.config_path,
                              force=args.force, wait=args.wait)
        if args.json:
            parser.error("--json needs --mcp")
        return doctor()

    while args.command == "create" and args.port is None:
        try:
            port_input = input("Enter a port number (8080 for Google Cloud Run and 7860 for HuggingFace Spaces). Leave blank to use 8080.\n")
        except EOFError:
            # No one to answer (a Docker RUN, CI, `< /dev/null`): take the
            # default the prompt promises for a blank answer (#347).
            print("No input; using port 8080.")
            args.port = 8080
            break
        if port_input.strip() == "":
            args.port = 8080
        else:
            try:
                port = int(port_input)
                if 1 <= port <= 65535:
                    args.port = port
                else:
                    print("Please enter a valid port number between 1 and 65535.")
            except ValueError:
                print("Please enter a valid integer port number.")

    # Handle commands
    if args.command == "create":
        return create_project(args.project_name, port=args.port, backend=args.backend)
    else:
        parser.print_help()
        return 1

if __name__ == "__main__":
    sys.exit(main())