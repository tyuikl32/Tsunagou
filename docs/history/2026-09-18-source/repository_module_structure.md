# Monorepo 结构与八模块所有权

> 核对日期：2026-09-17。
> 状态：已确认；作为所有详细计划、代码生成和 Trellis 拆分的文件归属基线。
> 总体约束：模块设计必须同时满足 [design_and_runtime_principles.md](./design_and_runtime_principles.md)，尤其是“机械内核维护结构不变量、业务判断交给 LLM Agent”的边界。

## 选择依据

- PyPA 建议的 `src` layout 将可导入代码与仓库根配置、工具脚本分开，可以减少开发目录被意外导入造成的测试偏差。
- uv 为项目维护 `.venv` 和 `uv.lock`，`uv run` 会创建或同步项目环境；本项目已决定只支持从源码 checkout 运行。
- pnpm workspace 由根 `pnpm-workspace.yaml` 定义；内部包使用 `workspace:` protocol，可拒绝意外解析为注册表上的同名包。

来源：

- [PyPA: src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
- [uv project layout](https://docs.astral.sh/uv/concepts/projects/layout/)
- [pnpm workspaces](https://pnpm.io/workspaces)

## 候选顶层目录

```text
Tsunagou/
|-- pyproject.toml
|-- uv.lock
|-- package.json
|-- pnpm-workspace.yaml
|-- pnpm-lock.yaml
|-- README.md
|-- src/
|   `-- tsunagou/
|       |-- cli/
|       |-- api/
|       |-- bootstrap/
|       |-- shared_kernel/
|       |-- generated/
|       |-- modules/
|       |   |-- projects/
|       |   |-- agents/
|       |   |-- tasks/
|       |   |-- cognition/
|       |   |-- resources/
|       |   |-- workspaces/
|       |   |-- durability/
|       |   `-- evaluation/
|       `-- platform/
|           |-- db/
|           |-- http/
|           |-- os/
|           |-- crypto/
|           |-- git/
|           `-- telemetry/
|-- protocol/
|   |-- schemas/
|   |-- fixtures/
|   `-- openapi/
|-- packages/
|   |-- protocol-ts/
|   |-- bridge-sdk/
|   |-- adapter-codex/
|   |-- adapter-opencode/
|   |-- adapter-zcode/
|   `-- adapter-deepseek/
|-- tools/
|   |-- codegen/
|   |-- conformance/
|   `-- dev/
|-- tests/
|   |-- unit/
|   |-- architecture/
|   |-- protocol/
|   |-- integration/
|   |-- fault_injection/
|   |-- conformance/
|   |-- benchmarks/
|   `-- manual_live_agents/
`-- docs/
    |-- architecture/
    |-- plans/
    |-- protocols/
    `-- runbooks/
```

这是一个 Python distribution，不把八个模块拆成八个 wheel。TypeScript 包是 pnpm workspace 成员，内部依赖必须使用 `workspace:*`。

## 模块内统一骨架

每个业务模块按需要采用以下目录，禁止为了形式创建空层：

```text
modules/<module>/
|-- domain/           # 实体、值对象、状态机、领域规则与领域事件
|-- application/      # command/query handler、用例、输入输出 DTO
|-- public/           # 其他模块唯一允许导入的应用端口和公共 DTO
|-- infrastructure/   # 本模块表、repository、projector 和外部端口实现
`-- api/              # 本模块 REST router 与 API 映射
```

- `domain` 只能依赖标准库与 `shared_kernel` 的稳定值类型，不依赖 FastAPI、SQLAlchemy、文件系统、Git 或其他业务模块。
- `application` 依赖本模块 domain 和抽象 ports；不得导入其他模块的 infrastructure 或 ORM。
- `infrastructure` 实现本模块 ports，并拥有本模块 SQLAlchemy table/repository/projector；数据库 session 由 Unit of Work 注入。
- `public` 暴露窄的应用 facade/port 和跨模块 query DTO。跨模块同步调用只能指向 `modules.<name>.public`。
- 跨模块异步协作使用提交后的领域事件；事件 payload 来自 `protocol/schemas`，不传 ORM 实体。
- `api` 只做鉴权上下文、协议模型、命令映射、revision/幂等 header 与 HTTP 状态转换，不承载领域规则。

架构测试会扫描 Python import graph：违反 domain 纯度、跨模块深层导入或从 API 直达 repository 时阻止 Windows 发布检查。

## 八大模块所有权

| 模块 | 拥有的核心概念 | 明确不拥有 |
|---|---|---|
| `projects` 项目空间与权限 | Project、named roots、repo registrations、policy、roles/grants、capability limits、archive/delete lifecycle | Agent 会话 token、任务状态、通用数据库引擎 |
| `agents` Agent 接入 | Adapter descriptor、Agent identity、host session、main-agent authority、enrollment/token family、capability snapshot、persistent inbox/delivery | 项目授权规则、任务 owner 决策、宿主厂商 SDK |
| `tasks` 任务调度 | Task、edges/prerequisites、claim、TaskAttempt、preflight summary、acceptance、review/返工/取消/失联状态机 | 认知内容、实际资源锁、workspace 生命周期 |
| `cognition` 认知协商 | EpistemicReport、Discrepancy、ContractProposal/Acceptance、RiskAssessmentRequest/Submission | 最终 IsolationDecision、LLM provider 调用、隐含分歧推断 |
| `resources` 资源协调 | ResourceIntent、resource key、wait queue、Lease、冲突/aging/续租规则 | Git worktree、job execution lease、操作系统权限 |
| `workspaces` 隔离驱动 | driver registry/capability vector、IsolationDecision、WorkspaceInstance、baseline/result manifest、integration/cleanup | 通用任务状态、Git 仓库外的任意工作流 DSL |
| `durability` 持久化回放 | project event sequence/envelope、outbox/materialization、Operation/Job/JobAttempt、checkpoint、shared-file import/export、migration/backup/replay | 其他模块的业务表所有权、通用跨模块 repository |
| `evaluation` 可观测性与评估 | audit/read models、日志/trace/metric policy、token estimates、experiment definition/run/result、故障注入报告 | 领域事件真相、业务状态修改、模型账单推断 |

### 跨边界对象的归属

- `projects` 决定某主体能否执行动作；`agents` 负责证明主体和会话是谁。授权服务通过公开端口组合两者。
- `cognition` 保存主 Agent 的风险请求和建议；`workspaces` 在内核硬约束验证后保存最终 IsolationDecision。
- `resources` 的 Lease 是任务对项目资源的协调所有权；`durability` 的 job execution lease 只保护某个 worker attempt。
- `agents` 拥有 inbox/delivery/ACK；`durability` 提供同事务 outbox 和 materializer 机制，但不能直接改变消息业务状态。
- 各模块拥有自身表；`durability` 维护统一 Alembic revision 链、备份和恢复协议。migration 文件必须标注 owning module。
- `evaluation` 可读取已脱敏的事件/投影并生成报告，不能成为任务、契约或权限的写入口。

## 组合层与平台层

- `bootstrap` 是唯一 composition root：装配配置、数据库、Unit of Work、module facades、worker、driver 和 routers。
- `cli` 调用应用 facade 或经本机 HTTP 调用已运行 daemon；不得复制业务规则。
- `api` 组合模块 routers、异常到 RFC 9457 的映射、认证中间件和 SSE stream。
- `shared_kernel` 只包含 UUIDv7 ID 类型、UTC 时间、revision、event/command envelope、JCS/hash helpers 和少量稳定错误类型。
- `platform` 是技术适配层：数据库连接、loopback HTTP、OS 凭据/路径/进程、加密随机数、Git 子进程和 OTel。业务模块通过 ports 使用它。
- `generated` 只包含 codegen 产物，禁止手工修改；生成文件头记录 schema digest 和生成器版本。

## 协议与生成产物

- `protocol/schemas/<module>/` 是共享 DTO、事件和共享文件的 JSON Schema 2020-12 源；`protocol/fixtures/` 保存跨语言正反例与 canonical hashes。
- Python Pydantic 模型生成到 `src/tsunagou/generated/protocol/`。
- TypeScript 领域类型生成到 `packages/protocol-ts/src/generated/`。
- FastAPI 导出的固定 OpenAPI artifact 保存到 `protocol/openapi/openapi.json`；HTTP 类型生成到 `packages/bridge-sdk/src/generated/http/`。
- codegen 命令集中在 `tools/codegen/`，不得在适配器各自维护不同生成逻辑。CI 重生成后检查工作树无差异。

## 测试归属

- `unit/modules/<module>` 验证纯领域和应用规则；与源模块保持同构。
- `architecture` 验证 imports、表所有权、router/handler/repository 边界和生成文件不可手改。
- `protocol` 验证 JSON Schema、JCS、UUID、OpenAPI 和 Python/TypeScript fixtures 一致。
- `integration` 使用真实 SQLite/Git/loopback HTTP，不启动真实 Coding Agent。
- `fault_injection` 覆盖崩溃窗口、lease expiry、outbox/materializer、迁移和恢复。
- `conformance` 对四个桥接运行同一宿主模拟契约；`manual_live_agents` 保存人工验收脚本与签字记录。
- `benchmarks` 保存微基准和 A/B/C/D 实验 harness；不与普通单元测试混合。

## 仍待细化

- 每个模块的完整实体字段、命令、查询、事件、表和索引。
- public ports 的精确方法签名和允许的跨模块调用矩阵。
- CLI 命令树、daemon bootstrap 顺序与配置优先级。
- Alembic revision 约定、schema/codegen 命令和生成产物 header。
