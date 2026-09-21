# 从空工程到首发闭环的搭建指南

本指南保留原 T01–T24 从空工程搭建完整设计的步骤，原任务均已关闭归档，历史顺序见[旧路线图](roadmap-legacy-2026-09-18.md)。当前已有原型，应按 [M1 / R1–R6](roadmap.md)及各任务 PRD 修复，不从 T01 重新搭建。当前可运行和待交付的命令分别见[调试执行单](../standalone/debugging-runbook.md) A/B 部分。

每个阶段都要留下可复用产物和验证结果。完成一个阶段，不等于后续宿主/恢复功能已通过。目录路径见[详细目录](directory-layout.md)；命令和权限以[命令目录](command-catalog.md)为准。

## 0. 接手任务时先恢复共同认知

1. 读取本仓库AGENTS、原则、当前任务prd/design/implement和JSONL；先查看git状态，保留已有用户改动。
2. 查看task-plan与`meta.depends_on`。依赖完成以产物和验收证据判断，不以文件夹存在判断。
3. 找出本任务拥有的表、公开命令和调用端口；涉及其他模块的改动先写到design的事务清单。
4. 标记每项信息是已确认边界、工程默认、待实测假设还是历史方案。不能把历史候选重新带进当前代码。
5. 使用Trellis start开始当前实施任务；阶段结果写journal，更新design使其与实际一致。

现在可执行：

```powershell
git status --short
python .trellis/scripts/task.py list
python .trellis/scripts/task.py validate .trellis/tasks/09-20-r1-protocol-package
python tools/docs/validate_docs.py
```

## 1. 建可复现的语言与包边界（T01）

前置：无产品依赖。先记录 `python --version`、`uv --version`、`node --version`、`pnpm --version` 和OS，再核对选定窗口；不因为本机有别的版本就静默改项目范围。

按序建立：

1. `pyproject.toml`声明一个Python distribution，`src/tsunagou`布局，Python `>=3.13,<3.14`。产品console script固定`tsunagou`，指向CLI应用入口。
2. 根package.json、pnpm-workspace、tsconfig.base以及六个TS包。Node `>=24.19,<25`，pnpm12，TS `>=7.0,<7.1`；内部包用workspace协议。精确版本与完整性由锁文件记录。
3. 设置Python运行依赖/开发依赖、TS协议/bridge/adapter依赖；避免各包装一套不兼容生成器。
4. 创建可导入的空composition root、可退出的CLI帮助入口与质量脚本，不先实现八模块的空repository类。
5. 建立测试目录及架构import检查，记录干净Windows安装命令。包目录存在后更新Trellis package配置。

当清单与锁文件已创建，可使用：

```powershell
uv sync --locked
pnpm install --frozen-lockfile
uv run python -c "import tsunagou"
uv run tsunagou --help
```

