# Python 首版兼容窗口与依赖分组

> 核对日期：2026-09-17。
> 状态：已确认选项 A；作为 D77 的依赖基线，具体 lower bound 仍须由最小 spike 验证。

## 注册表核对结论

- 选定包的当前版本均声明支持 Python 3.13；首版可以只正式验证 CPython 3.13.x。
- FastAPI 0.141.1 要求 Starlette `>=0.46`、Pydantic `>=2.9`；sse-starlette 3.4.11 要求 Starlette `>=0.49.1`、AnyIO `>=4.7`，当前约束可求解，但应由锁文件固定实际 Starlette/AnyIO 组合。
- Alembic 1.20 要求 SQLAlchemy `>=2.0`；SQLAlchemy 2.0.54 提供 asyncio/aiosqlite extra。
- pytest-asyncio 1.4 支持 pytest `>=8.4,<10`，因此当前 pytest 9.1.1 组合可用。
- datamodel-code-generator 0.82 在 Python 3.13 上接受 Pydantic 2.x，并提供 Pydantic v2 output。
- FastAPI、Uvicorn、Typer、HTTPX、sse-starlette 等仍为 `0.x`；只写 `<1` 会允许多个未经验证的 minor 行为变化。

数据源：各项目 [PyPI JSON API](https://warehouse.pypa.io/api-reference/json.html) 元数据；完整快照见 [technology_stack_research.md](./technology_stack_research.md)。

## 选项

| 选项 | 声明与支持策略 | 优点 | 代价与风险 |
|---|---|---|---|
| A（推荐） | 首版正式支持 CPython 3.13；核心 `0.x`/紧耦合包锁当前 minor，稳定库锁下一个 major；uv.lock 精确固定 | 升级面有界；允许兼容 patch 候选；避免 pyproject 重复精确 lock | 需要按计划维护 minor 窗口，升级要显式 PR |
| B | Python `>=3.13`，依赖只锁 major（FastAPI/Uvicorn 等 `<1`） | 声明简洁；较少调整 pyproject | 对 `0.x` 过宽；重新解析可能跨多个行为版本，测试矩阵不可控 |
| C | pyproject 中所有包都 `==` 精确版本 | 任意环境解析结果直观 | 与 uv.lock 重复；安全 patch 也要改每条声明；无法表达真正兼容边界 |

## 推荐 A：解释规则

- `requires-python = ">=3.13,<3.14"`。首版正式支持 CPython 3.13.x；未来增加 3.14 要通过 SQLite/asyncio/keyring/codegen/四 adapter 全套回归后扩大范围。
- `pyproject.toml` 表达允许进入升级评估的候选窗口，`uv.lock` 表达唯一正式开发/CI/源码运行组合。仅落在声明范围并不代表已经正式支持。
- 普通 `uv sync`/`uv run` 使用 `--locked`；任何锁变化必须由显式 dependency update 产生，CI 拒绝隐式重解。
- 每个直接依赖必须附 `reason`/owner 注释或在依赖清单文档中映射用途；删除功能时同步清除不再需要的包。

## 首个候选范围

最终 lower bound 在最小 spike 通过后固定；基于当前已核对组合，首个候选如下：

| 分组 | 包 | 候选声明范围 |
|---|---|---|
| core web | fastapi | `>=0.141.1,<0.142` |
| core web | uvicorn | `>=0.53.0,<0.54` |
| core model | pydantic | `>=2.13.5,<2.14` |
| core config | pydantic-settings | `>=2.15.0,<2.16` |
| database | sqlalchemy[asyncio] | `>=2.0.54,<2.1` |
| database | alembic | `>=1.20.0,<1.21` |
| database | aiosqlite | `>=0.22.1,<0.23` |
| transport | sse-starlette | `>=3.4.11,<3.5` |
| transport | httpx | `>=0.28.1,<0.29` |
| CLI | typer | `>=0.27.2,<0.28` |
| platform | platformdirs | `>=4.11.9,<5` |
| platform | keyring | `>=25.7.0,<26` |
| platform | watchfiles | `>=1.2.0,<2` |
| platform | portalocker | `>=4.3.2,<5` |
| protocol/config | jsonschema | `>=4.26.0,<5` |
| protocol/config | tomlkit | `>=0.15.1,<0.16` |
| protocol primitives | rfc8785 | `==0.1.4` |
| protocol primitives | uuid6 | `==2025.0.1` |
| observability | structlog | `>=26.1.0,<27` |
| optional telemetry | opentelemetry-sdk | `>=1.44.0,<1.45` |
| CLI transitive guard | click | `>=8.5.0,<8.6` |

- `rfc8785` 和 `uuid6` 直接封装在项目 ports/factory 后并精确声明，因为它们 API 面小、替换需要 RFC fixture 验证且更新节奏不同于常规 SemVer minor。
- Click 虽由 Typer 引入，仍显式约束并测试，因为 CLI 解析/退出行为属于公共接口。
- Starlette、AnyIO、pydantic-core、OTel API/semantic-conventions 等紧耦合传递依赖由 uv.lock 精确固定；除非代码直接导入，否则不全部提升为 direct dependency。
- 不使用 `fastapi[standard]` 或 `uvicorn[standard]` 大包 extra；按实际需要直接声明 Uvicorn、watchfiles 等，避免引入 `.env`、WebSocket、模板和上传依赖。

## 依赖分组

- `[project.dependencies]`：daemon/CLI 运行必需的 web、DB、protocol、platform 与 logging 包。
- `[project.optional-dependencies].otel` 或 uv 对应 runtime extra：OTel SDK/exporter；未启用时 core trace context 和本地日志仍工作。
- `[dependency-groups].dev`：pytest、pytest-asyncio、Hypothesis、Ruff、mypy/pyright 等开发工具。
- `[dependency-groups].codegen`：datamodel-code-generator、OpenAPI/schema validation 辅助工具；生产 daemon 不需要导入。
- `[dependency-groups].benchmark`：仅实验 harness 需要的统计/报告包，不能渗入 runtime。

首个开发候选窗口：pytest `>=9.1.1,<10`、pytest-asyncio `>=1.4,<2`、Hypothesis `>=6.168,<7`、datamodel-code-generator `>=0.82,<0.83`。Ruff 和静态类型工具在工具链 spike 时再核对并固定。

## 升级与支持证据

- 依赖更新命令按 package set 定向执行，不做无边界 `uv lock --upgrade`。Web 栈、DB 栈、协议生成、OTel 各为独立升级组。
- PR 记录旧/新 lock diff、上游 changelog、已知 breaking/deprecation、schema/OpenAPI/generated diff 和 Windows 检查结果。
- 安全修复可以加速升级，但不能跳过 migration、codegen、协议 fixtures 与核心故障注入。
- 每次 release manifest 记录 Python exact、uv exact、lock digest 和主要依赖 exact versions；`doctor` 报告运行环境偏离。
- macOS/Linux 可运行同一 lock，但首版只有 Windows 结果阻止发布，兼容声明继续如实标注。

## Spike 退出条件

- FastAPI/Uvicorn/SSE bearer stream、断线取消与优雅关机通过 Windows 测试。
- SQLAlchemy async + aiosqlite 在 WAL/FULL、单写队列、Alembic/backup 并发下通过故障测试。
- keyring 在 Windows Credential Manager 正常工作，降级文件权限检查可复现。
- JCS/UUIDv7、schema/codegen 和 Typer JSON/退出码 fixtures 通过。
- 若当前最新组合失败，只回退有证据的问题包并记录 upper exclusion，不能任意整体降级。
