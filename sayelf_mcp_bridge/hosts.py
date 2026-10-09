"""Host adapters: where and how each agent host registers a stdio MCP server.

Every adapter cites its evidence. ``official`` = the host's own docs;
``local`` = observed in the host's own config on this machine, docs silent;
``none`` = no local MCP path known — the adapter explains instead of writing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import state
from .manifest import Server

BRIDGE_ROOT = str(Path(__file__).resolve().parents[1])


class HostError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code, self.detail = code, detail
        super().__init__(f"{code}{': ' + detail if detail else ''}")


def _home() -> Path:
    return Path(os.environ.get("SAYELF_MCP_BRIDGE_USERHOME") or Path.home())


def launcher_entry(server: Server) -> tuple[str, list[str], dict[str, str]]:
    """Wrap a server whose host has no ``cwd`` field in the bridge launcher."""
    if not server.cwd:
        return server.command, list(server.args), dict(server.env)
    env = dict(server.env)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (BRIDGE_ROOT, env.get("PYTHONPATH", "")) if p)
    return sys.executable, ["-m", "sayelf_mcp_bridge.launch", "--cwd", server.cwd, "--",
                            server.command, *server.args], env


@dataclass
class Host:
    id: str
    label: str
    evidence: str            # official | local | none
    source: str              # doc URL or local observation
    note: str = ""

    def detect(self) -> tuple[bool, str]:
        raise NotImplementedError

    def location(self) -> str:
        return ""

    def native_entry(self, server: Server) -> dict:
        raise NotImplementedError

    def current(self, name: str) -> dict | None:
        raise NotImplementedError

    def write(self, server: Server, ledger: state.Ledger, force: bool = False) -> dict:
        raise NotImplementedError

    def remove(self, name: str, ledger: state.Ledger, force: bool = False) -> dict:
        raise NotImplementedError

    # Ownership: change or remove only entries this tool wrote and nobody edited since.
    def _check_owned(self, name: str, existing: dict | None, ledger: state.Ledger, force: bool) -> None:
        if existing is None or force:
            return
        owned = ledger.owned(self.id, name)
        if owned is None:
            raise HostError("CONFLICT_UNOWNED", f"{self.id} already has '{name}' that this tool did not write; use --force to replace (backed up)")
        if owned["digest"] != state.digest(existing):
            raise HostError("DRIFT", f"'{name}' in {self.id} was edited by hand since install; use --force to overwrite (backed up)")


# --------------------------------------------------------------------------- JSON hosts
def _strip_jsonc(text: str) -> tuple[str, bool]:
    """Remove // and /* */ comments outside strings. Returns (text, had_comments)."""
    out, i, had, in_str = [], 0, False, False
    while i < len(text):
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < len(text):
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True; out.append(c)
        elif text.startswith("//", i):
            had = True
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            had = True
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out)), had


