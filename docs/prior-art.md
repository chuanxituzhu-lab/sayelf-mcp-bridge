# 同类开源工具与借鉴（2026-10-09 调研）

| 项目 | 做什么 | 借鉴了什么 | 没采用什么、为什么 |
|---|---|---|---|
| [mcpm.sh](https://github.com/pathintegral-institute/mcpm.sh)（MIT，约 1k 星） | MCP 包管理器：全局安装一次、按 profile 分组、`mcpm client edit` 管各客户端；带注册表与 `doctor` | “服务只定义一次、客户端只是投影”的模型；`doctor` 式的状态检查（本工具的 `status`） | 中心注册表、profile 代理运行、隧道分享：与“本地优先、只接自己的服务”无关，且公开页面未说明写客户端配置前的备份 |
| [mcpup](https://github.com/mohammedsamin/mcpup)（Go，MIT） | 一份规范配置同步到 13 个客户端；写前备份、按客户端回滚、`--dry-run`、保留非自己管理的条目、`doctor` 查漂移 | **所有权感知写入**（只动自己写的条目）、**写前备份 + 按宿主回滚**、**先预览后执行**、**漂移检测** —— 四点都已落到本工具 | 97 个内置第三方服务模板：本工具只登记你自己的服务，不分发第三方 |
| [mcp-hosts-installer](https://github.com/soufgit/mcp-hosts-installer)（MIT） | 以 MCP 服务形式，从 npm/PyPI 安装别的 MCP 服务并写入宿主配置 | 宿主探测顺序的思路（找已存在的配置文件） | 让 Agent 自己调用安装器改配置：等于让 Agent 自行扩权，违背“人确认后才写入” |
| Smithery CLI `install --client` | 从 Smithery 注册表一键装到指定客户端 | 按客户端名称选择目标的命令形态（`--hosts`） | 依赖第三方注册表与网络 |

## 这些工具都没有、本工具补上的

1. **国内宿主**：CodeBuddy、WorkBuddy、Qwen Code，以及对豆包、千问桌面版、太一的如实“不支持/待核实”说明。
2. **依据分级**：每个宿主标注 official / local / none 与出处；没有依据不写入。
3. **登记前真实握手**：用标准库完成 MCP `initialize → tools/list`，服务起不来就不登记。
4. **工作目录启动器**：对没有 `cwd` 字段的宿主统一补齐，而不是要求每个服务自己处理路径。
5. **不写明文密钥**：清单中带 key/token/secret/password 的变量必须用 `${变量}` 引用。
6. **零依赖**：只用 Python 标准库，任何装了 Python 3.11 的机器都能运行。

所有借鉴均为机制层面的重新实现，未复制上述项目的代码。
