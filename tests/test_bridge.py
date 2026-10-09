from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from sayelf_mcp_bridge import hosts as H
from sayelf_mcp_bridge import state
from sayelf_mcp_bridge.cli import main
from sayelf_mcp_bridge.manifest import ManifestError, Server, parse
from sayelf_mcp_bridge.verify import handshake

HERE = Path(__file__).resolve().parent
FAKE = str(HERE / "fake_server.py")

CODEX_EXISTING = """model = "gpt-5"

[mcp_servers.cad-hub]
command = 'C:\\Program Files\\nodejs\\node.exe'
args = ['D:\\Codex\\mcp\\cad-hub\\server.mjs']
cwd = 'D:\\Codex\\mcp\\cad-hub'

[windows]
sandbox = "x"
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.userhome, self.codex = root / "home", root / "codexhome"
        self.userhome.mkdir()
        self.codex.mkdir()
        self.servers = root / "bridge" / "servers"
        self.servers.mkdir(parents=True)
        env = {"SAYELF_MCP_BRIDGE_USERHOME": str(self.userhome),
               "SAYELF_MCP_BRIDGE_HOME": str(root / "bridge"), "CODEX_HOME": str(self.codex)}
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.workdir = root / "srv"
        self.workdir.mkdir()
        self.server = Server("demo", sys.executable, (FAKE,), cwd=str(self.workdir), env={"A": "1"})
        (self.servers / "demo.json").write_text(json.dumps({
            "name": "demo", "command": sys.executable, "args": [FAKE], "cwd": str(self.workdir),
            "env": {"A": "1"}}), encoding="utf-8")

    def cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(list(args))
        return code, out.getvalue()


class ManifestTests(unittest.TestCase):
    def test_literal_secret_rejected(self):
        with self.assertRaisesRegex(ManifestError, "LITERAL_SECRET"):
            parse({"name": "x", "command": "c", "env": {"API_KEY": "sk-123"}})
        parse({"name": "x", "command": "c", "env": {"API_KEY": "${MY_KEY}"}})

    def test_bad_name_rejected(self):
        with self.assertRaises(ManifestError):
            parse({"name": "Bad Name", "command": "c"})

    def test_placeholders_expand(self):
        s = parse({"name": "x", "command": "{python}", "args": ["-m", "m"]})
        self.assertEqual(sys.executable, s.command)


class VerifyAndLaunchTests(Base):
    def test_handshake_lists_tools_in_cwd(self):
        result = handshake(self.server, timeout=10)
        self.assertTrue(result["ok"], result)
        self.assertEqual(["echo"], result["tools"])
        self.assertEqual(str(self.workdir), result["version"])  # fake reports its cwd

    def test_handshake_reports_start_failure(self):
        self.assertFalse(handshake(Server("x", "/no/such/binary"), timeout=5)["ok"])

    def test_launcher_gives_cwd_to_hosts_without_cwd(self):
        cmd, args, env = H.launcher_entry(self.server)
        result = handshake(Server("w", cmd, tuple(args), env=env), timeout=10)
        self.assertTrue(result["ok"], result)
        self.assertEqual(str(self.workdir), result["version"])


class JsonHostTests(Base):
    def test_cursor_write_preserves_other_servers_and_backs_up(self):
        path = self.userhome / ".cursor" / "mcp.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
        out = H.get("cursor").write(self.server, state.Ledger())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual({"other", "demo"}, set(data["mcpServers"]))
        self.assertEqual("stdio", data["mcpServers"]["demo"]["type"])
        self.assertIn("sayelf_mcp_bridge.launch", data["mcpServers"]["demo"]["args"])
        self.assertTrue(Path(out["backup"]).is_file())

    def test_unowned_same_name_is_not_overwritten(self):
        path = self.userhome / ".cursor" / "mcp.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"mcpServers": {"demo": {"command": "mine"}}}), encoding="utf-8")
        with self.assertRaisesRegex(H.HostError, "CONFLICT_UNOWNED"):
            H.get("cursor").write(self.server, state.Ledger())
        self.assertEqual("mine", json.loads(path.read_text())["mcpServers"]["demo"]["command"])

    def test_hand_edit_after_install_is_drift(self):
        host, ledger = H.get("cursor"), state.Ledger()
        host.write(self.server, ledger)
        path = self.userhome / ".cursor" / "mcp.json"
        data = json.loads(path.read_text())
        data["mcpServers"]["demo"]["command"] = "edited"
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(H.HostError, "DRIFT"):
            host.write(self.server, ledger)

    def test_codebuddy_uses_first_existing_file_and_jsonc_comments_block_write(self):
        legacy = self.userhome / ".codebuddy" / "mcp.json"
        legacy.parent.mkdir()
        legacy.write_text('{\n  // mine\n  "mcpServers": {}\n}', encoding="utf-8")
        host = H.get("codebuddy")
        self.assertEqual(legacy, host.path())
        with self.assertRaisesRegex(H.HostError, "HAS_COMMENTS"):
            host.write(self.server, state.Ledger())
        legacy.write_text('{"mcpServers": {}}', encoding="utf-8")
        host.write(self.server, state.Ledger())
        self.assertIn("demo", json.loads(legacy.read_text())["mcpServers"])

    def test_qwen_keeps_other_settings_and_uses_native_cwd(self):
        path = self.userhome / ".qwen" / "settings.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        H.get("qwen-code").write(self.server, state.Ledger())
        data = json.loads(path.read_text())
        self.assertEqual("dark", data["theme"])
        self.assertEqual(str(self.workdir), data["mcpServers"]["demo"]["cwd"])
        self.assertNotIn("type", data["mcpServers"]["demo"])

    def test_remove_only_owned(self):
        host, ledger = H.get("workbuddy"), state.Ledger()
        host.write(self.server, ledger)
        host.remove("demo", ledger)
        path = self.userhome / ".workbuddy" / ".mcp.json"
        self.assertNotIn("demo", json.loads(path.read_text())["mcpServers"])


class CodexTests(Base):
    def setUp(self):
        super().setUp()
        self.path = self.codex / "config.toml"
        self.path.write_text(CODEX_EXISTING, encoding="utf-8")

    def test_write_appends_marked_block_and_keeps_rest(self):
        H.get("codex").write(self.server, state.Ledger())
        text = self.path.read_text(encoding="utf-8")
        data = tomllib.loads(text)
        self.assertEqual("gpt-5", data["model"])
        self.assertIn("cad-hub", data["mcp_servers"])
        self.assertEqual(str(self.workdir), data["mcp_servers"]["demo"]["cwd"])
        self.assertEqual({"A": "1"}, data["mcp_servers"]["demo"]["env"])
        self.assertIn("# >>> sayelf-mcp-bridge: demo >>>", text)

    def test_rewrite_is_idempotent_and_remove_restores(self):
        host, ledger = H.get("codex"), state.Ledger()
        host.write(self.server, ledger)
        self.assertFalse(host.write(self.server, ledger)["changed"])
        host.remove("demo", ledger)
        data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("demo", data["mcp_servers"])
        self.assertIn("cad-hub", data["mcp_servers"])
        self.assertEqual("x", data["windows"]["sandbox"])

    def test_unmarked_existing_needs_force_then_replaced(self):
        self.path.write_text(CODEX_EXISTING + "\n[mcp_servers.demo]\ncommand = 'old'\nargs = []\n", encoding="utf-8")
        host = H.get("codex")
        with self.assertRaisesRegex(H.HostError, "CONFLICT_UNOWNED"):
            host.write(self.server, state.Ledger())
        host.write(self.server, state.Ledger(), force=True)
        data = tomllib.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(sys.executable, data["mcp_servers"]["demo"]["command"])
        self.assertEqual(1, self.path.read_text(encoding="utf-8").count("[mcp_servers.demo]"))

    def test_identical_unmarked_entry_is_adopted_without_force(self):
        block = (f"\n[mcp_servers.demo]\ncommand = '{sys.executable}'\nargs = ['{FAKE}']\n"
                 f"cwd = '{self.workdir}'\nstartup_timeout_sec = 60\n[mcp_servers.demo.env]\nA = '1'\n")
        self.path.write_text(CODEX_EXISTING + block, encoding="utf-8")
        out = H.get("codex").write(self.server, state.Ledger())
        text = self.path.read_text(encoding="utf-8")
        self.assertEqual(1, text.count("[mcp_servers.demo]"))
        self.assertIn("# >>> sayelf-mcp-bridge: demo >>>", text)
        self.assertTrue(out["changed"])

    def test_invalid_toml_is_never_written(self):
        self.path.write_text("not = = toml", encoding="utf-8")
        with self.assertRaisesRegex(H.HostError, "HOST_FILE_INVALID"):
            H.get("codex").write(self.server, state.Ledger())
        self.assertEqual("not = = toml", self.path.read_text(encoding="utf-8"))


class ClaudeCodeTests(Base):
    def test_cli_add_arguments_follow_documented_order(self):
        calls = []

        def runner(args):
            calls.append(args)
            code = 1 if args[:2] == ["mcp", "get"] and not any(c[:2] == ["mcp", "add"] for c in calls[:-1]) else 0
            return subprocess.CompletedProcess(args, code, "", "")

        host = H.get("claude-code")
        host.runner = runner
        host.write(self.server, state.Ledger())
        add = next(c for c in calls if c[:2] == ["mcp", "add"])
        self.assertLess(add.index("--env"), add.index("--transport"))
        self.assertLess(add.index("--transport"), add.index("demo"))
        self.assertEqual("--", add[add.index("demo") + 1])


class ShimTests(unittest.TestCase):
    def test_npm_cmd_shim_resolves_to_real_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            exe = base / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
            exe.parent.mkdir(parents=True)
            exe.write_text("")
            shim = base / "claude.cmd"
            shim.write_text('@ECHO off\r\n"%dp0%\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe"   %*\r\n')
            self.assertEqual([str(exe.resolve())], H.resolve_windows_shim(str(shim)))

    def test_js_shim_runs_through_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            js = base / "node_modules" / "x" / "cli.js"
            js.parent.mkdir(parents=True)
            js.write_text("")
            shim = base / "x.cmd"
            shim.write_text('"%~dp0\\node_modules\\x\\cli.js" %*')
            resolved = H.resolve_windows_shim(str(shim))
            self.assertEqual(str(js.resolve()), resolved[-1])
            self.assertEqual(2, len(resolved))

    def test_stale_npm_shim_is_reported_as_broken_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shim = base / "claude.cmd"
            shim.write_text('"%dp0%\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe" %*')
            host = H.get("claude-code")
            with patch.object(H.ClaudeCodeHost, "_claude", return_value=str(shim)):
                self.assertFalse(host.detect()[0])
                with self.assertRaisesRegex(H.HostError, "HOST_CLI_BROKEN"):
                    host.current("demo")

    def test_non_shim_is_unchanged(self):
        self.assertEqual(["/usr/bin/claude"], H.resolve_windows_shim("/usr/bin/claude"))


class CliTests(Base):
    def test_install_without_yes_writes_nothing(self):
        (self.userhome / ".cursor").mkdir()
        with patch("sayelf_mcp_bridge.cli.servers_dir", return_value=self.servers):
            code, out = self.cli("install", "demo", "--hosts", "cursor")
        self.assertEqual(0, code)
        self.assertIn("计划", out)
        self.assertFalse((self.userhome / ".cursor" / "mcp.json").exists())

    def test_install_verifies_then_writes_and_status_ok(self):
        (self.userhome / ".cursor").mkdir()
        with patch("sayelf_mcp_bridge.cli.servers_dir", return_value=self.servers):
            code, _ = self.cli("install", "demo", "--hosts", "cursor,codex", "--yes", "--timeout", "15")
            self.assertEqual(0, code)
            _, out = self.cli("status", "demo")
        states = {r["host"]: r["state"] for r in json.loads(out)}
        self.assertEqual({"cursor": "ok", "codex": "ok"}, states)

    def test_failed_handshake_blocks_install(self):
        (self.servers / "broken.json").write_text(json.dumps(
            {"name": "broken", "command": "/no/such/binary"}), encoding="utf-8")
        with patch("sayelf_mcp_bridge.cli.servers_dir", return_value=self.servers):
            code, out = self.cli("install", "broken", "--hosts", "cursor", "--yes")
        self.assertEqual(1, code)
        self.assertFalse((self.userhome / ".cursor" / "mcp.json").exists())

    def test_unsupported_host_explains_instead_of_writing(self):
        with patch("sayelf_mcp_bridge.cli.servers_dir", return_value=self.servers):
            code, out = self.cli("plan", "demo", "--hosts", "doubao")
        self.assertIn("HOST_NOT_SUPPORTED", out)

    def test_rollback_restores_previous_file(self):
        path = self.codex / "config.toml"
        path.write_text(CODEX_EXISTING, encoding="utf-8")
        H.get("codex").write(self.server, state.Ledger())
        code, _ = self.cli("rollback", "--host", "codex", "--yes")
        self.assertEqual(0, code)
        self.assertEqual(CODEX_EXISTING, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
