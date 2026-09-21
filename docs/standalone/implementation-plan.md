# 独立运行最小成品实施方案

状态：2026-09-21。M1 十二条最小产品验收标准已通过；R1/R2 已完成第一轮代码落地和真实审计；R3 已接入统一执行工作流、SuspensionSnapshot、Lease 维护和审查回退撤权；R5/R6 已完成 bridge、公开入口、独立安装和真实 daemon 提交窗口 smoke；常驻维护已接入 expired Job lease recovery 与公共 jobs 查询，ResourceService 已按物理 root alias 归一冲突。主动 Job runner 故障矩阵、完整协议矩阵和原设计扩展仍由 R1-R6 后续推进。逐条 M1 证据见 [m1-acceptance-2026-09-21.json](m1-acceptance-2026-09-21.json)。

## 1. 范围与唯一交付目标

M1 的验收对象是一套可独立安装、启动、操作和重启恢复的本机程序。用户不需要启动 Python REPL、直接调用 Service、修改数据库或补写能力证据来完成正常流程。

必须完成：安装包启动 → 初始化协调 Git 项目 → 一个主 Agent和一个 worker 独立接入 → 查看同一任务和黑板 → 显式报告分歧 → 接受同一契约 → 领取资源和 shared workspace → 执行真实文件任务 → 提交结果 → 指定审查者接受 → 用户确认项目完成 → 重启后仍可查询事实、消息、结果和 checkpoint。

交付按以下边界收敛：

| 项目 | M1 必须支持 | 后续恢复完整设计 |
|---|---|---|
| 运行 | Windows 本机、loopback、一个 daemon、一个活动项目；项目可绑定多个目录/仓库 | 同 daemon多项目加载、macOS/Linux完整运行 |
| 身份 | 一次性票据、逐 bridge 会话、私有 token、main/worker/user 分离、重连校验 | 宿主生命周期增强与多宿主产品支持范围 |
| 接入 | 通用 stdio MCP bridge；手动打开两个独立 Agent会话并绑定 | 自动启动、主动唤醒、宿主工具门禁 |
| 任务 | 完整单 owner执行/阻塞/恢复/提交/审查；基本依赖 | 复杂委派、继任和批量生命周期 |
| 认知 | 显式 report、分歧、契约和相关 blocker | 更多规则、proxy policy、复杂风险 fallback |
| 工作空间 | 用户/main明确选择 shared，真实目录、基线和结果验证 | worktree/external完整创建、整合、清理 |
| 恢复 | 同机进程重启、事务回滚、幂等、checkpoint、必要附件 | clone/replica/lineage恢复和共享分叉合并 |
| 观测 | 真实事件审计、任务/Attempt/Result/消息/决定查询、日志定位、错误与运行状态查询 | 多组对照实验及性能研究 |

shared 是本阶段明确支持的路径，不变成所有任务的全局默认隔离策略。请求暂未接通的工作空间类型必须明确拒绝，不能返回 ready。阶段收缩不删除原设计中的表、语义和用户边界。

### 接入简化的工程决定

用户当前要求以能用的本机程序优先。因此 M1 接入条件为：有效用户/已授权主 Agent票据、明确绑定的独立 bridge 会话、正确协议、凭据与 epoch。宿主能力测评不再是本阶段执行任务的前置条件。

实施时在本机 runtime 设置中定义 `admission_profile=local_session`；这是本方案新增的内部配置，当前代码尚无此设置。它只改变本机接入就绪判定，不给 worker 主权限或用户权限。原有宿主能力字段可保留为 unknown，不伪造 supported。独立 bridge 使用由本机启动描述绑定的随机会话 ID，不能拿 cwd 充当身份；原生对话 ID可作附加绑定。新对话新接入，resume只有持有原私有凭据并通过 nonce/epoch 校验才可延续。不能将父 Agent 内部临时子代理直接当成项目成员。

本节是响应用户当前优先级的阶段性工程选择。R1/R5 实施时必须同步接入 Schema/服务设置/测试/文档；不在现有代码中偷偷把 `missing_admission_capabilities()` 改成永远成功。

