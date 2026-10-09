"""Tiny launcher that gives a working directory to hosts whose MCP config has
no ``cwd`` field: ``python -m sayelf_mcp_bridge.launch --cwd DIR -- CMD ARGS``.
stdin/stdout/stderr are inherited, so the MCP stdio stream passes through.
"""
from __future__ import annotations

import os
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 4 or argv[0] != "--cwd" or argv[2] != "--":
        print("usage: python -m sayelf_mcp_bridge.launch --cwd DIR -- CMD [ARGS...]", file=sys.stderr)
        return 2
    cwd, command = argv[1], argv[3:]
    if not os.path.isdir(cwd):
        print(f"sayelf-mcp-bridge: cwd not found: {cwd}", file=sys.stderr)
        return 2
    try:
        return subprocess.call(command, cwd=cwd)
    except FileNotFoundError:
        print(f"sayelf-mcp-bridge: command not found: {command[0]}", file=sys.stderr)
        return 127
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