@dataclass
class JsonHost(Host):
    candidates: tuple[str, ...] = ()       # relative to home; first existing is the live file
    detect_paths: tuple[str, ...] = ()
    detect_commands: tuple[str, ...] = ()
    with_type: bool = True
    supports_cwd: bool = False

    def path(self) -> Path:
        home = _home()
        for rel in self.candidates:
            if (home / rel).exists():
                return home / rel
        return home / self.candidates[0]

    def location(self) -> str:
        return str(self.path())

    def detect(self) -> tuple[bool, str]:
        home = _home()
        for rel in self.detect_paths:
            if (home / rel).exists():
                return True, str(home / rel)
        for cmd in self.detect_commands:
            found = shutil.which(cmd)
            if found:
                return True, found
        return False, ""

    def native_entry(self, server: Server) -> dict:
        if self.supports_cwd:
            command, args, env = server.command, list(server.args), dict(server.env)
        else:
            command, args, env = launcher_entry(server)
        entry: dict = {"type": "stdio"} if self.with_type else {}
        entry.update({"command": command, "args": args})
        if self.supports_cwd and server.cwd:
            entry["cwd"] = server.cwd
        if env:
            entry["env"] = env
        return entry

    def _load(self) -> tuple[dict, bool]:
        path = self.path()
        if not path.exists():
            return {}, False
        raw = path.read_text(encoding="utf-8-sig")
        if not raw.strip():
            return {}, False
        cleaned, had_comments = _strip_jsonc(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            raise HostError("HOST_FILE_INVALID", str(path)) from None
        if not isinstance(data, dict):
            raise HostError("HOST_FILE_INVALID", str(path))
        return data, had_comments

    def current(self, name: str) -> dict | None:
        data, _ = self._load()
        servers = data.get("mcpServers") or {}
        return servers.get(name) if isinstance(servers, dict) else None

    def _save(self, data: dict, had_comments: bool, force: bool) -> str:
        path = self.path()
        if had_comments and not force:
            # Rewriting would drop the user's comments; never do that silently.
            raise HostError("HOST_FILE_HAS_COMMENTS", f"{path}: add the entry by hand or use --force (comments are lost, file backed up)")
        backup = state.backup(path, self.id)
        state.atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return str(backup) if backup else ""

    def write(self, server: Server, ledger: state.Ledger, force: bool = False) -> dict:
        data, had_comments = self._load()
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise HostError("HOST_FILE_INVALID", "mcpServers is not an object")
        self._check_owned(server.name, servers.get(server.name), ledger, force)
        entry = self.native_entry(server)
        if servers.get(server.name) == entry:
            ledger.record(self.id, server.name, entry, str(self.path()))
            return {"changed": False, "path": str(self.path())}
        servers[server.name] = entry
        backup = self._save(data, had_comments, force)
        ledger.record(self.id, server.name, entry, str(self.path()))
        return {"changed": True, "path": str(self.path()), "backup": backup}

    def remove(self, name: str, ledger: state.Ledger, force: bool = False) -> dict:
        data, had_comments = self._load()
        servers = data.get("mcpServers") or {}
        if name not in servers:
            ledger.forget(self.id, name)
            return {"changed": False, "path": str(self.path())}
        self._check_owned(name, servers[name], ledger, force)
        del servers[name]
        backup = self._save(data, had_comments, force)
        ledger.forget(self.id, name)
        return {"changed": True, "path": str(self.path()), "backup": backup}


# --------------------------------------------------------------------------- Codex (TOML)
def _toml_str(value: str) -> str:
    if "'" not in value and "\n" not in value:
        return f"'{value}'"
    return json.dumps(value, ensure_ascii=False)  # JSON string escapes are valid TOML basic strings


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key)


@dataclass
class CodexHost(Host):
    def path(self) -> Path:
        base = os.environ.get("CODEX_HOME")
        return Path(base) / "config.toml" if base else _home() / ".codex" / "config.toml"

    def location(self) -> str:
        return str(self.path())

    def detect(self) -> tuple[bool, str]:
        if self.path().exists():
            return True, str(self.path())
        found = shutil.which("codex")
        return (True, found) if found else (False, "")

    def native_entry(self, server: Server) -> dict:
        entry = {"command": server.command, "args": list(server.args)}
        if server.cwd:
            entry["cwd"] = server.cwd
        if server.env:
            entry["env"] = dict(server.env)
        return entry

    @staticmethod
    def _marks(name: str) -> tuple[str, str]:
        return f"# >>> sayelf-mcp-bridge: {name} >>>", f"# <<< sayelf-mcp-bridge: {name} <<<"

    def _text(self) -> str:
        path = self.path()
        return path.read_text(encoding="utf-8-sig") if path.exists() else ""

    @staticmethod
    def _parse(text: str) -> dict:
        import tomllib
        try:
            return tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            raise HostError("HOST_FILE_INVALID", "config.toml does not parse") from None

    def current(self, name: str) -> dict | None:
        return (self._parse(self._text()).get("mcp_servers") or {}).get(name)

    def _render(self, server: Server) -> str:
        start, end = self._marks(server.name)
        lines = [start, f"[mcp_servers.{_toml_key(server.name)}]",
                 f"command = {_toml_str(server.command)}",
                 "args = [" + ", ".join(_toml_str(a) for a in server.args) + "]"]
        if server.cwd:
            lines.append(f"cwd = {_toml_str(server.cwd)}")
        lines.append("startup_timeout_sec = 60")
        if server.env:
            lines.append(f"[mcp_servers.{_toml_key(server.name)}.env]")
            lines += [f"{_toml_key(k)} = {_toml_str(v)}" for k, v in server.env.items()]
        lines.append(end)
        return "\n".join(lines) + "\n"

    def _without(self, text: str, name: str, force: bool) -> tuple[str, bool]:
        """Drop our marked block; with ``force`` also drop an unmarked table of that name."""
        start, end = self._marks(name)
        if start in text and end in text:
            a, b = text.index(start), text.index(end) + len(end)
            return (text[:a].rstrip("\n") + "\n" + text[b:].lstrip("\n")).lstrip("\n"), True
        if not force:
            return text, False
        out, skipping, removed = [], False, False
        header = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")
        prefix = f"mcp_servers.{name}"
        for line in text.splitlines(keepends=True):
            m = header.match(line)
            if m:
                table = m.group(1).replace('"', "").replace("'", "")
                skipping = table == prefix or table.startswith(prefix + ".")
                removed = removed or skipping
            if not skipping:
                out.append(line)
        return "".join(out), removed

    def write(self, server: Server, ledger: state.Ledger, force: bool = False) -> dict:
        text = self._text()
        before = self._parse(text)
        existing = (before.get("mcp_servers") or {}).get(server.name)
        if existing is not None:
            existing = {k: v for k, v in existing.items() if k != "startup_timeout_sec"}
        self._check_owned(server.name, existing, ledger, force)
        entry = self.native_entry(server)
        if existing == entry and self._marks(server.name)[0] in text:
            ledger.record(self.id, server.name, entry, str(self.path()))
            return {"changed": False, "path": str(self.path())}
        stripped, _ = self._without(text, server.name, force=True if existing is not None else force)
        new_text = stripped.rstrip("\n") + ("\n\n" if stripped.strip() else "") + self._render(server)
        after = self._parse(new_text)  # never write a file that would not parse
        if {k: v for k, v in after["mcp_servers"][server.name].items() if k != "startup_timeout_sec"} != entry:
            raise HostError("RENDER_MISMATCH", server.name)
        backup = state.backup(self.path(), self.id)
        state.atomic_write(self.path(), new_text)
        ledger.record(self.id, server.name, entry, str(self.path()))
        return {"changed": True, "path": str(self.path()), "backup": str(backup) if backup else ""}

    def remove(self, name: str, ledger: state.Ledger, force: bool = False) -> dict:
        text = self._text()
        existing = (self._parse(text).get("mcp_servers") or {}).get(name)
        if existing is None:
            ledger.forget(self.id, name)
            return {"changed": False, "path": str(self.path())}
        self._check_owned(name, {k: v for k, v in existing.items() if k != "startup_timeout_sec"}, ledger, force)
        new_text, removed = self._without(text, name, force=True)
        self._parse(new_text)
        backup = state.backup(self.path(), self.id)
        state.atomic_write(self.path(), new_text)
        ledger.forget(self.id, name)
        return {"changed": removed, "path": str(self.path()), "backup": str(backup) if backup else ""}