## 2. 保留的技术与目录

继续使用仓库现有 Python 3.13、FastAPI/Uvicorn、Pydantic、Typer、SQLite、SQLAlchemy/Alembic、jsonschema、RFC8785；bridge 使用 TypeScript、Node和已安装的 MCP SDK。具体依赖版本沿用锁文件。无需新服务、Redis、PostgreSQL、消息中间件或新的 Agent 框架。

最小实现采用现有 `ProjectDatabase/UnitOfWork` 的 sqlite3 事务基础，按模块提供 SQL repository；Alembic 管理迁移。不得让 SQLAlchemy Session和 sqlite3 各自开启一个所谓“同一命令”的事务。继续保留 SQLAlchemy 依赖不等于强制改用第二套连接管理。

预期变更位置如下；是待建路径，不表示文件已存在：

```text
src/tsunagou/
  bootstrap/container.py              # 所有服务、项目DB、端口和runner的唯一装配
  bootstrap/runtime.py                # daemon/project runtime、启动关闭、锁和恢复
  bootstrap/settings.py               # 已登记本机参数和来源
  cli/app.py                          # 命令参数与输出；删除直接 new application
  cli/client.py                       # 同一个daemon的HTTP客户端、凭据私读
  api/app.py                          # lifespan、错误映射、已注册routes
  api/routes/{projects,agents,...}.py  # 各模块既有公开契约
  interfaces/runtime.py               # DTO规范化、同一事务dispatcher
  application/workflows/              # 只组合模块端口，无自有领域表
  application/queries/blackboard.py   # 单ReadSnapshot组合查询
  modules/<module>/
    domain/                           # 从现有文件迁移纯规则和状态机
    public/                           # 跨模块DTO与端口
    application/                      # 本模块handle/query
    infrastructure/                   # 本模块SQLite repository
  platform/db/{sqlite.py,migrations/} # 单UoW、迁移、writer锁
  platform/checkpoints.py             # 保留物化/校验算法，接入Jobs
  generated/protocol/                # 真正生成每个使用中的DTO
  protocol_data/                     # wheel内Schema/registry/OpenAPI
packages/bridge-server/src/           # stdio入口、接入、typed tools
packages/bridge-sdk/src/              # HTTP客户端、重试、同步、续租
tests/integration/standalone/         # 启动真实daemon的产品行为测试
tests/fault_injection/               # kill进程、提交窗口和物化失败
tools/dev/audit_standalone.py         # 已有：当前缺陷复现器
tools/dev/smoke_standalone.py         # 待建：成品端到端执行器
tools/dev/package_smoke.ps1          # wheel/npm 离开源码树安装与启动烟测
```

无需第一天移动全部八模块。逐模块迁移时，必须同一提交修复 import 和 tests；不能同时长期保留 `modules/tasks.py` 与具有不同实现的 `modules/tasks/`。跨模块调用最终走 public，workflows 不读写其他模块字典或私有 `_save()`。

## 3. 分六个实施包执行

每个包关闭标准是功能断言通过。原 T 编号是关联责任，不等于依赖已经满足。顺序 `R1 → R2 → R3 → R4 → R5 → R6`；不要跳过 R2 先补更多内存 handler。

### R1：协议与独立安装入口（T01/T03/T16）

最小故障：wheel缺少registry；公开Schema、手写PAYLOAD_FIELDS和handler参数不一致；CLI调用`protocol_version=1/schema_digest=sha256:x`仍通过。

实施：

