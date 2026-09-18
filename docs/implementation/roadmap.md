# 实施路线图与 Trellis 操作

Trellis 0.6.17 已初始化：开发者 **tyuikl32**，平台 **Codex**。24 个实施子任务属于一个首发总任务，当前均为 planning，未运行产品实现；文档初始化任务单独完成归档。

机器可读定义：[task-plan.json](task-plan.json)。任务元数据的 `meta.depends_on` 保存稳定 T 编号；这是项目约定，Trellis 的 parent/children 只分组，不自动调度依赖。开始任务前必须核对依赖产物和验收证据。

## 阶段

1. T01 工程骨架与 T02 宿主研究是起点；研究可独立推进。
2. T03–T12 建立协议、存储、身份、任务、认知、资源、工作空间与附件。
3. T13–T16 整合闭环、checkpoint、重大生命周期、HTTP/MCP/CLI与黑板。
4. T17–T21 建共享SDK并交付四个宿主；各宿主都需自己的真实证据。
5. T22 可在核心事件可用后开始观测框架；T23 工程验收；T24 对照实验、演示与首发材料。

## 任务目录

每个任务目录都有 task.json、prd.md、design.md、implement.md、implement.jsonl、check.jsonl。PRD包含具体产物和可判定验收；设计引用唯一协议并规定事务/权限边界；implement是实际执行和交接清单。

| 任务 | 交付 | 前置依赖 |
|---|---|---|
| [T01](../../.trellis/tasks/09-18-t01-foundation/prd.md) | 工程骨架与可复现工具链 | 无 |
| [T02](../../.trellis/tasks/09-18-t02-host-probes/prd.md) | 四宿主与MCP可行性探针 | 无 |
| [T03](../../.trellis/tasks/09-18-t03-protocol/prd.md) | 统一Schema、DTO与命令策略目录 | T01 |
| [T04](../../.trellis/tasks/09-18-t04-storage-runtime/prd.md) | SQLite事务、事件与持久Operation运行时 | T03 |
| [T05](../../.trellis/tasks/09-18-t05-projects-roots/prd.md) | 项目初始化、根目录与范围模型 | T04 |
| [T06](../../.trellis/tasks/09-18-t06-identity-authority/prd.md) | 会话身份、最小认证、Grant与主权限 | T05, T02 |
| [T07](../../.trellis/tasks/09-18-t07-messaging/prd.md) | 持久消息、收件箱与回应义务 | T06 |
| [T08](../../.trellis/tasks/09-18-t08-tasks/prd.md) | 任务、Attempt、委派与验收状态机 | T06 |
| [T09](../../.trellis/tasks/09-18-t09-resources/prd.md) | 资源冲突、等待与Lease | T08 |
| [T10](../../.trellis/tasks/09-18-t10-cognition/prd.md) | 认知报告、分歧、契约和风险 | T08 |
| [T11](../../.trellis/tasks/09-18-t11-workspaces/prd.md) | 隔离驱动、工作空间与Git请求 | T09, T10 |
| [T12](../../.trellis/tasks/09-18-t12-artifacts/prd.md) | 领域授权附件与内容寻址存储 | T06, T04 |
| [T13](../../.trellis/tasks/09-18-t13-task-orchestration/prd.md) | 跨模块Preflight与认知协作闭环 | T07, T09, T10, T11, T12 |
| [T14](../../.trellis/tasks/09-18-t14-checkpoints/prd.md) | Checkpoint、Git锚点与共享状态恢复 | T07, T08, T10, T11, T12 |
| [T15](../../.trellis/tasks/09-18-t15-lifecycles/prd.md) | 重大决定、完成、继任与Lineage转换 | T13, T14 |
| [T16](../../.trellis/tasks/09-18-t16-interfaces/prd.md) | HTTP、MCP、CLI、黑板与运行提示 | T15, T07 |
| [T17](../../.trellis/tasks/09-18-t17-bridge-sdk/prd.md) | 共享Bridge SDK与适配器一致性测试框架 | T16, T02 |
| [T18](../../.trellis/tasks/09-18-t18-adapter-codex/prd.md) | Codex正式共同基线适配 | T17 |
| [T19](../../.trellis/tasks/09-18-t19-adapter-opencode/prd.md) | OpenCode正式共同基线适配 | T17 |
| [T20](../../.trellis/tasks/09-18-t20-adapter-zcode/prd.md) | ZCode正式共同基线适配 | T17 |
| [T21](../../.trellis/tasks/09-18-t21-adapter-deepseek/prd.md) | DeepSeek Harness正式共同基线适配 | T17 |
| [T22](../../.trellis/tasks/09-18-t22-observability/prd.md) | 脱敏审计、指标与实验运行框架 | T04, T07, T08, T10 |
| [T23](../../.trellis/tasks/09-18-t23-integration-release-gates/prd.md) | 端到端与故障恢复发布门槛 | T15, T16, T17, T22 |
| [T24](../../.trellis/tasks/09-18-t24-experiments-demo/prd.md) | 四宿主演示、对照实验与首发交付 | T18, T19, T20, T21, T23 |

## 八模块覆盖

| 模块 | 主要任务 |
|---|---|
| projects | T05、T06、T15 |
| agents | T06、T07、T15、T17–T21 |
| tasks | T08、T13、T15 |
| cognition | T10、T13 |
| resources | T09、T13 |
| workspaces | T11、T13 |
| durability | T04、T12、T14、T15 |
| evaluation | T22、T23、T24 |

T01/T03提供公共工程和协议，T16提供入口与组合查询，不新增业务模块。

## 实际可执行的管理命令

在仓库根目录执行：

```powershell
python .trellis/scripts/task.py list
python .trellis/scripts/task.py validate .trellis/tasks/09-18-t01-foundation
python .trellis/scripts/task.py start .trellis/tasks/09-18-t01-foundation
python tools/docs/validate_docs.py
```

`start`是将来开始实施时执行，本轮未自动启动。它依赖当前Codex会话身份；若宿主未注入，先读Trellis报出的身份提示，用当前可信会话标识配置 `TRELLIS_CONTEXT_ID`，不要所有并发会话共用同一个固定ID。没有hooks也可显式读取任务/context/spec，不缺规划内容。

完成后先检查PRD和验证证据，再用`task.py finish`清除当前指针、`task.py archive <task>`归档。归档会改变路径，需同步task-plan.json/roadmap直接链接；稳定T编号和depends_on不变。用`add_session.py --title ... --commit - --summary ... --no-commit`记录未提交工作；实际提交后用真实commit OID。

session_auto_commit已关闭。本轮不创建提交或发布。Codex hooks资产已安装，但自动注入是否生效取决于宿主hooks开关和用户UI信任；未替用户修改全局设置或批准hooks。

## 开工就绪判断

产品边界和跨模块契约足够开始T01/T02/T03，不必再做一轮无边界问答。精确依赖和宿主API的可行性通过T01/T02消除，不能跳过后宣称四宿主已经兼容。若证据推翻用户已定支持范围，才带具体失败与替代方案交还用户；一般内部工程取舍由实施Agent决策留档。
