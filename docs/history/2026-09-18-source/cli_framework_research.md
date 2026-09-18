# CLI 框架与命令接口研究

> 核对日期：2026-09-17。
> 状态：已确认选择 A（Typer + Rich）。

## 事实核对

- PyPI 当前 Typer 0.27.2 和 Click 8.5.0 均声明 Python `>=3.10`，覆盖已确定的 Python 3.13。
- Typer 基于 Click，提供类型提示驱动的参数、嵌套子命令、自动帮助和 Bash/Zsh/Fish/PowerShell 补全。
- Click 直接提供成熟的 command/group/context 抽象，能获得更细控制，但需要手工声明更多参数与类型转换。
- argparse 在 Python 3.13 标准库内支持参数与子命令，不增加运行依赖，但大型嵌套命令、补全和一致化输出需要更多自建代码。

来源：

- [Typer features](https://typer.tiangolo.com/features/)
- [Click commands and groups](https://click.palletsprojects.com/en/stable/commands-and-groups/)
- [Python 3.13 argparse](https://docs.python.org/3.13/library/argparse.html)
- [PyPI Typer metadata](https://pypi.org/project/typer/)

## 选项

| 选项 | 方案 | 优点 | 代价与风险 |
|---|---|---|---|
| A（推荐） | Typer + Rich，Click 作为传递依赖 | 与 FastAPI/Pydantic 的类型化风格一致；命令树和 PowerShell 补全成本低；人类诊断体验好 | 多一层 Typer 抽象；必须单独锁 Typer/Click 兼容范围并避免 Rich 改变脚本输出 |
| B | 直接使用 Click | 控制 parser/context/输出最直接；生态成熟；比 Typer 少一层行为 | 注解不能直接成为完整 CLI schema；每个命令样板更多；仍需 Rich 或自建展示 |
| C | 标准库 argparse | 无第三方 CLI 运行依赖；行为完全由项目控制 | 嵌套命令、补全、文档、类型转换和测试工具需要更多维护；不符合本项目已有依赖取向 |

## 推荐 A 的具体边界

- 根入口为 `tsunagou`，通过 `pyproject.toml [project.scripts]` 指向薄 CLI composition entry；正式运行仍使用已登记 checkout 的 `uv run tsunagou ...`。
- 首版命令组固定为 `runtime`、`daemon`、`project`、`agent`、`task`、`contract`、`operation`、`doctor` 和 `completion`。命令组只调用 application public facades 或已运行 daemon 的 REST API。
- CLI callback 不持有 SQLAlchemy session，不直接读写项目 SQLite，不直接执行 Git/worktree 或宿主进程操作。
- 默认模式面向人类：Rich 表格和明确错误提示；`--json` 使用稳定 schema，仅向 stdout 输出一个 JSON document，日志、进度与提示进入 stderr。
- 颜色仅在交互 TTY 默认启用，尊重 `NO_COLOR`；`--no-color` 显式关闭。JSON 模式永不输出 ANSI、spinner 或 Rich markup。
- 全局参数仅包括 `--project`、`--endpoint`、`--json`、`--no-color`、`--timeout`、`--verbose`；凭据从 credential store/受保护文件读取，不接受会进入 shell history 的 token 参数。
- 稳定退出码：`0` 成功，`2` CLI 用法错误，`3` 鉴权/权限，`4` 未找到，`5` revision/conflict，`6` validation，`7` daemon unavailable/timeout，`8` asynchronous operation failed，`10` unexpected internal error。异步命令返回已创建 Operation 时仍为 `0`，除非使用 `--wait` 且终态失败。
- `--wait` 轮询 Operation 并显示可取消进度；`--wait-timeout` 只停止客户端等待，不取消 Operation。脚本应以 Operation status 判断异步结果。
- Typer pretty exception 在正式 CLI 关闭；普通错误映射为稳定错误码和 RFC 9457 字段，只有 `--verbose` 或日志文件保留 traceback。
- 测试分两层：命令解析/输出使用 Typer `CliRunner`，完整本机行为通过真实 loopback daemon 子进程测试。JSON fixtures 纳入兼容检查。

## 首版命令轮廓

```text
tsunagou runtime register|show|repair|unregister
tsunagou daemon start|status|stop|logs
tsunagou project init|list|show|archive|delete|backup|restore
tsunagou agent ticket|list|show|revoke|set-main
tsunagou task create|list|show|claim|start|submit|review|cancel|resume
tsunagou contract list|show|propose|accept|reject
tsunagou operation list|show|wait|cancel|resolve
tsunagou doctor [--fix-safe]
tsunagou completion install|show
```

`task`/`contract` 命令是用户和人工调试入口，不替代适配器的类型化 tools。`doctor --fix-safe` 只能执行不会扩大权限、删除数据或改写业务状态的确定性修复。

## 后续细化

- 每个命令的完整参数、交互确认规则、REST 映射和 JSON output schema。
- 配置文件、环境变量、CLI 参数的优先级以及哪些设置允许运行时修改。
- `daemon start` 在 Windows 隐藏进程中的 bootstrap、日志路径和 endpoint 就绪握手。