1. 将 registry、所有实际使用的Schema及OpenAPI作为包内资源构建，使用 `importlib.resources` 定位。修改 `pyproject.toml` 和所有 `parents[3]/protocol` 读取处，不能依赖cwd或源码checkout。
2. 修复 codegen：以显式 Schema为DTO真相；Markdown目录用作权限/路由登记的校验输入。当前生成器去掉`?`后又把全部字段设为required，复杂字段生成`{}`；这些必须改掉。不要运行旧生成器覆盖已补完整的Schema。
3. 首先补齐 M1 命令的 request/response/查询Schema，精确区分path参数、payload、envelope执行上下文。`task.create`返回draft，不含创建时自动ready/publish。
4. 修复`PAYLOAD_FIELDS`与Schema分叉：由同一规范生成校验器和MCP工具。flat compatibility入口规范化task_id等路径参数后进入同dispatcher，不拥有另一种业务语义。
5. 落实协议/digest检查和RFC9457错误；新增主对象更新必须If-Match，保持原设计的401/403/409/412/428区分。
6. 生成当前bundle及确切N-1映射；未支持的旧格式明确拒绝，不写“兼容”后直接忽略版本。

出口：安装到临时venv，cd到别处仍能构建application；错误版本/未知字段/缺revision在任何变更前失败；生成DTO有具体字段类型。此时尚不能声称完整协作可用。

### R2：常驻daemon、统一SQLite和真实CLI（T04/T05/T06/T07/T16）

最小故障：HTTP用内存Service、CLI另建Service；事实不能跨重启保持、不能事务回滚或幂等。

实施：

1. 装配一个ProjectRuntime，项目路径固定到`<coord-root>/.tsunagou/local/state.sqlite3`。没有已初始化项目时明确拒绝项目命令，不生成内存默认项目。
2. daemon使用进程寿命的项目OS独占锁、单writer队列、统一UoW；第二个进程打开同项目即失败。现有数据库方法内短期文件锁不能替代daemon生命周期锁。
3. 建八模块M1事实表，连接handler用repository。内存仅作请求内对象，不再有独立持久“真相”。身份、Grant、消息也迁移，不能JSON和SQLite双写。
4. CLI的enroll/appoint/decision/operation全部经HTTP到同daemon；新增真实`daemon start/stop/status`、`--project`、必要list/show。连接失败退出5，未知对象404；取消固定`[]/submitted/unknown/ok`成功占位输出。
5. `ProjectDatabase.dispatch`进入原子执行路径。认证/当前epoch检查先于幂等命中；同键同语义返回旧结果，异语义409；主对象revision检查在幂等命中之后。
6. 实现server lifespan启动恢复和优雅停止。启动轮换runtime epoch，撤旧execution Grant/Lease，将未结束执行和旧 claim 转为历史 Attempt、Task 回到 `open` 公共队列（不宣称进程已经停止）。接入身份可恢复，写代码必须重新claim/preflight/start；原 owner 可通过历史证据继续协调，但不是其他 Agent 领取任务的前置条件。
7. 正常查询用只读快照和query port，提供project/tasks/agents/authority/decisions/operations/blackboard。没有数据库就不报告业务健康。
8. 对旧JSON目录做显式一次性导入：先备份，记录源digest/迁移版本，导入在事务内；校验ID/关系失败则保留原件并失败。不存在的旧Task/Contract不能凭Grant反造出来，旧execution Grant一律失效。

出口：重启不丢Task/Contract/Message，CLI票据立即可用；同command重试只一份事实；事务失败不留部分Task/Grant/Event；第二writer无法启动。F01/F02/F05/F11–F14解决。

### R3：任务状态机与主从边界（T06/T08/T13/T15）

最小故障：worker可block/resume别人的任务；HTTP绕过编排start；失败响应后Task已running。

实施：

