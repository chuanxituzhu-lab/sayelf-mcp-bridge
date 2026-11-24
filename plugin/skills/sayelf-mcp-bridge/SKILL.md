---
name: sayelf-mcp-bridge
description: "把一个 MCP 服务（本地 stdio 或远程 URL，如 https://mcp.sayelf.app/mcp）一次登记到本机所有 Agent 宿主：Claude Code、Codex、Cursor、CodeBuddy、WorkBuddy、Qwen Code，保留已有配置、可回滚。Use when the user wants to register, add, sync, check or remove an MCP server across several agent hosts, or mentions MCP 接入器 / 通用MCP接入 / 把 MCP 装到 / 所有 Agent 都能用."
---

# sayelf-mcp-bridge（MCP 接入器）

目标：一个 MCP 服务写一份清单，登记一次，本机所有 Agent 宿主都能用。

> 本插件只有说明，工具本体是本机的 Python 包 `sayelf_mcp_bridge`（只用标准库）：
> - 位置：`D:\Codex\skills\sayelf-mcp-bridge`（`~/.claude/skills/sayelf-mcp-bridge` 指向同一目录）
> - 源码仓库：https://github.com/chuanxituzhu-lab/sayelf-mcp-bridge
> - 所有命令都在该目录下运行：`python -m sayelf_mcp_bridge <命令>`
> 旧版说明里的 `register_mcp.py` 已不存在，不要再用。

## 工作流程（必须按顺序）

1. **看宿主**：`python -m sayelf_mcp_bridge hosts` —— 本机装了哪些 Agent、配置位置、依据等级（official / local / none）。
2. **自检服务**：`python -m sayelf_mcp_bridge verify <名称>` —— 本地服务：真实启动并完成 MCP 握手、列出工具；远程服务：确认地址可达，并要求 OAuth 登录（或直接可用）。失败就停，不要登记。
3. **出计划**：`python -m sayelf_mcp_bridge plan <名称> [--hosts a,b]` —— 把将写入每个宿主的内容**原样展示给用户**。
4. **用户确认后执行**：`python -m sayelf_mcp_bridge install <名称> --yes [--hosts a,b]`。
5. **核对**：`python -m sayelf_mcp_bridge status <名称>`；提醒用户重启对应 Agent；远程服务还要在每个宿主里登录一次。

撤销：`remove <名称> --yes`；改坏了：`rollback --host <宿主> --yes`。查看已有清单：`list`。

## 宿主覆盖表

| 宿主 | 配置位置 | 依据 | 远程服务写法 |
|---|---|---|---|
| Claude Code | `claude mcp --scope user`（~/.claude.json） | 官方 | `--transport http <名称> <url>` |
| Codex | `CODEX_HOME/config.toml`（本机 `D:\Codex\config.toml`）`[mcp_servers.<名称>]` | 官方 | `url = "…"`；登录 `codex mcp login <名称>` |
| Cursor | `~/.cursor/mcp.json` | 官方 | `{"url": …}` |
| CodeBuddy | `~/.codebuddy/.mcp.json`，否则 `mcp.json` | 官方 | `{"type": "http", "url": …}` |
| WorkBuddy | `~/.workbuddy/.mcp.json` | 本机实证 | `{"type": "http", "url": …}`；写入后请用户在设置 → MCP 确认 |
| Qwen Code | `~/.qwen/settings.json` 的 `mcpServers` | 官方 | `{"httpUrl": …}` |
| 千问桌面、豆包、太一/OpenClaw | 未知 | 无 | 不写入；如其界面支持远程 MCP，请用户手动填 URL |

## 新增一个 MCP 服务

在工具目录的 `servers/` 放一份 JSON：

- 本地服务：`name`、`command`、`args`，可选 `cwd`、`env`。占位符 `{python}`、`{skills_root}`、`{home}`。没有 `cwd` 字段的宿主由启动器 `sayelf_mcp_bridge.launch` 自动补齐工作目录。
- 远程服务：只写 `name`、`description`、`url`（必须 https；本机调试可用 http://localhost）。登录（OAuth）在各宿主首次使用时进行，清单里不放任何令牌。示例：`servers/sayelf.json` → https://mcp.sayelf.app/mcp。

现有清单：`sayelf`（网站，远程）、`sayelf-agent-ops`、`lizhu`、`solidworks-2022`。

## 硬规则

1. 未经用户确认不加 `--yes`；`--force` 只在用户明确同意替换已有条目时使用。
2. 只改本工具登记过的条目：同名的他人条目报 `CONFLICT_UNOWNED`，被手改过报 `DRIFT`，两者都先告诉用户，不要自行 `--force`。
3. 每次写入前自动备份（`~/.sayelf/mcp-bridge/backups/`）；带注释的 JSONC 文件不改写（`HOST_FILE_HAS_COMMENTS`），给出片段让用户手加。
4. 清单里不得写明文密钥（会被复制进每个宿主的配置）；用 `${变量名}` 引用。
5. 依据为"无"的宿主不写入，如实告诉用户原因与替代方案。

宿主规则与出处见工具目录的 `docs/hosts.md`。