# --------------------------------------------------------------------------- Claude Code (CLI)
@dataclass
class ClaudeCodeHost(Host):
    runner: object = field(default=None, repr=False)   # injectable for tests

    def _claude(self) -> str | None:
        return shutil.which("claude")

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        if self.runner is not None:
            return self.runner(args)
        exe = self._claude()
        if not exe:
            raise HostError("HOST_CLI_MISSING", "claude")
        return subprocess.run([exe, *args], capture_output=True, text=True, timeout=60)

    def location(self) -> str:
        return "claude mcp (user scope, ~/.claude.json)"

    def detect(self) -> tuple[bool, str]:
        if self.runner is not None:
            return True, "test-runner"
        found = self._claude()
        return (True, found) if found else (False, "")

    def native_entry(self, server: Server) -> dict:
        command, args, env = launcher_entry(server)
        return {"command": command, "args": args, **({"env": env} if env else {})}

    def current(self, name: str) -> dict | None:
        result = self._run(["mcp", "get", name])
        return {"present": True} if result.returncode == 0 else None

    def _owned_ok(self, name: str, ledger: state.Ledger, force: bool) -> None:
        # The CLI does not return a stable structured entry, so ownership is the ledger alone.
        if self.current(name) is not None and ledger.owned(self.id, name) is None and not force:
            raise HostError("CONFLICT_UNOWNED", f"claude already has '{name}' that this tool did not write; use --force to replace")

    def write(self, server: Server, ledger: state.Ledger, force: bool = False) -> dict:
        self._owned_ok(server.name, ledger, force)
        entry = self.native_entry(server)
        owned = ledger.owned(self.id, server.name)
        if owned and owned["digest"] == state.digest(entry) and self.current(server.name) is not None:
            return {"changed": False, "path": self.location()}
        backup = state.backup(_home() / ".claude.json", self.id)
        if self.current(server.name) is not None:
            self._run(["mcp", "remove", server.name, "--scope", "user"])
        args = ["mcp", "add"]
        if entry.get("env"):
            args += ["--env", *[f"{k}={v}" for k, v in entry["env"].items()]]
        args += ["--transport", "stdio", "--scope", "user", server.name, "--", entry["command"], *entry["args"]]
        result = self._run(args)
        if result.returncode != 0:
            raise HostError("HOST_CLI_FAILED", (result.stderr or result.stdout or "")[-400:])
        ledger.record(self.id, server.name, entry, self.location())
        return {"changed": True, "path": self.location(), "backup": str(backup) if backup else ""}

    def remove(self, name: str, ledger: state.Ledger, force: bool = False) -> dict:
        if self.current(name) is None:
            ledger.forget(self.id, name)
            return {"changed": False, "path": self.location()}
        if ledger.owned(self.id, name) is None and not force:
            raise HostError("CONFLICT_UNOWNED", f"claude has '{name}' that this tool did not write")
        backup = state.backup(_home() / ".claude.json", self.id)
        result = self._run(["mcp", "remove", name, "--scope", "user"])
        if result.returncode != 0:
            raise HostError("HOST_CLI_FAILED", (result.stderr or result.stdout or "")[-400:])
        ledger.forget(self.id, name)
        return {"changed": True, "path": self.location(), "backup": str(backup) if backup else ""}


