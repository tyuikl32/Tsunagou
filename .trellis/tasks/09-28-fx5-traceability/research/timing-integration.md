# FX5 安装与接入计时集成

记录时间：2026-09-28T13:44:45.000Z。本项实现 T3 的安装/接入部分，并验证 T4/T6 对查询与字段可见性的相关要求；不代表 FX5 全项验收，也不替代原 Desktop 会话唤醒实测。

## 当前字段和边界

成功安装在既有 `~/.tsunagou/installation.json` 保存以下字段，不新建数据库：

| 字段 | 含义 |
| --- | --- |
| `install_started_at` | 本次安装尝试开始的 UTC RFC3339 毫秒时间 |
| `install_finished_at` | 依赖、项目 bootstrap、校验、launcher/PATH 登记完成后的 UTC 时间，随后原子保存此记录 |
| `duration_ms` | 同一安装进程的 `monotonic_ns` 差值换算毫秒；不是 wall-clock 相减 |
| `installed_at` | 保留旧查询字段，新成功安装与 `install_finished_at` 相同 |
| source/commit/Python/bridge metadata | 保留既有实际安装来源与版本；查询不运行 Git、安装或 daemon |

安装器普通和 JSON 失败输出都包含本次实际起止和 monotonic 耗时；失败不覆盖上次成功安装记录。已有 `started_at`、`finished_at` 输出字段保留，指向同一尝试。dry-run 不物化安装记录，`install_started_at`/`install_finished_at` 为 null；其通用 started_at/finished_at/duration_ms 只是预演进程经过时间。

`agent connect` 沿用私有 `connection.json`，本次结果及文件包含：

- `connect_started_at`、`connect_finished_at`：当前 CLI 尝试的 UTC 起止。
- `duration_ms`：该 CLI 尝试的 monotonic 经过时间。
- `enrolled_at`：本次 helper bridge 确认正确项目和目标角色的时刻。它不能证明原对话已加载 MCP，因此状态仍为 `enrolled`，next 仍要求原对话调用 context；不写 `ready_at`。
- `connected_at`：保留第一次已记录的成功接入时间。重复 connect 不改此值；旧 connection.json 缺该字段则保持 null，不以新尝试替历史补造。

失败 connect 输出实际尝试起止和耗时。若 enrollment 尚未被观察到，enrolled_at=null；若已经确认 enrollment、随后步骤失败，则保留这次真实阶段时间，整体 status 仍为 error。失败不把旧成功 connection.json 替换为失败报告。

接入报告不再直接展开 helper context：仅公开 project_id、agent_id、role；session 仅保留 status/connection_epoch/baseline_status；host_binding 仅保留 provider/status/binding_revision/connection_epoch。raw session/thread、私有 endpoint、credential 不进入报告。原 context API 未改。

## 用户查询

从任意目录执行：

```powershell
tsunagou installation-info --json
```

这是本机安装元数据查询，不需要 daemon 或项目令牌。也支持顶层 `tsunagou --json installation-info`。查询白名单包含来源、commit、runtime 路径/版本、source_dirty、installed_at、安装起止与 duration_ms。缺失安装记录返回 not_installed 和 null 字段；旧记录缺新时间字段返回 null，不写文件、不生成事件。

本轮在当前机器实际运行开发入口 `.\.venv\Scripts\python.exe -m tsunagou installation-info --json`，读取到 source_root=`D:\Tsunagou`、commit=`1fb86e08b9cfaab312a9210a3eb15d0108314c36`、Python 3.13.13、bridge 0.1.0、source_dirty=true。原安装 recorded installed_at=`2026-09-28T12:57:57.116Z`；因为早于本次改动，三个新增安装计时字段均为 null。这是未知历史值的真实结果，不是本轮实装通过证据。

## 修改范围

- `tools/install/install.py`：monotonic 计时、成功安装记录、失败输出；继续保留 `sync --locked --inexact` 和后续 `run --no-sync`。
- `src/tsunagou/cli/app.py`：仅新增 installation-info，以及 agent_connect 的计时和输出白名单。未改 daemon、MCP 注册或 diagnostics 函数。
- `tests/unit/test_install.py`：临时 home/模拟注册表下的计时落盘、时钟回拨仍按 monotonic 计时、失败不覆盖成功记录。
- `tests/unit/test_onboarding_timing.py`：离线只读和 sentinel 隔离、未知值、重复接入时间、失败阶段时间。
- `tests/integration/test_onboarding_connect.py`：原两会话真实 CLI/daemon/MCP fixture 中增加计时顺序、首次时间稳定、connection.json 一致和 session_id 不公开断言；顺手修正该文件 import 顺序。

## 实际验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_install.py tests/unit/test_onboarding_timing.py tests/unit/test_cli.py tests/integration/test_onboarding_connect.py::test_one_connect_and_shared_mcp_keep_two_host_conversations_separate -q
.\.venv\Scripts\python.exe -m ruff check tools/install/install.py src/tsunagou/cli/app.py tests/unit/test_install.py tests/unit/test_onboarding_timing.py tests/integration/test_onboarding_connect.py
.\.venv\Scripts\python.exe -m mypy tools/install/install.py src/tsunagou/cli/app.py
.\.venv\Scripts\python.exe -m tsunagou installation-info --help
.\.venv\Scripts\python.exe -m tsunagou installation-info --json
```

结果：20 tests passed，退出码 0；Ruff 在修正集成测试 import 顺序后通过；mypy 两源文件通过；help 注册和真实安装信息查询通过。`git diff --check` 定向检查通过。计时 unit fixture 包含 UTC wall-clock 回拨，duration_ms 仍为实际模拟 monotonic 差值；真实 CLI fixture 验证两次 connect 的顺序和落盘。

本项没有执行实际安装器或 uv sync。下一步由主会话串行实装，核对新安装记录起止/耗时以及既有开发依赖是否保留。真实宿主 original MCP ready、Worker 工作/提交、main review、用户确认等其他阶段仍由对应任务提供证据，不能从本项 enrolled_at 推断。
