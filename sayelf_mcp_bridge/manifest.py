"""Server manifests: one JSON file per MCP server, the single source of truth.

{
  "name": "sayelf-agent-ops",
  "description": "...",
  "command": "{python}",
  "args": ["-m", "sayelf_agent_ops.mcp_server"],
  "cwd": "{skills_root}/sayelf-agent-ops",
  "env": {"SAYELF_OWNER": "human.owner"}
}

Placeholders expanded at install time: {python} (this interpreter),
{skills_root} (SAYELF_SKILLS_ROOT, default D:/Codex/skills on Windows,
~/.sayelf/skills elsewhere), {home}. Secrets do not belong in manifests:
reference them with ${VAR} and set them in the host or the OS environment.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
SECRET_HINT = re.compile(r"(key|token|secret|password)", re.I)


class ManifestError(ValueError):
    pass


def skills_root() -> str:
    if os.environ.get("SAYELF_SKILLS_ROOT"):
        return os.environ["SAYELF_SKILLS_ROOT"]
    return "D:/Codex/skills" if os.name == "nt" else str(Path.home() / ".sayelf" / "skills")


def _expand(value: str) -> str:
    out = value.replace("{python}", sys.executable).replace("{skills_root}", skills_root())
    out = out.replace("{home}", str(Path.home()))
    return os.path.normpath(out) if ("/" in out or "\\" in out) and not out.startswith("-") else out


@dataclass(frozen=True)
class Server:
    name: str
    command: str
    args: tuple[str, ...] = ()
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    description: str = ""

    def entry(self) -> dict:
        """Canonical stdio entry used for drift checks and the ledger."""
        data = {"command": self.command, "args": list(self.args)}
        if self.cwd:
            data["cwd"] = self.cwd
        if self.env:
            data["env"] = dict(self.env)
        return data


def parse(data: dict) -> Server:
    if not isinstance(data, dict):
        raise ManifestError("MANIFEST_NOT_OBJECT")
    name = data.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ManifestError("MANIFEST_BAD_NAME")
    command = data.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ManifestError("MANIFEST_NO_COMMAND")
    args = data.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ManifestError("MANIFEST_BAD_ARGS")
    env = data.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ManifestError("MANIFEST_BAD_ENV")
    for key, value in env.items():
        # Literal secrets would be copied into every host's config file in clear text.
        if SECRET_HINT.search(key) and value and not value.startswith("${"):
            raise ManifestError(f"MANIFEST_LITERAL_SECRET:{key}")
    cwd = data.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise ManifestError("MANIFEST_BAD_CWD")
    return Server(
        name=name,
        command=_expand(command),
        args=tuple(_expand(a) if "{" in a else a for a in args),
        cwd=_expand(cwd) if cwd else None,
        env={k: _expand(v) if "{" in v and not v.startswith("${") else v for k, v in env.items()},
        description=str(data.get("description", "")),
    )


def load(path: str | Path) -> Server:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"MANIFEST_UNREADABLE:{error.__class__.__name__}") from None
    return parse(data)


def find(name_or_path: str, servers_dir: Path) -> Server:
    candidate = Path(name_or_path)
    if candidate.suffix == ".json" and candidate.is_file():
        return load(candidate)
    path = servers_dir / f"{name_or_path}.json"
    if not path.is_file():
        raise ManifestError(f"MANIFEST_NOT_FOUND:{name_or_path}")
    return load(path)