1. 增加Task执行scope、验收policy和依赖等原设计字段；draft→ready→open分别对应独立命令；保留父任务导航与blocks依赖的区别。
2. `block/resume/progress/submit`必须核对当前owner/session/attempt/epoch。resume只恢复原owner的可恢复Attempt；换owner走明确recovery/succession，不能在resume里偷偷new Attempt抢占。
3. 统一为一个PreflightResult：preflight_id、attempt_id、input_digest、各领域revision、blockers、有效状态。删除两个同名但不同含义的事实来源。
4. HTTP handler只调TaskExecutionWorkflow。start事务内重新读取owner、scope、reports、契约、blocker、workspace、完整Lease；必需项缺失就是blocked，不能默认True或`None`视为ready。
5. 全部检查成功后同事务写Task/Attempt running、execution Grant、事件。attempt不匹配等失败必须零副作用。preflight不是永久许可。
6. block/submit/cancel/会话结束在同事务撤执行Grant、释放Lease、更新Attempt。block必须保存SuspensionSnapshot；用户等待不设deadline，不周期改failed。
7. submit固化TaskResult和ReviewRound；指定reviewer获得R/task_review Grant。用户CLI不借main token代执行；main只有被指定reviewer才可accept。changes_requested关闭旧Attempt，重新发布创建新Attempt。

M1 的 scope 采用一个可选、结构化的最小形式：`task.create.execution_scope` 可以包含 `digest` 和 `resources`；每项资源使用与 `resource.intent` 相同的 `kind/root_id/segments/mode`。path 规则按同一 `root_id` 的目录前缀允许子路径，mode 必须一致；named 资源必须精确匹配。scope 请求兼容一个只含 `roots` 的根级 shorthand。没有 execution scope 的历史任务保持兼容，不推断额外范围；提供 scope 后，越界 intent 在创建 Lease 前以 `task_scope_denied` 拒绝。`task.scope.resolve` 批准新 scope 会递增 `scope_revision` 并撤销旧 execution Grant，后续必须重新 preflight/start。

出口：F03/F06–F09解决；运行中并发claim最多一owner；错误身份、陈旧版本/epoch被拒；任务可走到completed，项目仍active，等待用户整体确认。

### R4：认知、资源、工作空间形成实际闭环（T09/T10/T11/T12/T13）

实施：

1. 认知报告校验task/attempt/author关系，保存boundary、understanding、assumptions、uncertainties、claims和input revisions。superseded报告不当作当前理解。
2. 分歧比对限定同项目、同subject和相关当前报告；记录两侧report refs；提供list/show/resolve。主Agent裁决语义与受影响动作，内核只检查结构、主体、版本和契约接受。
3. Contract与相关task/subject关联；required slots全部按同一proposal digest接受才生效。proposal改变或参与者变化使旧接受失效。仅报告存在不等于分歧已解决。
4. resources落实intent/acquire/renew/release；校验有效scope；同物理路径alias归一；整组资源获取失败全部不授予。claim/preflight可预留，blocked释放。
5. background维护到期：一个事务内expired Lease、撤Grant、旧 Attempt orphaned、Task 回到 `open` 公共队列、事件和通知。Lease 只约束当前执行 Attempt，不约束 Task 本身；任何后来加入且有基础权限的 Agent 都可重新 claim。bridge每30秒续running Lease，默认TTL120秒；claimed预留过期则重新申请，不能假装已有X执行身份续租。
6. workspace.select由main明确选择shared。prepare创建Operation，Job只读扫描实际roots/Git和文件摘要；把核验过的baseline和revision登记后ready。Git mutation仍由main。
7. task.start核对baseline输入版本；workspace.result采集changed paths、patch/artifact及验证引用。允许Agent预期改动；无法归因的改动记录为观察，由main处理。至少在准备、执行前和结果/整合检查点重验，不把缺watcher写成实时保护。
8. 附件使用现有流式blob算法，新增持久上传intent/ref；领域权限控制读取。TaskResult必须引用本Attempt的workspace result与有效验证记录。
9. 黑板在同一ReadSnapshot中返回任务、reports、契约、分歧、Lease、workspace和blocker；私信只对接收者可见，主Agent无自动旁路。

出口：main+worker围绕同一字段提交不同理解，协商后同意同一契约，worker才可start；重启后仍能查询协商；相交任务等待、无关任务可继续；提交的真实文件patch可取回且hash相符。

### R5：可操作的Agent接入、用户决定与恢复（T14/T15/T16/T17）

实施：

