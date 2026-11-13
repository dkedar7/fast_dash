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


def doctor_stream(url, as_json=False, timeout=30.0):
    """Check that a running ``stream=True`` app really streams to a client (#352).

    Connects on the app's own transport (socket.io on Flask, the native
    WebSocket on ``backend="fastapi"``), presses Run once and exits 0 when
    updates arrive while the Run is still in flight; 1 otherwise.
    """
    import json

    from fast_dash.stream_check import check_stream, print_report

    ok, report = check_stream(url, timeout=timeout)
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(ok, report)
    return 0 if ok else 1


def doctor_mcp(url, as_json=False, timeout=30.0):
    """Smoke-test the MCP surface of the app running at ``url`` (#341).

    Exits 0 when an MCP client can initialize, list the Fast Dash tools and
    read a well-formed ``describe_app`` contract; 1 otherwise, so it works as
    a container HEALTHCHECK or a CI step.
    """
    import json

    from fast_dash.mcp_check import check_mcp, print_report

    ok, report = check_mcp(url, timeout=timeout)
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(ok, report)
    return 0 if ok else 1


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
             "/ --stream a running app's MCP surface or streaming",
    )
    doctor_parser.add_argument(
        "--mcp",
        metavar="URL",
        help="Connect to a running app's MCP endpoint (e.g. "
             "http://127.0.0.1:8080/mcp) as an MCP client and check it. "
             "Needs the mcp package.",
    )
    doctor_parser.add_argument(
        "--stream",
        metavar="URL",
        help="Connect to a running stream=True app (e.g. http://127.0.0.1:8080/) "
             "the way the page does, press Run once, and check that updates "
             "arrive while it runs. Runs the app's function once.",
    )
    doctor_parser.add_argument(
        "--json", action="store_true",
        help="With --mcp or --stream: print the full report as JSON",
    )
    doctor_parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="With --mcp or --stream: seconds to wait for the whole check (default: 30)",
    )

    # Parse arguments
    args = parser.parse_args()

    if args.command == "doctor":
        if args.mcp and args.stream:
            parser.error("pass --mcp or --stream, not both")
        if args.mcp:
            return doctor_mcp(args.mcp, as_json=args.json, timeout=args.timeout)
        if args.stream:
            return doctor_stream(args.stream, as_json=args.json, timeout=args.timeout)
        if args.json:
            parser.error("--json needs --mcp or --stream")
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