锁文件尚不存在时先由T01维护者解析生成并审查；不要把`--locked`失败绕过为永久不锁版本。阶段出口：重建环境可复现，架构检查能阻止domain导入框架；记录实际脚本名称与退出码。依据：[PyPA src布局](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)、[uv项目](https://docs.astral.sh/uv/guides/projects/)、[pnpm工作区](https://pnpm.io/workspaces)。

## 2. 提前验证四宿主身份与传输（T02）

此步骤可独立于大部分后端开发。先选官方接入面，再运行小探针；不要先写完整adapter后才发现无可信会话ID。

每个host/profile跑：两个同目录会话→各自新建→原会话resume/compact→clear/fork→bridge重启。保存ID相等/不同的结果与脱敏证据，不能保存原ID到Git。验证typed tools、MCP接入、凭据不进入模型、可选hook/wake/gate是否实际启用。

产物为 `docs/research/host-matrix.md` 与 `tools/conformance/probes/<host>/`。记录具体软件、版本、官方URL、调用面、11项baseline、增强强度、失败复现。unknown不算通过。Python/TS MCP SDK选择由此锁定；参考[MCP传输](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)和[生命周期](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)。

阶段出口：每宿主可行/不可行有证据，不能通过减少身份要求“修复”失败。仅涉及宿主的任务可被阻塞，其余领域内核可继续。

## 3. 把文字语义固定成机器契约（T03）

按依赖顺序生成 common ID/time/digest/scope/error → 项目与身份 →任务/消息 →认知/资源/workspace →持久性/评估DTO。逐条展开command-catalog中的user变体与查询集合；所有mutation必须有唯一policy注册项。

每个字段明确：类型、required/可省略、nullable、默认、最大长度、是否参与JCS、创建者、可否修改、读取权限。state枚举不能由adapter增加同义状态。`runtime_epoch`是UUID；数字epoch不要跟它混用。

建立正反fixtures和跨语言哈希向量；生成Pydantic与TS领域类型；HTTP OpenAPI待router存在后由同一模型导出。不要从Pydantic反推另一份独立业务Schema，再让两份源相互覆盖。

阶段出口：Python/TS相同接受与拒绝、同JCS digest、二次生成零差异；策略registry拒绝缺失或重复command；版本协商区分协议bundle/共享format/DB迁移。依据：[JSON Schema 2020-12](https://json-schema.org/draft/2020-12)、[RFC 8785](https://www.rfc-editor.org/rfc/rfc8785)。

## 4. 先证明事务和恢复底座（T04）

1. 建platform/db连接与项目lock，启用WAL/FULL/foreign keys，每项目单writer；配置注入Clock。
2. 建单线Alembic、UoW与ReadSnapshot；先创建durability事件、command result、outbox、Operation/Job表。
3. 用最小测试聚合验证事务：身份代次检查→幂等→revision/policy→领域变更→event/outbox/result→commit。
4. 建worker持久claim、job lease、重试和effect分类。unknown外部结果只登记，不盲重。
5. 用临时目录和子进程杀进程模拟commit前后崩溃；验证恢复与双writer互斥，再允许上层接入。

阶段出口：状态/事件/result/outbox无部分成功；命令重放不多执行；迁移失败可诊断；写事务不等待网络/文件/用户。依据：[SQLite WAL](https://www.sqlite.org/wal.html)、[PRAGMA](https://www.sqlite.org/pragma.html)、[SQLAlchemy事务](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html)、[Alembic教程](https://alembic.sqlalchemy.org/en/latest/tutorial.html)。

## 5. 项目、身份与真正的权限边界（T05、T06）

先有project/root/binding与ceiling交集，再接入ticket/session/Grant。以用户已准备的临时Git仓库测试init，允许尚无commit；从初始化开始写入项目中心，不能先“临时放全局”后续再搬。

root注册分别测试逻辑ID、物理绑定、case、symlink/junction、嵌套别名。认证只得到PrincipalContext；授权在UoW中用静态policy检查当前事实。main任命与worker接入是两条权限路径。

接入流程按[协作实例](coordination-walkthrough.md)：票据消费、身份/能力快照、独立session token、ready或degraded；重连CAS推进connection epoch；token交付丢失走rebind而非造新Agent。故意用子session调用appoint、父Attempt、他人inbox，全部拒绝。

阶段出口：知道project ID或声称main均不授予权限；旧epoch在commit前被拒绝；私有秘密不进共享导出、日志、CLI JSON或prompt。

## 6. 建两个可单独验证的业务分支（T07、T08）

消息分支：Message/RoutingSnapshot→Delivery pull lease→fetch→ACK→ResponseObligation。先写断线/重复fetch/ACK和sender/recipient可见性测试，再加SSE高水位提示。消息ACK不触发契约或任务接受。

任务分支：draft/ready/open→原子claim→唯一Attempt→block/resume准备态→submit/review→终态。先用fake public evidence port验证状态机；fake只用于模块测试，不能算资源/workspace已集成。父子导航与blocks依赖分开，父终态不级联。

阶段出口：并发claim唯一owner；主权限不能代替owner提交；返工新Attempt；没有资源/认知证据时start不能被简单stub“永久允许”。

## 7. 资源、认知、隔离和附件（T09–T12）

资源先实现scope子集、冲突矩阵和all-or-none，再接TTL/续租/过期；认知先显式报告与确定性规则，再做proposal/接受和proxy，最后风险请求/建议。双方各自只保存所属事实。

workspace先driver候选与IsolationDecision，再baseline/result和main Git请求；所有Git mutation由main。没有main时pending，不让daemon代跑worktree add。附件先upload intent和领域授权，再流式存储/finalize，再显式promote；hash不是权限。

阶段出口：scope冲突可解释；改变proposal参与者使旧接受无效；baseline陈旧拒绝start/integrate；私信附件不能自动共享；finalized blob无自动GC。依据：[Git worktree](https://git-scm.com/docs/git-worktree)。

## 8. 打通第一个可信闭环（T13）

用一个main、两个worker的simulator场景串起：创建两个任务→各自claim→报告字段理解不一致→分歧→契约共同接受→风险/隔离→Lease/preflight/start→结果→review。每条命令记录哪个principal、Grant、revision、事件与状态改变。

先故意修改contract revision、scope digest、workspace baseline，使旧preflight失败；再验证重新准备可恢复。用户待决场景保持相关Task blocked，无关worker继续。此阶段可以证明内核闭环，仍不能宣称四宿主真机兼容。

## 9. 共享恢复和重大生命周期（T14、T15）

各模块export/import所有者先提供profile，再做checkpoint排序/哈希/staging/原子切换；在Windows注入写一半、rename前后、DB水位推进前后崩溃。读Git只核验heads/tags可达锚点，不把reflog或远端报告当同等证据。

随后实现UserDecision、完成/归档/重激活、handoff/succession、lineage reset。必须测试“用户完成已commit但checkpoint失败”：Project仍completed，依赖证据的动作blocked。reset创建新lineage、unassigned，无旧运行权；未知Operation只追加Resolution。

阶段出口：完整恢复测试，而不是仅能生成JSON文件。终态任务不复活，非终态恢复无current Attempt，需要main显式restore_open。

## 10. 暴露统一入口（T16、T17）

模块router→dispatcher→同一policy/UoW；MCP仅投影允许的Agent命令；CLI用U入口。先验证HTTP/工具同语义/错误/hash，再完成用户向导。

黑板一次ReadSnapshot组合；提示按attach/resume/task边界最小注入；shared bridge负责token注入、epoch、重试、消息去重和Lease。adapter不能复制服务端授权或状态机。CLI完整映射见[CLI契约](cli-contract.md)，用户示例见[手册](../overview/cli-http-manual.md)。

阶段出口：OpenAPI可重复生成；同命令REST/MCP一致；CLI示例全部由contract fixture驱动，无未注册user权限。依据：[FastAPI多文件应用](https://fastapi.tiangolo.com/tutorial/bigger-applications/)、[Typer教程](https://typer.tiangolo.com/tutorial/)。

## 11. 首发宿主与最终证据（T18–T24）

Codex、OpenCode、DeepSeek Harness 接T02验证的官方面、复用SDK并分别跑11项真机baseline；ZCode适配器保留实现和诊断，但正式基线延后，不阻塞首发。T22观测可在核心事件具备后提前进行，不必等待全部adapter。T23使用真SQLite/Git/loopback与故障点，T24再运行统一A/B/C/D实验和三个首发宿主演示。

最终交付应提供：锁文件、Schema/OpenAPI、真实支持矩阵、安装与用户手册、恢复指南、故障记录、实验原始结果及限制。没有观察到的token指标标unavailable。研究指标未达成就如实写未达成，不能靠删失败run“通过”。

## 每个阶段的交接格式

在当前任务implement/journal中记录：完成到哪个步骤；精确产物路径；公开接口是否变化；运行了什么命令和结果；遗留的真实缺口；下一任务可依赖哪些证据。不要只写“模块完成”或“测试没问题”。无需让用户批准每个私有函数名，但不能默默改重大设计/固定用户边界。