1. 整理bridge-server复用bridge-sdk，去除第二套手写工具、硬编码digest及“内容相同永远同command_id”的逻辑。每次用户/模型动作生成新command_id；同一次动作网络重试保留ID。不同时间发送相同内容的两条消息可以是两次动作。
2. 提供逐会话bridge配置生成器。CLI从daemon申请ticket，私有交付给本机bridge；bridge启动兑换。用户只向宿主配置非秘密启动描述路径，不手填conversation_id或向模型粘贴token。
3. 将接入结果非秘密agent_id/session_id/角色回报用户和模型；用户通过U接口任命main。两次新接入不能共享session文件；resume读取原私有记录并用nonce/epoch与daemon验证。
4. local_session接入按本方案第1节落地；宿主报告不阻塞本机协作。保留ticket、协议、真实持有凭据和主体边界校验。
5. MCP工具覆盖M1命令及query工具，返回精确Problem；能力不足的动作不在tools/list冒充可调用。attach/resume/任务边界读取黑板和增量收件箱；先呈现再ACK，不把ACK当业务回答。
6. UserDecision与CompletionProposal归projects模块；workflows只调用端口。主Agent提出重大决定，user通过CLI resolve精确revision/digest。解决不自动start；相关owner显式恢复，无关任务不阻塞。
7. checkpoint由真实Operation/Job驱动模块export；本机私有状态不进入shared文件。项目完成确认同事务写completed+checkpoint Operation，物化失败保留completed与错误，不能丢失用户结论。
8. 观测模块消费已提交事件，持久化审计投影和处理水位；提供query，必要日志关联command_id/attempt_id/event_seq；不记录私有token和消息全文。

出口：人只需CLI启停/接入/任命/重大确认，Agent使用实际MCP工具完成工作；停止bridge会话再恢复可读原任务及消息；checkpoint/审计能够用于查故障。

### R6：封装、回归和独立交付（T01/T16/T23）

实施：

1. Python wheel包含协议资源和CLI入口，Node产物有可启动的stdio bridge，lockfile冻结；提供一条安装命令和真实help。
2. 从任意cwd启动daemon；endpoint manifest包含instance/PID/port/start time，control secret另存用户私有文件。默认随机空闲loopback端口，日志不含secret。
3. 新增`tools/dev/smoke_standalone.py`与`tests/integration/standalone/`，测试只走CLI/HTTP/MCP公开入口，不直接new领域服务。包含下节所有M1断言。
4. 故障测试运行真实子进程：commit前kill、commit后响应前kill、Job物化中断、重复消息、旧会话/epoch、两个writer、用户未回复、文件在检查点间变化。
5. 独立临时venv安装wheel，断开源码导入路径，运行同一场景；打包脚本不能靠本机editable install补齐文件。
6. 改`doctor`为真实配置/DB/锁/任务恢复结果；未实现命令退出明确错误。最终用户文档中的命令逐条执行一次，并记录结果。

出口：M1的全部功能断言通过；没有任何“打印成功但未落库”的路径；用户能按操作单完成协作及重启恢复。宿主正式支持与实验报告单列，不参与此判断。

## 4. 数据与事务的具体约定

每个模块仍拥有原设计表，不建一个`all_state_json`大字段保存所有对象。允许claims/payload等版本化结构用canonical JSON，但身份、FK、revision、状态与索引字段必须独立列出。

| 所有者 | M1最小持久对象 | 必须约束 |
|---|---|---|
| projects | project/lineage、roots/bindings、policy/ceiling、UserDecision、CompletionProposal、Grant | root物理身份；scope子集；决定revision/digest；user-only |
| agents | agents/sessions/tickets/authority、messages/deliveries/obligations | 单次ticket；唯一活动session；recipient权限；消息不重投副作用 |
| tasks | tasks/attempts/preflights/progress/results/reviews、scope requests | current Attempt唯一；owner不变；result与review精确关联 |
| cognition | reports/discrepancies/resolutions/contracts/proposals/acceptances | 同project关系；proposal摘要包含participants；slot唯一 |
| resources | intents/lease sets/leases/waits/observations | conflict/alias；整组原子授予；epoch与scope绑定 |
| workspaces | decisions/instances/baselines/results/git requests/integrations | Attempt绑定；baseline/result摘要；主Agent Git操作归属 |
| durability | commands/events/outbox/operations/jobs/checkpoints/uploads/blobs | 幂等四元组；事件单调；Job租约；hash/长度 |
| evaluation | audit projection/cursor/basic metrics | 只消费已提交事件；可重建；无业务写权限 |

