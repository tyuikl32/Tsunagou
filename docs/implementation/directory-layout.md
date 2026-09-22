# 预期目录与文件责任

这是首发交付时的设计目录，并标注当前已存在的安装与 Agent skill 入口。代码层仍按任务逐步补齐，不预先创建所有空层。下列私有文件名可以在任务内调整；模块名、协议产物路径、公开语义和所有权不能由某个 Agent 自行改变。

## 源码仓库

```text
Tsunagou/
├── README.md
├── AGENTS.md
├── pyproject.toml                 # Python distribution、CLI入口、质量工具
├── uv.lock                        # 精确Python依赖
├── .python-version                # T01核验后固定3.13补丁
├── package.json                   # 固定packageManager、公共TS脚本
├── pnpm-workspace.yaml            # packages/*
├── pnpm-lock.yaml
├── tsconfig.base.json             # strict / ESM / NodeNext
├── alembic.ini
├── src/tsunagou/
│   ├── __init__.py
│   ├── __main__.py                # 转CLI，不另写业务逻辑
│   ├── bootstrap/
│   │   ├── settings.py            # 分层配置与来源
│   │   ├── container.py           # 唯一composition root
│   │   ├── daemon.py              # 用户级daemon启停
│   │   └── project_runtime.py     # 每项目lock/DB/worker/模块生命周期
│   ├── api/
│   │   ├── app.py                 # app factory、lifespan、挂载routers/MCP
│   │   ├── dependencies.py        # 注入principal、runtime、dispatcher
│   │   ├── authentication.py      # 凭据→可信PrincipalContext
│   │   ├── problems.py            # DomainError→RFC 9457
│   │   ├── protocol_headers.py    # 协议版本、digest、If-Match解析
│   │   ├── streams.py             # SSE高水位提示
│   │   └── mcp.py                 # 项目共享服务，每连接独立身份
│   ├── cli/
│   │   ├── app.py                 # Typer入口
│   │   ├── client.py              # control token私有读取与HTTP调用
│   │   ├── output.py              # Rich / JSON / exit code
│   │   ├── enrollment.py          # 接入组合流程，秘密只给bridge
│   │   └── commands/              # project/root/agent/authority/decision等
│   ├── application/
│   │   ├── project_integration.py # 项目本地无秘密入口生成器
│   │   ├── command_dispatcher.py  # 唯一authorize-and-handle入口
│   │   ├── command_policies.py    # 静态注册表，不解释任意策略DSL
│   │   ├── workflows/
│   │   │   ├── enrollment.py
│   │   │   ├── task_execution.py
│   │   │   ├── authority_transition.py
│   │   │   ├── agent_succession.py
│   │   │   ├── project_completion.py
│   │   │   └── lineage_transition.py
│   │   └── queries/
│   │       └── blackboard.py      # 单read snapshot组合，无独立业务表
│   ├── shared_kernel/
│   │   ├── ids.py                 # UUIDv7等稳定值类型
│   │   ├── time.py                # Clock端口和UTC表示
│   │   ├── revisions.py
│   │   ├── digests.py             # JCS、SHA256
│   │   ├── envelopes.py
│   │   └── errors.py
│   ├── generated/protocol/        # 从JSON Schema生成的Pydantic模型
│   ├── modules/
│   │   ├── projects/              # 项目、root/policy/Grant/用户决定
│   │   ├── agents/                # 会话、能力、Authority、消息
│   │   ├── tasks/                 # Task/Attempt/Result/review
│   │   ├── cognition/             # 报告、分歧、契约、风险
│   │   ├── resources/             # 意图、等待、execution Lease
│   │   ├── workspaces/            # driver、manifest、main Git请求
│   │   ├── durability/            # event/outbox/Operation/Job/checkpoint/blob
│   │   └── evaluation/            # 审计投影、指标、实验与报告
│   └── platform/
│       ├── db/                    # SQLite连接、事务底座
│       ├── http/                  # 底层客户端/连接设施
│       ├── os/                    # 路径、physical identity、文件/进程/锁
│       ├── crypto/                # CSPRNG、token hash、cursor HMAC
│       ├── git/                   # 仅只读Git执行allowlist
│       └── telemetry/             # structlog、可选本机OTLP
├── migrations/
│   ├── env.py                     # T04建立，单线Alembic
│   └── versions/                  # 每revision标注owning module
├── protocol/
│   ├── schemas/
│   │   ├── common/                # ID、scope、envelope、problem
│   │   ├── projects/ agents/ tasks/ cognition/
│   │   └── resources/ workspaces/ durability/ evaluation/
│   ├── fixtures/
│   │   ├── valid/ invalid/        # 跨语言验证样例
│   │   ├── canonical/             # 输入JSON与预期JCS/digest
│   │   └── commands/              # 命令允许/拒绝与重放案例
│   ├── prompts/v1/                # 核心提示片段、manifest/digest
│   └── openapi/v1/openapi.json     # HTTP契约生成物
├── packages/
│   ├── protocol-ts/src/generated/
│   ├── bridge-sdk/
│   │   ├── src/generated/http/    # OpenAPI生成客户端类型
│   │   ├── src/{auth,connection,commands,inbox,leases,context,mcp}/
│   │   └── tests/
│   ├── adapter-codex/
│   ├── adapter-opencode/
│   ├── adapter-zcode/
│   └── adapter-deepseek/
├── tools/
│   ├── codegen/                   # 唯一生成入口与schema subset lint
│   ├── conformance/{probes,harness}/
│   ├── dev/                       # 安装/检查/演示辅助与独立烟测
│   ├── install/install.py         # GitHub clone、Python/Node安装、bridge构建、skill安装
│   └── docs/validate_docs.py       # 当前已有的文档校验
├── tests/
│   ├── unit/modules/<module>/
│   ├── architecture/ protocol/ integration/
│   ├── fault_injection/ conformance/
│   ├── benchmarks/ manual_live_agents/
│   └── fixtures/                  # 测试项目，绝非真实用户项目
├── docs/{overview,implementation,decisions,research,history}/
├── .agents/skills/                # 可跨宿主发现的项目级 Agent skill
│   ├── tsunagou-install/          # 从 GitHub 安装 Tsunagou 和 skill
│   └── tsunagou-agent-onboarding/ # daemon/bridge/session 接入向导
└── .trellis/                      # 本仓库开发管理，不是产品协调数据库
```

