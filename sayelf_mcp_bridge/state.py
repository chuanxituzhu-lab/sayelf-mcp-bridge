"""Ledger and backups.

The ledger records which host entries this tool wrote (and their canonical
content), so it only ever changes or removes entries it owns. Every config
write is preceded by a timestamped backup; ``rollback`` restores the newest.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


def home() -> Path:
    return Path(os.environ.get("SAYELF_MCP_BRIDGE_HOME") or Path.home() / ".sayelf" / "mcp-bridge")


def digest(entry: dict) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self, root: Path | None = None):
        self.root = root or home()
        self.path = self.root / "ledger.json"

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def owned(self, host: str, name: str) -> dict | None:
        return self._read().get(host, {}).get(name)

    def record(self, host: str, name: str, entry: dict, location: str) -> None:
        data = self._read()
        data.setdefault(host, {})[name] = {
            "digest": digest(entry), "location": location,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._write(data)

    def forget(self, host: str, name: str) -> None:
        data = self._read()
        data.get(host, {}).pop(name, None)
        self._write(data)

    def all(self) -> dict:
        return self._read()


def backup(path: Path, host: str, root: Path | None = None) -> Path | None:
    """Copy ``path`` aside before a write. Returns the backup path (None if the file did not exist)."""
    if not path.exists():
        return None
    folder = (root or home()) / "backups" / host
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = folder / f"{stamp}__{path.name}"
    shutil.copy2(path, target)
    (folder / f"{stamp}__{path.name}.origin").write_text(str(path), encoding="utf-8")
    return target


def latest_backup(host: str, root: Path | None = None) -> tuple[Path, Path] | None:
    folder = (root or home()) / "backups" / host
    if not folder.is_dir():
        return None
    copies = sorted(p for p in folder.iterdir() if not p.name.endswith(".origin"))
    if not copies:
        return None
    newest = copies[-1]
    origin = Path((folder / f"{newest.name}.origin").read_text(encoding="utf-8"))
    return newest, origin


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".sayelf-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
