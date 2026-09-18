# 架构、模块所有权与事务边界

## 部署和目录

一个用户级 daemon，绑定 loopback，管理多个 project runtime。每项目一个 SQLite 文件、一个单写队列、一个 OS 独占锁；同一进程内并发读。运行时按请求/连接/后台 Job 惰性加载，加载后保持到 daemon 退出、归档卸载或 unregister，不增加空闲卸载计时器。启动扫描已注册项目的未完成 Job/outbox，不等待用户打开项目才恢复持久工作。

```text
src/tsunagou/
  bootstrap/                 # 唯一依赖装配入口
  api/ cli/                  # HTTP 和 CLI 外壳
  application/workflows/     # 跨模块编排，没有自有领域表
  application/queries/       # 黑板等组合查询，没有第二真相
  shared_kernel/             # ID/revision/clock/hash/errors/envelope
  generated/protocol/        # 生成的 Pydantic DTO，禁止手改
  modules/{projects,agents,tasks,cognition,resources,workspaces,durability,evaluation}/
    domain/ application/ public/ infrastructure/ api/
  platform/{db,http,os,crypto,git,telemetry}/
protocol/schemas/{common,projects,agents,tasks,cognition,resources,workspaces,durability,evaluation}/
protocol/fixtures/ protocol/openapi/v1/openapi.json
packages/{protocol-ts,bridge-sdk,adapter-codex,adapter-opencode,adapter-zcode,adapter-deepseek}/
tools/{codegen,conformance,dev,docs}/
tests/{unit,architecture,protocol,integration,fault_injection,conformance,benchmarks,manual_live_agents}/
```

Python 一个 distribution；TS 为 pnpm workspace，内部依赖 `workspace:*`。不用八个 wheel、微服务或消息中间件。

## 依赖规则

- domain 只依赖标准库与 shared_kernel 值类型。不能导入 FastAPI、SQLAlchemy、宿主 SDK 或外模块领域对象。
- application 依赖本模块 domain 与抽象端口。跨模块只能调用 `modules.<module>.public`；禁止跨模块 ORM 查询/写入。
- infrastructure 实现端口，拥有本模块表与 repository。迁移由 durability 统筹单线 Alembic，迁移文件标注 owning module。
- API 仅验证 wire、建立 PrincipalContext、映射命令、响应与异常；不能直接访问 repository。
- 公共端口返回 DTO，不暴露 ORM/session。组合层从 bootstrap 取得同一 UoW 与模块端口；不创建通用跨模块 repository。
- evaluation 消费脱敏查询/事件，不得修改 tasks/contracts/Grant 等业务事实。

## 调用约定

公共写端口统一为 `handle(command: TypedCommand, ctx: PrincipalContext, uow: UnitOfWork) -> CommandResult`；公共查询为 `query(query: TypedQuery, ctx: PrincipalContext, read: ReadSnapshot) -> TypedView`。具体 command/query 必须注册，不能接受任意字典动作。模块还可提供规范命名的窄接口，例如 `tasks.get_attempt_context`、`resources.validate_lease_set`、`projects.authorize_scope`；端口返回值固定 Schema，所有者在模块计划中定义。

组合层允许的同步交互：认证取 agents；授权取 projects 并查任务/参与者关系；task preflight 读取 cognition/resources/workspaces 的证据；task state 变更同步撤 Grant/Lease；completion/succession/reset 在一个 UoW 调用各模块写端口；黑板在一个 read snapshot 调用各模块 query port。外部通知和 I/O 一律提交后通过 outbox/Job。

## 写入算法

1. 传输层校验大小/格式/版本；认证建立身份，禁止从 payload 读取 actor。
2. 进入项目写队列并开启 `BEGIN IMMEDIATE`。使用 SQLite WAL、`synchronous=FULL`、`foreign_keys=ON`；busy timeout 默认 5 秒，队列饱和返回可重试 unavailable。
3. 在事务内检查 runtime/session/connection/authority/execution epoch 与当前认证有效性。随后查幂等命令记录；同 key 同 hash 返回持久结果，同 key 不同 hash 返回冲突。已撤权主体不能凭幂等键读取旧受限结果。
4. 新命令执行静态 CommandPolicy、关系/范围、revision、适用 blocker 检查。聚合级 revision 检查在幂等命中之后；重试不因自己已经推进 revision 而失败。
5. 调用各模块公开写端口，更新聚合/投影并递增受影响 revision。分配项目 lineage 内单调 `event_seq`，同事务追加 event、幂等 result、outbox、Operation/Job。
6. commit 后返回。不能在写事务中等待 Agent、用户、Git、文件同步或 HTTP。错误则全部 rollback，无部分消息/Grant/任务结果。

Event 顺序由单 writer 保证，不依赖 UUID 时间排序。内部 worker 使用不可通过公共 API 获得的 `system_job` context，只执行已登记 handler；它不是 user_control 或可签发的“管理员” Grant。

## 持久结构

```text
<coordination-repo>/.tsunagou/
  project.toml               # project/lineage、共享 policy 与 roots 描述
  shared/checkpoints/        # manifest、按模块实体 NDJSON、校验值
  shared/artifacts/          # 显式提升后才共享的内容
  local/config.toml          # 本机 root/repo binding、adapter 设置
  local/state.sqlite3        # 当前运行事实，Git 忽略
  local/artifacts/sha256/    # 默认附件位置，不自动 GC
  local/runtime/             # project lock、临时物化及本机运行元信息
```

用户级目录仅保存 daemon 发现、项目注册索引、控制凭据、日志入口和 adapter installation profile。不得把项目事实唯一存放在那里。共享文件不能包含令牌、绝对路径、活跃 Grant/Lease、worker claim 或私信正文。

## 配置与启动

daemon 读取用户配置 → 加载登记项目描述 → 获得项目 OS lock → schema/version 检查与迁移预检 → SQLite/UoW/module 装配 →恢复 outbox/Jobs → 开放普通写。迁移失败保持诊断与只读恢复入口。

共享 TOML 定义项目 policy；本机 TOML 定义物理绑定；环境/CLI 只覆盖登记的运行参数。权限上限取交集，不能靠配置优先级扩大。动态状态不进 TOML。`config show --effective --provenance` 展示脱敏有效值与来源；`config validate` 只读；无通用 `config set` 绕过领域命令。

`doctor` 校验版本、锁、绑定、checkpoint、DB schema、adapter 能力和 hook 状态，输出结构化 remediation。日志只记录 ID/hash/状态/计数，不默认记录正文或秘密。