# --------------------------------------------------------------------------- hosts without a local path
@dataclass
class NoLocalHost(Host):
    def detect(self) -> tuple[bool, str]:
        return False, ""

    def location(self) -> str:
        return "—"

    def _refuse(self, *_a, **_k):
        raise HostError("HOST_NOT_SUPPORTED", self.note)

    native_entry = current = write = remove = _refuse


def registry() -> list[Host]:
    return [
        ClaudeCodeHost("claude-code", "Claude Code", "official",
                       "https://code.claude.com/docs/en/mcp",
                       note="通过官方 CLI `claude mcp add --scope user` 登记；无 cwd 字段，用启动器补齐。"),
        CodexHost("codex", "OpenAI Codex", "official",
                  "Codex config.toml [mcp_servers.<name>]（与本机现有 cad-hub 等条目同格式）",
                  note="写入 CODEX_HOME/config.toml，区块带标记，写前写后均做 TOML 解析校验。"),
        JsonHost("cursor", "Cursor", "official", "https://cursor.com/docs/mcp",
                 note="~/.cursor/mcp.json；文档未列 cwd 字段，用启动器补齐。",
                 candidates=(".cursor/mcp.json",), detect_paths=(".cursor",), with_type=True),
        JsonHost("codebuddy", "CodeBuddy", "official", "https://www.workbuddy.ai/docs/cli/mcp",
                 note="用户级取第一个已存在的 ~/.codebuddy/.mcp.json → mcp.json；支持 JSONC。",
                 candidates=(".codebuddy/.mcp.json", ".codebuddy/mcp.json"),
                 detect_paths=(".codebuddy",), detect_commands=("codebuddy",), with_type=True),
        JsonHost("workbuddy", "WorkBuddy", "local",
                 "本机 ~/.workbuddy/.mcp.json 已有 mcpServers 条目（与 CodeBuddy 同结构）；官方页面只写了界面添加远程服务",
                 note="依据本机实证写入；首次接入后请在 WorkBuddy 设置 → MCP 中确认已出现。",
                 candidates=(".workbuddy/.mcp.json",), detect_paths=(".workbuddy",), with_type=True),
        JsonHost("qwen-code", "Qwen Code（千问命令行）", "official",
                 "https://qwenlm.github.io/qwen-code-docs/en/developers/tools/mcp-server/",
                 note="~/.qwen/settings.json 的 mcpServers，原生支持 cwd；只改 mcpServers，其他设置原样保留。",
                 candidates=(".qwen/settings.json",), detect_paths=(".qwen",), detect_commands=("qwen",),
                 with_type=False, supports_cwd=True),
        NoLocalHost("qianwen-desktop", "千问桌面版", "none", "本机 ~/Qianwen 与 ~/.qwen-agent 中未发现 MCP 配置",
                    note="未发现本机 MCP 接入方式；改用 Qwen Code，或等 HTTP 入口。"),
        NoLocalHost("doubao", "豆包", "none", "未找到官方本机 MCP 接入说明",
                    note="消费级应用，暂无已知的本机 stdio MCP 接入；等 HTTP 入口（需鉴权）。"),
        NoLocalHost("openclaw", "太一 / OpenClaw", "none",
                    "https://docs.openclaw.ai/gateway/configuration-reference（MCP 配置移至 config-extensions，格式待核实）",
                    note="官方文档确认支持 MCP，但具体键名与格式未核实；在太一所在机器运行 `openclaw config schema` 后补适配器。"),
    ]


def get(host_id: str) -> Host:
    for host in registry():
        if host.id == host_id:
            return host
    raise HostError("UNKNOWN_HOST", host_id)
