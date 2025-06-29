# fast_dash/cli.py

import os
import sys
import argparse
from pathlib import Path

def create_project(project_name, port=8080):
    """
    Create a new project folder with required files:
    - Dockerfile
    - requirements.txt
    - app.py with FastDash import
    """
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
    dockerfile_content = f"""FROM python:3.13-slim
ADD . /app
WORKDIR /app
RUN pip install --no-cache-dir -r requirements.txt
CMD gunicorn app:server --bind :${{PORT:-{port}}}
"""
    
    with open(project_dir / "Dockerfile", "w") as f:
        f.write(dockerfile_content)
    print(f"Created Dockerfile: {project_name}/Dockerfile")
    
    # Create empty requirements.txt
    with open(project_dir / "requirements.txt", "w") as f:
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
        f.write(f"app = FastDash(simple_text_to_text, port={port})\n\n")
        f.write("server = app.server\n\n")
        f.write("if __name__ == '__main__':\n")
        f.write("    app.run()\n")
    print(f"Created app.py: {project_name}/app.py")
    
    print(f"\nProject '{project_name}' created successfully!")
    print(f"To get started, run:\n  cd {project_name}\n  pip install -r requirements.txt")
    
    return 0

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
    
    # Parse arguments
    args = parser.parse_args()

    while args.port is None:
        port_input = input("Enter a port number (8080 for Google Cloud Run and 7860 for HuggingFace Spaces). Leave blank to use 8080.\n")
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

    if args.port is None:
        args.port = 8080
    
    # Handle commands
    if args.command == "create":
        return create_project(args.project_name, port=args.port)
    else:
        parser.print_help()
        return 1

if __name__ == "__main__":
    sys.exit(main())