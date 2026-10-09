---
name: sayelf-mcp-bridge
description: "Use when an MCP server should be registered into (or removed from) several agent hosts at once — Claude Code, Codex, Cursor, CodeBuddy, WorkBuddy, Qwen Code — or when the user asks which agents can use a local MCP server. Chinese triggers: MCP 接入 / 接入器 / 把 MCP 装到 / 注册 MCP / 所有 Agent 都能用 / MCP 登记 / 撤销 MCP. Not for writing MCP servers themselves (use mcp-builder) or for remote/HTTP connectors."
metadata:
  short-description: 一份 MCP 服务定义，登记到多个 Agent（先计划、再确认、可回滚）
  aliases: [MCP 接入器, MCP 接入, 注册 MCP, MCP 登记]
---

# Sayelf MCP 接入器

> 当前内容版本：0.1.0。

一个 MCP 服务写一份清单（`servers/<名称>.json`），由本工具按各宿主自己的规则登记进去。只用 Python 标准库。

## 工作流程（必须按顺序）

1. **看宿主**：`python -m sayelf_mcp_bridge hosts` —— 本机装了哪些 Agent、各自的配置位置、依据等级（official / local / none）。
2. **自检服务**：`python -m sayelf_mcp_bridge verify <名称>` —— 真实启动服务并完成 MCP 握手，列出工具。失败就停，不要登记。
3. **出计划**：`python -m sayelf_mcp_bridge plan <名称> [--hosts a,b]` —— 把将写入每个宿主的内容**原样展示给用户**。
4. **用户确认后执行**：`python -m sayelf_mcp_bridge install <名称> --yes [--hosts a,b]`。
5. **核对**：`python -m sayelf_mcp_bridge status <名称>`；提醒用户重启对应 Agent。

撤销：`remove <名称> --yes`；改坏了：`rollback --host <宿主> --yes`。

## 硬规则

1. 未经用户确认不加 `--yes`；`--force` 只在用户明确同意替换已有条目时使用。
2. 只改本工具登记过的条目；同名的他人条目报 `CONFLICT_UNOWNED`，被手改过报 `DRIFT`——两者都先告诉用户，不要自行 `--force`。
3. 每次写入前自动备份；带注释的 JSONC 文件不改写（`HOST_FILE_HAS_COMMENTS`），给出片段让用户手加。
4. 清单里不得写明文密钥（会被复制进每个宿主的配置）；用 `${变量名}` 引用。
5. 依据为 `none` 的宿主（豆包、千问桌面、太一/OpenClaw 待核实）不写入，如实告诉用户原因与替代方案。
6. `local` 依据的宿主（WorkBuddy）写入后，请用户在该 Agent 的设置里确认服务已出现。

## 新增一个 MCP 服务

在 `servers/` 放一份 JSON：`name`、`command`、`args`、可选 `cwd`、`env`。占位符：`{python}`、`{skills_root}`、`{home}`。没有 `cwd` 字段的宿主会自动通过启动器补齐工作目录。

宿主规则与出处见 `docs/hosts.md`；同类开源工具的借鉴见 `docs/prior-art.md`。
