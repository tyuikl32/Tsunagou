# 技术栈与依赖研究

> 核对日期：2026-09-17。
> 本文件记录注册表与本机工具链事实；版本快照不是最终锁定版本。最终实现以 `uv.lock`、`pnpm-lock.yaml` 和兼容矩阵为准。

## 当前工具链

- 本机：Python 3.13.13、uv 0.9.26、Node.js 24.19.0、Corepack 0.35.0。
- Python 3.13 标准库文档不包含 `uuid.uuid7`；既定 UUIDv7 方案需要第三方实现并通过项目自有 ID factory 封装，或未来升级最低 Python 版本。
- 当前规划仍以 Python 3.13 为最低版本，不能为了标准库 UUIDv7 静默改为 Python 3.14。

## Python 注册表快照

数据来自 PyPI JSON API。所有下列包在注册表元数据中声明的最低 Python 版本均不高于 3.13。

| 用途 | 包 | 2026-09-17 最新版 |
|---|---|---:|
| HTTP/API | fastapi | 0.141.1 |
| ASGI server | uvicorn | 0.53.0 |
| ORM/Core | sqlalchemy | 2.0.54 |
| migration | alembic | 1.20.0 |
| SQLite async driver | aiosqlite | 0.22.1 |
| DTO/settings | pydantic / pydantic-settings | 2.13.5 / 2.15.0 |
| CLI | typer | 0.27.2 |
| HTTP client | httpx | 0.28.1 |
| SSE | sse-starlette | 3.4.11 |
| platform paths | platformdirs | 4.11.9 |
| OS credential store | keyring | 25.7.0 |
| filesystem watch | watchfiles | 1.2.0 |
| cross-platform file lock | portalocker | 4.3.2 |
| schema validation | jsonschema | 4.26.0 |
| TOML preservation | tomlkit | 0.15.1 |
| JCS | rfc8785 | 0.1.4 |
| UUIDv7 candidate | uuid6 | 2025.0.1 |
| structured logging | structlog | 26.1.0 |
| telemetry | opentelemetry-sdk | 1.44.0 |
| testing | pytest / pytest-asyncio / hypothesis | 9.1.1 / 1.4.0 / 6.168.0 |
| Python model codegen | datamodel-code-generator | 0.82.0 |

## TypeScript 注册表快照

数据来自 npm registry `latest` 元数据。

| 用途 | 包 | 2026-09-17 最新版 |
|---|---|---:|
| package manager | pnpm | 12.4.2 |
| compiler | typescript | 7.0.2 |
| OpenAPI types | openapi-typescript | 7.13.0 |
| typed HTTP client | openapi-fetch | 0.17.0 |
| JSON Schema types | json-schema-to-typescript | 16.0.0 |
| testing | vitest | 5.0.1 |
| lint/format | eslint / prettier | 10.10.0 / 3.9.7 |

Vitest 5 当前要求 Node 22.12 或更高，ESLint 10 要求 Node 20.19 或更高；若采用这组工具，monorepo 的最低 Node 版本不能继续模糊处理。

## Node 与包管理器生命周期核对

- Node.js 官方发布计划显示：Node 24（Krypton）于 2025-10-28 进入 LTS，计划在 2026-10-20 进入 Maintenance，2028-04-30 结束支持。
- Node.js 24.21 文档仍将 Corepack 标为 Experimental，并明确说明 Node.js 25 起不再随 Node 发行 Corepack；后续版本必须安装用户态 Corepack，不能依赖 Node 的捆绑副本。
- pnpm 12 的 `devEngines.packageManager` 支持版本范围，解析出的 pnpm 版本会记录到 `pnpm-lock.yaml` 的 `packageManagerDependencies` 并在仍满足范围时复用。
- TypeScript 7.0.2 自身要求 Node 16.20 或更高；本项目真正收紧 Node 下限的是 Vitest 5 等开发工具，以及我们对单一、可复现工具链的要求。

来源：

- [Node.js Release Working Group schedule](https://github.com/nodejs/Release/blob/main/schedule.json)
- [Node.js 24 Corepack 文档](https://nodejs.org/docs/latest-v24.x/api/corepack.html)
- [pnpm 12 package.json 文档](https://pnpm.io/package_json#devenginespackagemanager)
- [npm registry: TypeScript 7.0.2](https://registry.npmjs.org/typescript/latest)

## 已确认的首个 TypeScript 工具链窗口

- 首版以 Node `>=24.19 <25` 为受支持范围；固定开发/CI 基准版本，并同时验证 24.x 最新补丁。Node 26 转为 LTS 后，经四适配器回归再扩展兼容范围。
- 使用 pnpm 12；仓库同时声明 `packageManager` 的精确版本和完整性哈希、`devEngines.packageManager` 的 `>=12 <13` 范围，并提交 `pnpm-lock.yaml`。引导脚本安装固定用户态 Corepack，不依赖 Node 捆绑 Corepack。
- TypeScript 7 使用 strict、ESM 和 NodeNext；适配器包不得混用 CommonJS。首个声明范围固定在 `>=7.0 <7.1`，实际解析版本由锁文件固定。
- `datamodel-code-generator` 只生成 Python Pydantic 协议模型；`json-schema-to-typescript` 只生成 TypeScript 领域协议类型；`openapi-typescript` 与 `openapi-fetch` 只生成/承载 HTTP 端点类型和客户端。生成器之间不互相覆盖文件。
- 所有 codegen 采用固定命令和稳定排序；CI 重生成后必须保持 Git 工作树无差异。

## 已确认方案

- 声明文件使用受控兼容范围，`uv.lock` 与 `pnpm-lock.yaml` 精确锁定解析结果；升级依赖必须单独运行迁移、codegen 和 Windows 回归。
- 共享 DTO 与事件以 JSON Schema 2020-12 为源，生成 Pydantic v2 与 TypeScript 类型。FastAPI OpenAPI 使用同一模型，再生成提交 Git 的 TypeScript HTTP 类型/客户端。
- Python 3.13 使用固定版本 `uuid6`，只通过项目自有 UUIDv7 factory 调用；领域代码不直接依赖第三方包 API。
- 不直接采用“注册表 latest”作为约束；先做最小可运行 spike 后固定首个兼容窗口。

## 后续验证

- 对 `rfc8785` 和 `uuid6` 运行 RFC 测试向量、跨 Python/TypeScript 哈希一致性与时间回拨测试。
- 验证 `sse-starlette` 在 Uvicorn、Windows 事件循环、断线取消和 Last-Event-ID 下的行为。
- 验证 SQLAlchemy async + aiosqlite 在 WAL/FULL、单写队列、online backup 与 Alembic 迁移时的锁行为。
- 选择并固定 JSON Schema/Pydantic/TypeScript codegen 命令，保证同一输入产生字节稳定的提交产物。