## 一个模块内部怎样放文件

## 用户项目初始化后的入口

`project bootstrap` 在用户选定的协调根生成轻量、无秘密的项目入口；它不复制本仓库源码：

```text
<user-coordination-root>/
├── AGENTS.md                              # 用户正文 + TSUNAGOU 受管区块
├── .agents/skills/tsunagou-project/
│   └── SKILL.md                           # 项目 discoverability wrapper
└── .tsunagou/
    ├── project.json                       # Project 共享事实
    ├── project-integration.json           # source/version/managed digest
    ├── agent-context.md                   # 主/worker/user和恢复规则
    ├── .gitignore                         # 受管私有运行规则
    └── local/                             # endpoint/token/SQLite/session，默认忽略
```

`project-integration.json` 的 source checkout 路径只是本机诊断提示；GitHub URL、版本和项目相对规范链接才是可移植引用。一个 daemon 的多项目选择仍由 runtime/doctor 的实际配置证明，入口文件不创建全局项目单例。

以 tasks 为例，其余模块按实际需要采用相同边界：

```text
modules/tasks/
├── domain/
│   ├── task.py             # 聚合、状态转换与结构不变量
│   ├── attempt.py          # 不可变owner与可变状态投影
│   ├── acceptance.py       # 固定验收policy，不调用LLM
│   └── events.py           # 领域事件值对象
├── application/
│   ├── commands.py        # 本模块typed handler
│   ├── queries.py
│   └── ports.py           # 本模块依赖的repository/外部能力抽象
├── public/
│   ├── __init__.py        # 明确导出清单
│   ├── commands.py        # 跨模块可调用的窄写端口
│   └── queries.py         # AttemptContext/TaskScope等稳定DTO
├── infrastructure/
│   ├── tables.py          # 只定义tasks_*表
│   ├── repositories.py
│   └── checkpoint.py     # 本模块导出/导入profile
└── api/router.py          # 将HTTP映射到同一dispatcher
```

Schema生成DTO是wire边界类型；domain可有自己的值对象，转换必须显式且不改语义。没有业务需求时不复制一套同字段class。跨模块返回public DTO，不能传SQLAlchemy session或ORM实体。

| 调用者 | 可以依赖 | 禁止 |
|---|---|---|
| domain | stdlib、shared_kernel稳定值 | FastAPI/SQLAlchemy/宿主SDK/其他模块内部 |
| module application | 本模块domain、抽象ports、其他模块public | 其他模块tables/repository |
| module infrastructure | 本模块ports、platform技术设施 | 越权写其他模块表 |
| workflow | 各模块public、同一UoW | 独立复制任务/权限状态 |
| query composition | public query ports、同一ReadSnapshot | 任意跨模块SQL、绕过源字段权限 |
| adapter | bridge-sdk、生成协议、宿主官方API | control token、服务器业务状态机副本 |

## 开发仓库与用户项目的数据不要混放

用户可在 `D:\Work\ControlRepo` 保存协调中心，而代码位于 `D:\Work\Backend`、`E:\Web\Frontend`。只有第一个根是协调仓库；另两个通过Root/Repository登记。开发本项目的`.trellis/`与产品的`.tsunagou/`作用完全不同。

```text
D:\Work\ControlRepo\.tsunagou/
├── project.toml
├── shared/
│   ├── checkpoints/<digest>/      # manifest+各模块NDJSON
│   └── artifacts/                # 经过显式promote的共享blob
└── local/                        # 整个目录Git忽略
    ├── config.toml               # 本机绝对路径bindings
    ├── state.sqlite3             # 当前领域事实
    ├── state.sqlite3-wal         # SQLite自行管理
    ├── state.sqlite3-shm
    ├── artifacts/sha256/<prefix>/<hex>
    └── runtime/                  # 项目lock、staging/运行元信息

<platformdirs提供的用户state/config根>/
├── daemon/                       # endpoint发现，不含token
├── projects/                     # 本机索引，不是唯一项目事实
├── credentials/                  # control凭据，用户私有
└── adapters/<kind>/<profile>/     # installation、会话私有凭据
```

以上用户目录的内部文件名是布局建议，T01/T06需固定到配置与doctor输出；调用者通过平台路径服务取得，不能手写Windows用户名路径。session token不放进用户项目目录，shared更不能包含可用Grant/Lease/job claim。

## 生成、修改与验收责任

手写：Schema源、领域代码、命令策略、迁移、模板源和fixture期待值。生成：Python/TS协议模型、OpenAPI、HTTP类型；生成物进入Git但不得手改。运行产物：SQLite/WAL、token、临时文件、宿主profile秘密；不作为源码提交。

T01验收目录/构建；T03验收生成边界；T04验收迁移/存储；各模块任务验收owning table/public ports；T16验收HTTP/CLI/MCP组合；T17–T21验收adapter边界。外部设计依据见[官方参考](references.md)，完整搭建顺序见[搭建指南](build-guide.md)。
