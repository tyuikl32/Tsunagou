# 技术与库

这是已选择的技术方向，不是已安装依赖清单。当前仓库尚无产品代码和锁文件；T01 生成锁文件并在 Windows 验证安装，T02 实测四种宿主。不得把研究时查询到的版本当作已通过测试。

| 层次 | 选用技术/库 | 用途 |
|---|---|---|
| 后端语言与环境 | Python 3.13，uv，单 Python distribution、src layout | 控制本机服务和跨平台开发成本 |
| HTTP | FastAPI、Uvicorn、httpx、sse-starlette | 类型化 API、本机服务、客户端、SSE 提示 |
| 模型与设置 | Pydantic 2、pydantic-settings、jsonschema | 生成模型、配置、JSON Schema 2020-12 校验 |
| 数据库 | SQLite WAL + FULL、SQLAlchemy 2、Alembic、aiosqlite | 项目独立数据、迁移、事务与并发读取 |
| CLI | Typer、Rich（底层 Click） | 可读输出与 `--json` 自动化接口 |
| 本机能力 | platformdirs、portalocker、watchfiles、tomlkit | 用户目录、项目独占锁、文件观察、配置文件 |
| 标识与哈希 | uuid6、rfc8785、标准库 secrets/hashlib | UUIDv7、JCS canonical JSON、随机凭据与摘要 |
| 桥接 | Node 24 LTS 窗口、pnpm 12、TypeScript 7、ESM/NodeNext | 四宿主 adapter 与共享 bridge-sdk |
| 协议生成 | datamodel-code-generator、json-schema-to-typescript、openapi-typescript、openapi-fetch | 一份契约生成双语言模型及 HTTP 客户端 |
| MCP | 官方 Python SDK 承载 daemon 的项目 MCP 服务；官方 TypeScript SDK 用于 bridge 的必要传输适配 | 模型工具接入、stdio 薄转发；具体 SDK API/version 由 T02 锁定 |
| 日志观测 | structlog；OpenTelemetry 选配 | 结构化审计、可选本机 OTLP |
| 验证 | pytest、pytest-asyncio、Hypothesis、Ruff、mypy、Vitest | 状态机、属性测试、跨语言 fixtures、静态检查 |

已确认的版本窗口是 Python `>=3.13,<3.14`、Node `>=24.19,<25`、pnpm 12 与 TypeScript 7；0.x Python 包使用窄 minor 窗口。若注册表、SDK peer dependencies 或 Windows 实测无法满足，T01/T02 提交证据和替代兼容矩阵，不能静默更改已定大版本。精确版本由 `uv.lock` / `pnpm-lock.yaml` 固定。

不引入 Redis、消息队列服务、PostgreSQL、OAuth、云端控制平面或 OS keyring 作为首发前提。消息、幂等记录、Job 与 outbox 由本机 SQLite 支撑。控制凭据使用当前 OS 用户私有文件，宿主运行凭据只进入 bridge 受限存储。

模块不会各自依赖所有库：纯领域层只依赖标准库与稳定共享值类型；SDK、数据库、文件和 Git 都通过应用端口隔离。
