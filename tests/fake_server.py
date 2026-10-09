"""Minimal stdio MCP server used by tests (standard library only)."""
import json
import os
import sys

for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        reply = {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                 "serverInfo": {"name": "fake", "version": os.getcwd()}}
    elif msg.get("method") == "tools/list":
        reply = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
    else:
        continue
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": reply}) + "\n")
    sys.stdout.flush()