旧authority.py把Grant也放在agents服务。迁移到原设计projects所有权，agents只持有认证/主身份；通过projects授权端口发Grant，不能留下两张可独立授权的表。UserDecision等从LifecycleService内存移回projects，同理。

写入统一签名：

```python
handle(command: TypedCommand, ctx: PrincipalContext, uow: UnitOfWork) -> CommandResult
query(query: TypedQuery, ctx: PrincipalContext, read: ReadSnapshot) -> TypedView
```

一个mutation的次序固定为：传输校验 → 鉴权 → 项目writer/BEGIN IMMEDIATE → 事务内身份及epoch再验 → 幂等查重 → policy/关系/scope/revision/blocker → 领域写入/Grant/Lease/event/outbox → 提交 → 返回。失败全部rollback，不能先变内存再靠SQL回滚“修复”。

Git、文件扫描、HTTP、用户/Agent等待不放事务里。先记录Operation/Job，commit后执行外部I/O，再用expected revisions核验并提交结果。外部动作执行与回报之间崩溃记outcome_unknown；主Agent或用户在既有权限范围内处置，不盲重。

共享project.toml只保存逻辑描述，绝对路径与本机绑定放local config，动态事实只进SQLite；旧project.json作为迁移输入，成功导入后保留备份并停止写入。SQLite schema、协议bundle和shared format分别版本化，不共用一个版本号。

## 5. M1公开入口清单

URI和主体沿用[命令目录](../implementation/command-catalog.md)；表中的集合只是明确本阶段必须接通的既有命令，不另建缩写动作或超级用户。

| 流程 | 必须接通的命令/查询 | 关键结果 |
|---|---|---|
| 初始化和权限 | project.initialize；project查询；root.register/root.bind/repository.register（M）；roots/repositories查询；ceiling.set（U） | root登记、物理绑定和仓库身份可读可验证 |
| 接入 | agent.ticket.create.user、agent.enroll、session.reconnect/rebind/end、authority.appoint/revoke；agents/authority查询 | 两个独立Agent，U任命main |
| 任务准备 | task.create/ready/publish/claim/preflight/start；task.list/show、attempt/preflight查询 | preflight是准备，start才授权 |
| 协调和结束 | task.progress/block/resume/submit；task.review.accept/request_changes；task.cancel_request/cancel_ack | owner约束；review完成Task |
| 认知 | cognition.report、discrepancy.create/advance/resolve、contract.propose/accept/reject/withdraw；对应集合查询 | 各方接受同一digest |
| 资源 | resource.intent/acquire/renew/release/wait.cancel；黑板的Lease/blocker部分 | 冲突和过期约束 |
| 工作空间 | workspace.select/prepare/result；workspaces/baseline/result查询 | shared实际文件基线及结果 |
| 用户决定 | user_decision.propose/resolve/cancel；decisions查询 | U确认精确提案；无自动超时 |
| 完成与持久化 | project.completion.propose.main/confirm；checkpoint.create.user；operations/checkpoints查询 | completed+checkpoint操作可查 |
| 文件附件 | artifact.upload.create/finalize/promote；PUT content、GET授权bytes | patch/测试结果可读取 |
| 通信/观测 | message.send/respond、inbox.claim/fetch/presented/ack/defer；blackboard/events/audit查询 | 同一数据源；权限一致 |

