# 各宿主的 MCP 接入规则（2026-10-09 核对）

依据等级：**official** = 宿主官方文档；**local** = 宿主自己在本机生成的配置里观察到、官方文档未覆盖；**none** = 未找到本机接入方式，不写入。

| 宿主 | 依据 | 登记位置 | 格式要点 | cwd | 出处 |
|---|---|---|---|---|---|
| Claude Code | official | `claude mcp add --scope user`（存于 `~/.claude.json`） | `--env` 放在服务名之前，中间隔一个其他选项（如 `--transport stdio`）；`--` 之后原样传给服务 | 无 → 启动器 | https://code.claude.com/docs/en/mcp |
| Codex | official | `CODEX_HOME/config.toml`（默认 `~/.codex/config.toml`） | `[mcp_servers.<名称>]`：`command`、`args`、`cwd`、`startup_timeout_sec`，`[mcp_servers.<名称>.env]` | 有 | Codex 配置格式；与本机已有条目一致 |
| Cursor | official | `~/.cursor/mcp.json` | `mcpServers.<名称>`：`type: "stdio"`、`command`、`args`、`env`、`envFile` | 文档未列 → 启动器 | https://cursor.com/docs/mcp |
| CodeBuddy | official | 用户级取第一个已存在的 `~/.codebuddy/.mcp.json`、`~/.codebuddy/mcp.json`（后者已弃用）；都没有时新建 `.mcp.json` | `mcpServers`，`type` 建议显式写 `stdio`；支持 JSONC | 文档未列 → 启动器 | https://www.workbuddy.ai/docs/cli/mcp |
| WorkBuddy | local | `~/.workbuddy/.mcp.json` | 与 CodeBuddy 同结构（本机已有 `type: "http"` 条目） | 未知 → 启动器 | 官方 MCP 指南只写了界面添加远程服务 |
| Qwen Code | official | `~/.qwen/settings.json` 的 `mcpServers` | `command`、`args`、`cwd`、`env`、`timeout`、`trust` | 有 | https://qwenlm.github.io/qwen-code-docs/en/developers/tools/mcp-server/ |
| 千问桌面版 | none | — | 本机 `~/Qianwen`、`~/.qwen-agent` 未见 MCP 配置 | — | 改用 Qwen Code |
| 豆包 | none | — | 未找到官方本机 MCP 接入说明 | — | 等 HTTP 入口（需鉴权） |
| 太一 / OpenClaw | none（待核实） | `~/.openclaw/openclaw.json`（JSON5） | 官方文档确认支持 MCP，键名与格式在 config-extensions 页，尚未核实 | — | https://docs.openclaw.ai/gateway/configuration-reference |

## 启动器

宿主配置里没有 `cwd` 字段时，登记的命令改为：

```text
python -m sayelf_mcp_bridge.launch --cwd <工作目录> -- <原命令> <原参数>
```

启动器只切换目录并原样转接标准输入输出，MCP 流量不经过任何改写。

## 补一个新宿主的条件

1. 找到官方文档，或在该宿主自己生成的配置里观察到结构（标为 local）；
2. 写适配器与测试（保留其他条目、所有权检查、备份、可撤销）；
3. 在本表登记依据与出处。
