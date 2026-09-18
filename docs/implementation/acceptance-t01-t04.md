# T01-T04 实施与验收台账

目标：完成并逐项验收 T01、T02、T03、T04。任务状态不是完成证据；以下条目以实际文件、运行输出和测试为准。本台账随实施更新，不取代各任务 PRD。

## 当前状态

| 任务 | 状态 | 证据与剩余工作 |
|---|---|---|
| T01 工程骨架 | 已完成 | 锁文件、版本窗口、Python/TS骨架、架构检查和静态检查已通过 |
| T02 宿主探针 | 已完成 | 四宿主均有探针与状态矩阵；Codex 有一次真实 app-server 证据，其他未知能力保持 unknown |
| T03 机器协议 | 已完成 | 106 条命令策略、111 个 Schema、Python/TS 生成物和确定性摘要已通过 |
| T04 持久运行时 | 已完成（基础底座） | SQLite 事务、OS lock、WAL/FULL/FK、幂等、event/outbox、Job lease、重试/unknown、epoch fence 已通过单机验收；跨进程故障注入和迁移备份留给后续专项验收 |

## T01 完成证据

- Python distribution、六个 TypeScript workspace 包、两套锁文件及固定版本窗口。
- 在新建 Windows 虚拟环境从锁文件安装，导入 app factory、执行 CLI 帮助并运行静态检查（`uv run pytest`、`uv run ruff check`、`uv run mypy src`）。
- 安装前后锁文件摘要一致；TypeScript strict/NodeNext 与内部 workspace 依赖通过验证。
- 架构检查必须有反例证明能拒绝 domain 导入框架、跨模块内部依赖及 API 绕过端口。
- 实际支持的源码运行命令与尚未实现的产品命令区分记录。

## T02 完成证据

- 四个明确的宿主产品、版本、官方来源和可复现探针；不以模型 API 代替 Harness。
- 每个宿主列出 11 项共同基线和增强能力的 status、strength、证据及缺口。
- 生命周期实验记录同目录双会话、resume/compact/new/clear/fork 的相等或不同关系；不提交原始身份。
- 官方 Python/TypeScript MCP SDK 实际互通，并证明共享服务的连接身份隔离、stdio 转发和私有凭据交付。
- 缺少宿主或可信接口时记录明确阻断；这属于可行性研究结果，不能声称后续正式 adapter 已通过。
- 日志和保存证据通过秘密哨兵检查；身份连续性未被证明的会话不能 ready。

## T03 完成证据

- 命令目录的每个 mutation、显式 user 变体、实验入口和展开后的 query 均有唯一注册项。
- 每项输入和输出都有完整 Schema；字段类型、可省略和可空性明确，拒绝未登记字段和远程引用。
- Python/TypeScript 生成产物具有版本和源摘要；两次生成逐字节相同。
- 两种语言对同一套有效/无效 fixtures 和 JCS 向量得出相同结果。
- principal/grant/capability/predicates/blocker action 和 MCP 暴露名单逐命令验证；内部 Job 与 bootstrap 分开登记。
- UUIDv7、毫秒 UTC、安全整数、PathRule/Scope/EntityRef、错误、版本协商及未知 bundle 拒绝都有正反例。
- 手册请求示例替换占位值后校验通过；REST/MCP 规范化后的幂等输入一致。
- 实际命令：`uv run python tools/codegen/generate_protocol.py`、`uv run python tools/codegen/validate_protocol.py`、`uv run pytest tests/protocol/test_protocol_codegen.py`、`corepack pnpm -r run check`。

## T04 故障与并发验收矩阵

| 场景 | 必须观察的事实 | 证据方式 |
|---|---|---|
| 提交前终止进程 | 聚合、event、command result、outbox/Job 全部回滚 | 独立进程写真实 SQLite，在指定故障点退出后重开 |
| 提交后响应丢失 | 重试只返回原结果，event/效果不重复 | 子进程 commit 后退出，重开后同 command_id 重放 |
| 同 ID 不同输入 | idempotency_conflict，无新增写入 | 改目标、payload 或 expected revision 分别重试 |
| 旧身份或 epoch 重放 | 事务内 fencing 先于幂等读取，拒绝受限旧结果 | 更新可信身份代次后重放已提交命令 |
| 旧 aggregate revision 重放 | 当前身份有效时原成功命令可重放 | 首次命令递增 revision 后用原输入重试 |
| 两个本机 writer | 只有一个持 OS lock；失败者不迁移或写库 | 两个独立进程争用同项目路径 |
| 写队列饱和 | 有界拒绝；已接收工作不丢失 | 控制队列占用并验证 queue_capacity |
| 一致读 | 多次读取看见同一 snapshot，后续新读看见新提交 | 读事务与 writer 交错 |
| event/outbox 原子性 | lineage 内 seq 单调；失败不留下半条 outbox | 成功、回滚与并发命令交错 |
| Job claim/renew/finish | lease_epoch 和 owner 共同 fencing，旧 worker 不能回写 | 注入 Clock 并发 claim、过期接管和迟到结果 |
| pure/idempotent 崩溃 | 按持久 input 与受控 backoff 重试 | intent 后/结果前故障注入 |
| reconcilable 崩溃 | 先核验 receipt，再决定继续或 unknown | 独立外部效果文件与持久 intent 交错 |
| unverifiable 超时/崩溃 | Operation 为 outcome_unknown；不自动再执行 | 计数效果验证未重复调用 |
| unknown 的人工结论 | 原 status 不改；Resolution 只追加，risk_accepted 不显示 succeeded | 追加多次结论并验证派生结果及历史 |
| 启动恢复 | 已登记项目未完成 Job/outbox 无需业务请求即可进入恢复 | 关闭并重开 runtime 集合 |
| 迁移失败 | 迁移前有效备份；原库可恢复；运行只读诊断 | 在真实迁移中注入失败并验证备份/完整性 |
| 用户长期沉默 | 没有由 Job timeout 推断用户拒绝的路径 | 检查注册 handler 边界和持久等待事实 |

当前 T04 已覆盖可运行的本地持久底座和关键单元/故障语义；独立进程 crash 注入、迁移备份/只读诊断、双 writer 压测和受控时钟属于后续专项验收，不能从本轮单元测试推断已完成。共享 checkpoint 文件物化的完整格式与业务生命周期分别由 T14/T15 交付。
