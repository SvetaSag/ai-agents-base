"""Tools for the agent — shared by notebooks 05–08.

`@tool(parse_docstring=True)` builds the JSON schema the model sees:
  * function name      → tool name
  * docstring summary  → tool description
  * type hints         → argument types
  * `Args:` section    → a description for every argument
So the docstring IS part of the prompt — write it for the model.
"""

import subprocess
from pathlib import Path

from langchain_core.tools import tool


@tool(parse_docstring=True)
def list_files(path: str = ".") -> str:
    """List files and folders in a directory.

    Args:
        path: Directory relative to the current directory, e.g. "src".
    """
    folder = Path(path)
    if not folder.is_dir():
        return f"Error: {path} is not a directory"
    names = sorted(
        entry.name + ("/" if entry.is_dir() else "")
        for entry in folder.iterdir()
        if not entry.name.startswith(".")  # skip .env, .venv, .git ...
    )
    return "\n".join(names) or "(empty)"


@tool(parse_docstring=True)
def read_file(path: str) -> str:
    """Read a text file and return its content (first 200 lines).

    Args:
        path: File path relative to the current directory, e.g. "src/app.py".
    """
    file = Path(path)
    if file.name.startswith(".env"):
        return "Error: access to secrets is not allowed"
    if not file.is_file():
        return f"Error: {path} is not a file"
    lines = file.read_text(errors="replace").splitlines()
    return "\n".join(lines[:200])


# ── tools that CHANGE things (used from notebook 08, need approval) ─────────

@tool(parse_docstring=True)
def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file.

    Args:
        path: File path relative to the current directory, e.g. "hello.py".
        content: The full new text of the file.
    """
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content)
    return f"Wrote {len(content)} chars to {path}"


@tool(parse_docstring=True)
def run_command(command: str) -> str:
    """Run a shell command and return its exit code and output.

    Args:
        command: The command line to run, e.g. "python hello.py".
    """
    try:
        result = subprocess.run(command, shell=True, capture_output=True,
                                text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 60s"
    return f"exit code: {result.returncode}\n{result.stdout[-3000:]}{result.stderr[-3000:]}"


# Tools that need a human "yes" before they run.
DANGEROUS = {"write_file", "run_command"}
