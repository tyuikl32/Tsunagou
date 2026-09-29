# 总体设计和跨任务契约

权威修复入口：[实测修复方案](../../../docs/implementation/live-test-repair-plan.md)。公共语义以本轮四项已确认决定及所属子任务 design 为准；此文固定归属，避免多个实现 Agent 各自解释。

## 八模块归属

| 模块 | 本轮改变 | 主责 |
| --- | --- | --- |
| projects | 统一 root/source/state 定位，接入继续受 U 任命边界控制 | FX4 |
| agents | 每个真实会话一个 Worker、持久 inbox、原 Desktop 唤醒及绑定刷新 | FX3/4 |
| tasks | 一次 begin/submit、取消收口、Task 依赖为唯一执行事实 | FX1/2 |
| cognition | slot/agent_id 显式、终态约束；仅明确 required 契约形成门禁 | FX1/2 |
| resources | 无到期的 ResourceReservation，明确结束释放 | FX2 |
| workspaces | 策略归 task，基线/结果归 Attempt，main 控制 Git | FX2 |
| durability | 复用 UoW/outbox/幂等；同库重启保留 owner；不做旧版本迁移 | FX1/2/3 |
| evaluation | 真实失败/来源/UTC 时间，已有 CLI，最小可选 OTel 与两 Worker 验收 | FX5/6 |

FX7 属于外部业务代码，不增加第九模块。HostWakePort 是现有 adapter 边界，不能发展为独立调度中心。

## 接口交接

| 契约 | 定义位置 | 消费者 |
| --- | --- | --- |
| ContractParticipant(slot, agent_id)，代理及终态检查 | [FX1 design](../09-28-fx1-state-integrity/design.md) | handlers、Schema、认知工具、FX2 |
| task.begin、submit、recover、ResourceReservation、task 级策略 | [FX2 design](../09-28-fx2-execution-flow/design.md) | CLI、bridge、Skill、FX4、FX6 |
| CodexDesktopProvider、私有绑定、session.reconnect 的限定刷新 | [FX3 design](../09-28-fx3-desktop-wake/design.md) | FX4 connect/enrollment、dispatcher、FX5 |
| agent prepare/connect/list、安装 resolver、生成项目规则 | [FX4 design](../09-28-fx4-onboarding/design.md) | 安装器、项目中的 Agent、FX5/6 |
| diagnostic 时间/来源/关联及五边界 tracing | [FX5 design](../09-28-fx5-traceability/design.md) | CLI、OTLP、FX6 |
| 真实验收证据和结束标准 | [FX6 design](../09-28-fx6-live-acceptance/design.md) | 用户验收、总任务关闭 |
| BTID 校验错误/短读与既有 422 | [FX7 design](../09-28-fx7-btid-integrity/design.md) | Sega 后端、静态前端、FX6 |

FX3 的最小 bridge 刷新及服务端能力在 FX3 自身交付；FX4 负责自动收集上下文和一条命令体验。FX3 不依赖 FX4 完成后才能写 provider，FX4 不复制绑定实现。FX5 在 FX4 之后接计时，避免依赖环。

## 事务和重启

begin 内部仍调领域服务，但通过现有 UoW 原子提交新 Attempt、资源占用、基线、Grant、事件/outbox；失败返回原状态。submit/block/fail/cancel_ack/recover 在同一事务释放占用与撤权。文件系统观察不是物理文件锁，Full Access 的旧进程不会被数据库状态强制停止。

同库重启保留正在执行的任务和资源占用，旧运行期 Grant 无效；原 owner begin 恢复，其他 Worker 不可接管。主 Agent 显式回收后才重新开放。checkpoint 导入新副本沿用不继承活动权限的语义。

消息事务与宿主 RPC 分开：消息先持久化，再由 outbox 请求原会话。宿主失败不回滚消息、不改业务任务为 blocked。接收、启动、处理分别留痕；unknown 先核对再重试，不假设网络副作用 exactly-once。

## 规范切换

本轮取消旧资源 TTL/续租、多段外部准备、worker.ready 和全项目契约门禁；允许 Desktop 私有接口，且本轮不接受 no-wake 降级。旧模块文档与 adapter spec 中相反语义只作为历史基线。实现所属 FX 时同步文档、Schema、registry、Python/TS 生成物、打包资源与运行 Skill，不能只改提示词。

FX-D02 删除跨旧版本兼容义务，未授权清空用户现有目录；实际开发使用新状态目录即可。升级前后的旧记录可保留作证据，不要求迁移。不开新兼容开关、双写库或旧协议代理。

## 唯一显著工程不确定性

已独立验证本机 tools/list，尚未验证 caller 回合结束后 daemon 的合法 tools/call。FX3 第一项实际测试立即回答此问题；研究见[控制路径](research/codex-wake-control.md)。若失败，修同一宿主路径并记录事实，不能用开发对话代发、额外主 Agent 常驻或重建 Worker 代替目标。

其他未固定的私有函数拆分、包内文件位置和夹具组织由实现者决定，不再交用户选择。改变上述用户结果、固定权限或必须支持的原会话目标才需要重新讨论。