当前查询registry只列出一部分名称，R1必须把目录中本阶段所需查询注册并生成Schema；不能用一个`query(any_sql)`替代。root只有M动作，用户CLI不创造`root.register.user`；初始协调root由project.initialize建立，额外root由main在用户ceiling内登记。

HTTP：`P=/api/v1/projects/{project_id}`；正式REST按目录映射；保留flat入口仅用于旧bridge兼容，payload里的对象ID必须归一到相同目标和权限校验。成功响应携带command_id/result/revisions/event_seq/replayed与已定materialization/operation字段；不能仅返回command_hash冒充领域revision。

MCP：每个进程一份私有凭据；调用同dispatcher语义。M1可沿用现有stdio→HTTP桥，项目MCP Streamable HTTP共享入口在后续补齐，不让它阻止已经能用的stdio流程。两种传输未来不各造状态机。

### 校验与错误矩阵

| 输入/状态 | 对外结果 | 必须断言 |
|---|---|---|
| 未知协议/digest、字段类型错误 | 400/422 | 无业务写入 |
| 无效token/旧连接 | 401 | 无领域handler副作用 |
| worker操纵main任务、接管、签用户决定 | 403 | owner/decision不变 |
| task/contract不存在 | 404 | 不生成悬空记录 |
| 同ID不同输入/非法状态/资源冲突 | 409 | 保留原命令和状态 |
| 缺revision/旧revision | 428/412 | 无覆盖写入 |
| preflight依赖变化或未满足 | 409 condition_stale / 423 action_blocked | 无新Grant，Task不running |
| 队列满/服务暂不可用 | 429/503 | 原command_id受控重试 |
| 用户未回答 | 持久pending及相关blocker | 无超时failed/默认批准 |
| 业务已commit但客户端断线 | 重放原结果 | 只一Task/消息/事件副作用 |
| 外部Git结果不明 | Operation outcome_unknown | 不自动重跑Git |

正常案例：main建立任务，worker认领，准备/协商后运行并提交，指定reviewer接受，用户确认项目完成。基础恢复案例：运行daemon被kill，重启仍有任务/契约/消息，执行权需重新准备。拒绝案例：worker给主任务发resume，403且数据库owner不变。

错误做法：CLI new一份TaskService、返回固定success、写多个JSON后宣布完成事务。正确做法：CLI发HTTP到唯一runtime；同SQLite事务更新事实和幂等记录；返回真实状态。

## 6. 最终完成标准

以下全部通过才是M1完成；现有110/29测试保持通过只是其中一部分。

1. wheel+bridge产物在源码树以外启动，CLI真实管理同daemon。
2. 用户创建项目并接入两个独立会话，只有被任命者为main。
3. 主Agent和worker能查询同一项目/任务、收发消息并完成回应义务。
4. 显式认知分歧可见、契约按参与者接受；陈旧契约不能通过start。
5. owner、scope、revision、epoch、Lease、workspace同时约束start；任何失败零部分写入。
6. worker实际创建/修改一个项目文件并运行测试，结果manifest和patch可读取；Task经过review进入completed。
7. 用户手动修改测试文件后，在下个检查点显示观察/基线冲突；既不静默回滚，也不谎称知道修改者身份。
8. 用户决定pending期间只有相关任务blocked；批准不自动start。
9. 用户确认Project completed，checkpoint可验证，失败可查可重试物化。
10. 杀daemon后重启，Task/Attempt/Report/Contract/Message/Result/Decision仍可查，旧执行权不能续写；重试同command无重复事实。
11. 子Agent不能block/resume/submit别人的任务，不能任命main或代用户确认完成。
12. 操作单所有命令无需改库或直接调用Python对象；日志足够定位失败且不含凭据。

## 7. M1之后距离完整设计的工作

M2：多project runtime、完整worktree/external与Git结果核验、handoff/succession、复杂风险/代理接受、lineage/replica/共享checkpoint恢复、完整命令和查询矩阵。M3：多宿主产品兼容、推送/唤醒增强、系统性故障覆盖和对照实验。两阶段仍保留原设计，当前优先交付M1的确定闭环。
