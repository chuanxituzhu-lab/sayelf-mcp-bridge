# sayelf-mcp-bridge · MCP 接入器

一份 MCP 服务定义，登记到多个 Agent：Claude Code、Codex、Cursor、CodeBuddy、WorkBuddy、Qwen Code。先自检、再计划、经你确认才写入；只改自己写过的条目，写前备份，可撤销、可回滚。只用 Python 3.11+ 标准库。

```powershell
cd D:\Codex\skills\sayelf-mcp-bridge
python -m sayelf_mcp_bridge hosts                         # 本机有哪些 Agent、依据等级
python -m sayelf_mcp_bridge verify sayelf-agent-ops        # 真实启动并握手
python -m sayelf_mcp_bridge plan sayelf-agent-ops          # 预览将写入的内容
python -m sayelf_mcp_bridge install sayelf-agent-ops --yes # 确认后写入
python -m sayelf_mcp_bridge status sayelf-agent-ops        # 核对：ok / drift / missing
python -m sayelf_mcp_bridge remove sayelf-agent-ops --yes  # 撤销
python -m sayelf_mcp_bridge rollback --host codex --yes    # 还原某宿主上一次写入前的配置
```

- 服务清单：`servers/<名称>.json`（也可放在 `~/.sayelf/mcp-bridge/servers/`）。
- 宿主规则与出处：[docs/hosts.md](docs/hosts.md)。
- 同类开源工具与借鉴：[docs/prior-art.md](docs/prior-art.md)。
- 作为 Claude Code / Codex 的 Skill 使用：见 [SKILL.md](SKILL.md)。

豆包、千问桌面版暂无已知的本机 MCP 接入方式；太一/OpenClaw 官方支持 MCP，格式待核实后补适配器。

测试：`python -m unittest discover -s tests -v`

License: MIT
