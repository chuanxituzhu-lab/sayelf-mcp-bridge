"""Standard-library MCP stdio handshake: initialize → initialized → tools/list.

MCP stdio framing is one JSON-RPC message per line. No SDK needed to check
that a server actually starts and answers the way a host will call it.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading

from .manifest import Server

PROTOCOL_VERSION = "2025-06-18"


def handshake(server: Server, timeout: float = 30.0) -> dict:
    env = {**os.environ, **{k: os.path.expandvars(v) for k, v in server.env.items()}}
    try:
        proc = subprocess.Popen(
            [server.command, *server.args], cwd=server.cwd or None, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError) as error:
        return {"ok": False, "error": f"START_FAILED:{error.__class__.__name__}"}

    lines: "queue.Queue[str | None]" = queue.Queue()

    def pump():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()

    def send(message: dict) -> None:
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def receive(want_id: int) -> dict | None:
        while True:
            try:
                line = lines.get(timeout=timeout)
            except queue.Empty:
                return None
            if line is None:
                return None
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue  # stray non-protocol output; a strict host would also choke on this
            if message.get("id") == want_id:
                return message

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "sayelf-mcp-bridge", "version": "0.1.0"}}})
        init = receive(1)
        if not init or "result" not in init:
            return {"ok": False, "error": "NO_INITIALIZE_RESPONSE", "stderr": _tail(proc)}
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = receive(2)
        if not listed or "result" not in listed:
            return {"ok": False, "error": "NO_TOOLS_RESPONSE", "stderr": _tail(proc)}
        info = init["result"].get("serverInfo", {})
        return {"ok": True, "server": info.get("name"), "version": info.get("version"),
                "protocol": init["result"].get("protocolVersion"),
                "tools": [t.get("name") for t in listed["result"].get("tools", [])]}
    except (BrokenPipeError, OSError):
        return {"ok": False, "error": "SERVER_EXITED", "stderr": _tail(proc)}
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except Exception:
                pass


def _tail(proc) -> str:
    try:
        proc.terminate()
        _, err = proc.communicate(timeout=5)
        return (err or "")[-800:]
    except Exception:
        return ""
