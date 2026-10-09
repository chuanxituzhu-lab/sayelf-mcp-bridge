"""sayelf-mcp-bridge CLI.

  python -m sayelf_mcp_bridge hosts
  python -m sayelf_mcp_bridge list
  python -m sayelf_mcp_bridge verify  <server>
  python -m sayelf_mcp_bridge plan    <server> [--hosts a,b]
  python -m sayelf_mcp_bridge install <server> [--hosts a,b] --yes [--force]
  python -m sayelf_mcp_bridge status  [<server>]
  python -m sayelf_mcp_bridge remove  <server> [--hosts a,b] --yes [--force]
  python -m sayelf_mcp_bridge rollback --host <id> --yes

Without --yes, install/remove only print the plan. Nothing is written to a host
that is not detected unless it is named explicitly in --hosts.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import hosts as H
from . import state
from .manifest import ManifestError, find
from .verify import handshake

REPO_SERVERS = Path(__file__).resolve().parents[1] / "servers"


def servers_dir() -> Path:
    user = state.home() / "servers"
    return user if user.is_dir() and any(user.glob("*.json")) else REPO_SERVERS


def _targets(selected: str | None) -> list[H.Host]:
    all_hosts = H.registry()
    if selected:
        wanted = [s.strip() for s in selected.split(",") if s.strip()]
        return [H.get(w) for w in wanted]
    return [h for h in all_hosts if h.evidence != "none" and h.detect()[0]]


def _print(data, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    for row in data if isinstance(data, list) else [data]:
        print("  ".join(f"{k}={v}" for k, v in row.items() if v not in (None, "", [], {})))


def cmd_hosts(args) -> int:
    rows = []
    for h in H.registry():
        present, where = h.detect()
        rows.append({"host": h.id, "name": h.label, "detected": present, "evidence": h.evidence,
                     "config": h.location(), "note": h.note, "source": h.source})
    if args.json:
        _print(rows, True)
    else:
        for r in rows:
            mark = "✓" if r["detected"] else ("—" if r["evidence"] == "none" else "·")
            print(f"{mark} {r['host']:<16} [{r['evidence']:<8}] {r['config']}\n    {r['note']}")
    return 0


def cmd_list(args) -> int:
    folder = servers_dir()
    rows = []
    for path in sorted(folder.glob("*.json")):
        try:
            s = find(str(path), folder)
            rows.append({"name": s.name, "command": s.command, "args": " ".join(s.args), "cwd": s.cwd or ""})
        except ManifestError as error:
            rows.append({"name": path.stem, "error": str(error)})
    _print(rows, args.json)
    return 0


def cmd_verify(args) -> int:
    server = find(args.server, servers_dir())
    result = handshake(server, timeout=args.timeout)
    _print(result, True)
    return 0 if result["ok"] else 1


def _plan(server, targets):
    plan = []
    for h in targets:
        row = {"host": h.id, "config": h.location(), "evidence": h.evidence}
        try:
            row["entry"] = h.native_entry(server)
            row["exists"] = h.current(server.name) is not None
        except H.HostError as error:
            row["error"] = error.code
            row["detail"] = error.detail
        plan.append(row)
    return plan


def cmd_plan(args) -> int:
    server = find(args.server, servers_dir())
    _print(_plan(server, _targets(args.hosts)), True)
    return 0


def cmd_install(args) -> int:
    server = find(args.server, servers_dir())
    targets = _targets(args.hosts)
    if not args.yes:
        print("计划（未写入；确认后加 --yes 执行）：")
        _print(_plan(server, targets), True)
        return 0
    if not args.skip_verify:
        check = handshake(server, timeout=args.timeout)
        if not check["ok"]:
            print("服务自检未通过，未写入任何宿主：")
            _print(check, True)
            return 1
    ledger, results, failed = state.Ledger(), [], False
    for h in targets:
        try:
            results.append({"host": h.id, **h.write(server, ledger, force=args.force)})
        except H.HostError as error:
            failed = True
            results.append({"host": h.id, "error": error.code, "detail": error.detail})
    _print(results, True)
    return 1 if failed else 0


def cmd_remove(args) -> int:
    server_name = args.server
    targets = _targets(args.hosts) if args.hosts else [H.get(h) for h in state.Ledger().all()
                                                        if server_name in state.Ledger().all()[h]]
    if not args.yes:
        print("将从以下宿主移除（未执行；确认后加 --yes）：", ", ".join(h.id for h in targets) or "无")
        return 0
    ledger, results, failed = state.Ledger(), [], False
    for h in targets:
        try:
            results.append({"host": h.id, **h.remove(server_name, ledger, force=args.force)})
        except H.HostError as error:
            failed = True
            results.append({"host": h.id, "error": error.code, "detail": error.detail})
    _print(results, True)
    return 1 if failed else 0


def cmd_status(args) -> int:
    ledger = state.Ledger().all()
    rows = []
    for host_id, entries in ledger.items():
        for name, info in entries.items():
            if args.server and name != args.server:
                continue
            row = {"host": host_id, "server": name, "location": info["location"], "since": info["at"]}
            try:
                h = H.get(host_id)
                live = h.current(name)
                if live is None:
                    row["state"] = "missing"
                elif host_id == "claude-code":
                    row["state"] = "present"
                else:
                    if host_id == "codex":
                        live = {k: v for k, v in live.items() if k != "startup_timeout_sec"}
                    row["state"] = "ok" if state.digest(live) == info["digest"] else "drift"
            except H.HostError as error:
                row["state"] = error.code
            rows.append(row)
    _print(rows, True)
    return 0


def cmd_rollback(args) -> int:
    found = state.latest_backup(args.host)
    if not found:
        print(f"{args.host} 没有备份。")
        return 1
    backup, origin = found
    if not args.yes:
        print(f"将用 {backup} 覆盖 {origin}（未执行；确认后加 --yes）")
        return 0
    state.backup(origin, args.host + "-before-rollback")
    shutil.copy2(backup, origin)
    print(f"已还原 {origin}（来自 {backup}）。登记表未改动，请运行 status 核对。")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="sayelf-mcp-bridge", description="MCP 接入器：一份服务定义，登记到多个 Agent")
    p.add_argument("--json", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("hosts")
    sub.add_parser("list")
    for name in ("verify", "plan", "install", "remove"):
        sp = sub.add_parser(name)
        sp.add_argument("server")
        if name != "verify":
            sp.add_argument("--hosts")
        if name in ("install", "remove"):
            sp.add_argument("--yes", action="store_true")
            sp.add_argument("--force", action="store_true")
        if name in ("verify", "install"):
            sp.add_argument("--timeout", type=float, default=30.0)
        if name == "install":
            sp.add_argument("--skip-verify", action="store_true")
    st = sub.add_parser("status")
    st.add_argument("server", nargs="?")
    rb = sub.add_parser("rollback")
    rb.add_argument("--host", required=True)
    rb.add_argument("--yes", action="store_true")
    args = p.parse_args(argv)
    try:
        return {"hosts": cmd_hosts, "list": cmd_list, "verify": cmd_verify, "plan": cmd_plan,
                "install": cmd_install, "remove": cmd_remove, "status": cmd_status,
                "rollback": cmd_rollback}[args.command](args)
    except (ManifestError, H.HostError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
