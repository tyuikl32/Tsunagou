# 实测缺陷修复与协作流程简化

日期：2026-09-28。**用户已授权完成全部 FX 任务，实施中。** 源码核对基线 main@1fb86e0；当前分支 codex/live-test-repair，进度以任务索引和各项实际验证为准。

目标是把本轮真实协作暴露的故障修好，同时减少接入操作、协调回合和重复状态。用户已允许推翻低效旧设计，不要求旧版本数据/身份迁移。本文件供审阅和执行导航；字段、状态、具体文件与测试步骤在七项任务中固定。

## 1. 已确认的四项决定

| 决定 | 本轮执行边界 |
| --- | --- |
| [FX-D01：明确释放资源](../decisions/2026-09-28-explicit-resource-release.md) | 删除本机资源 TTL、续租和自动保活；提交、挂起、失败、取消确认或 main 回收时释放 |
| [FX-D02：统一破坏兼容升级](../decisions/2026-09-28-clean-break-upgrade.md) | daemon/CLI/bridge/Skill 同版本，全新状态验收；不迁移旧记录/身份，不保留旧接口兼容；新版自身持久化及同版本重启仍须工作 |
| [FX-D03：原 Desktop 唤醒必达](../decisions/2026-09-28-desktop-wake-required.md) | 手动创建的原 Codex 会话须由 daemon 自动触发；managed 成功不替代此项 |
| [FX-D04：允许本机私有接口](../decisions/2026-09-28-codex-local-app-interface.md) | Codex 专用 provider 可依赖应用自带管道，接受版本维护；不改宿主二进制、不删锁、不假冒活跃回合 |

产品边界已经明确，无需再逐项询问用户。应用管道的后台调用与原会话自动唤醒已由 FX3 探针及双 Worker 实测证明；新版 daemon 重启后恢复与完整场景收口仍按 FX6 验收。

## 2. 证据和问题取舍

本轮 [复盘](../acceptance/sega-test-retrospective-2026-09-28.md)、[数据摘录](../acceptance/sega-test-retrospective-2026-09-28.json)、[42 条原始记录](../acceptance/evidence/sega-image-manage-tool-2026-09-28/unexpected-deviations.json)和[原生唤醒补测](../acceptance/evidence/sega-image-manage-tool-2026-09-28/native-wake-followup.md)是依据。

11 个 Attempt 有 9 个 orphaned，12 次资源过期，169 条 session.reconnect；最终只有两项提交。不能把这些经过时间全解释成编码时间。最初部署精确起点未机器记录，旧数据中的估算上界不改写成精确值。

[逐项处置索引](../../.trellis/tasks/09-28-real-test-repair/research/issue-disposition.json)覆盖全部 42 条观察，区分：

- 产品修复：生命周期、执行步骤、接入路由、原会话唤醒、契约和取消、失败诊断、业务完整性。
- 回归即可：已修 Windows 排除端口锁、已有直接 A2A HTTP 证据、后续幂等复测和正样本；严格校验后须重新核实正样本。
- 保持正确边界：main 不能读 Worker 私信；两个任务确实重叠时，应由 main 调整范围。
- 不扩大范围：旧业务 nullable 警告；已修的独立 listener 目录问题不重开，Desktop 控制路径将替换。
- 复用已有成果：PT1–PT7 的 history、diagnostics、audit、checkpoint、秘密交付及工作区观察，不重新造一套。

## 3. 七项任务和实施顺序

FX1、FX2、FX7 已完成；FX7 在隔离业务 checkout 中通过 BTID 完整性、HTTP 和 WebUI 回归，证据见对应验证记录。FX3 的管道实现和原会话后台探针通过，当前进程升级后的持久化回归仍与 FX4/FX6 一起验收。各任务已具备 PRD、design、implement、实施/检查 JSONL。Trellis 父子关系只表示分组，执行依赖和最新进度见 [机器索引](live-test-repair-tasks.json)及各任务 meta.depends_on。

| 任务 | 必须交付 | 前置 | 详细入口 |
| --- | --- | --- | --- |
| FX1 状态正确性 | 显式参与者、契约终态不可复活、无 owner 取消结束、幂等事务 | 无 | [需求](../../.trellis/tasks/09-28-fx1-state-integrity/prd.md) / [设计](../../.trellis/tasks/09-28-fx1-state-integrity/design.md) / [步骤](../../.trellis/tasks/09-28-fx1-state-integrity/implement.md) |
| FX2 执行简化 | begin/submit、无 TTL 占用、task 级策略、删除 ready/重复执行状态 | FX1 | [需求](../../.trellis/tasks/09-28-fx2-execution-flow/prd.md) / [设计](../../.trellis/tasks/09-28-fx2-execution-flow/design.md) / [步骤](../../.trellis/tasks/09-28-fx2-execution-flow/implement.md) |
| FX3 原会话唤醒 | 应用管道 provider、绑定刷新、忙时合并、未知结果核对、真实唤醒 | 无 | [需求](../../.trellis/tasks/09-28-fx3-desktop-wake/prd.md) / [设计](../../.trellis/tasks/09-28-fx3-desktop-wake/design.md) / [步骤](../../.trellis/tasks/09-28-fx3-desktop-wake/implement.md) |
| FX4 安装接入 | 独立 CLI、统一项目定位、自动身份、一条命令、项目规则、Agent 查询 | FX2/3 | [需求](../../.trellis/tasks/09-28-fx4-onboarding/prd.md) / [设计](../../.trellis/tasks/09-28-fx4-onboarding/design.md) / [步骤](../../.trellis/tasks/09-28-fx4-onboarding/implement.md) |
| FX5 时间线和追踪 | 失败必落盘、实际触发来源、UTC 时间与阶段耗时、可选 OTel | FX2/3/4 | [需求](../../.trellis/tasks/09-28-fx5-traceability/prd.md) / [设计](../../.trellis/tasks/09-28-fx5-traceability/design.md) / [步骤](../../.trellis/tasks/09-28-fx5-traceability/implement.md) |
| FX7 BTID 修复 | 业务仓库 CRC/HMAC、完整读/短读退出、HTTP 422 与页面回归 | 无 | [需求](../../.trellis/tasks/09-28-fx7-btid-integrity/prd.md) / [设计](../../.trellis/tasks/09-28-fx7-btid-integrity/design.md) / [步骤](../../.trellis/tasks/09-28-fx7-btid-integrity/implement.md) |
| FX6 真实验收 | 两名独立 Worker 在原会话完成实际工作、恢复及业务回归，完整计时 | FX1–5/7 | [需求](../../.trellis/tasks/09-28-fx6-live-acceptance/prd.md) / [设计](../../.trellis/tasks/09-28-fx6-live-acceptance/design.md) / [步骤](../../.trellis/tasks/09-28-fx6-live-acceptance/implement.md) |

推荐顺序：**FX3 → FX1 → FX2 → FX4 → FX5 → FX7 → FX6**。先验证最不确定的后台宿主调用，避免写完外围后才发现路径不成立。FX1/2/7 可在技术排查时独立推进，但不能提前关闭总任务。

## 4. 修复后的正常流程

1. 用户告诉 Agent 从 GitHub 安装/接入 Tsunagou。安装器确定一份源码与运行环境，业务项目只生成规则、引用和自己的持久状态。
2. Agent 自动取得真实会话与宿主连接，准备私有接入请求。需要用户操作时，提供一条已填好路径和角色的 connect 命令。用户不抄 conversation_id、agent_id、pipe 或 token。
3. connect 的 U 授权绑定 ticket 与接入意图，原会话 bridge 兑换身份后绑定 provider。只有原会话查到正确 context 才报告 ready；不以 ticket_issued 代替完成。
4. main 读到 Worker 请求后在已有项目授权内判断、创建/发布或明确回复；不只 ACK 后等待用户再次催促。重大设计/交付决定仍交用户。
5. main 确定任务范围、隔离策略及确实必要的契约。Worker 读任务后一次 begin，机械准备由后端完成；无冲突即实际工作。
6. Worker 一次 submit，后端收集工作区结果并释放占用；main 审查。遇到真实阻塞时保存状态挂起，无关任务继续。
7. 持久消息经 outbox 到原会话 provider，空闲时启动、忙时合并等待；后续回复使相关 Agent 继续，无需用户发送“继续”。
8. 用户用现有 history/diagnostics/audit/checkpoint 与新增 agent list 查看任务、失败和时间；重大交付在用户确认后收口。

上述 begin、prepare 和查询过滤参数已在本轮工作区实现，FX4/6 已用本机安装产物 help 核对，逐条命令见 [首次实测操作单](../acceptance/live-repair-first-run.md)。这证明当前本机工作区产物的语法，不表示未发布的 GitHub 版本已经包含这些修改。

## 5. 生命周期：哪些情况释放资源

| 发生什么 | Task/资源行为 |
| --- | --- |
| 等待领取、时间经过、长推理、构建、无新消息 | 任务不失效；已存在占用不释放；不要求周期性进度 |
| begin 中途失败 | 回滚本次新 Attempt、占用和 Grant，不遗留半套准备 |
| owner submit、block、fail、cancel_ack | 同事务收口并释放；submit 仍等待审查 |
| main 请求取消活跃执行 | cancel_requested，不假设 Worker 已停写 |
| 取消无执行者的任务 | 直接 cancelled，不等待不存在的 owner |
| 短暂断线、MCP 重载、同库 daemon 重启 | 保留 owner/占用；旧 Grant 失效，原 owner begin 恢复 |
| main 显式回收 | 旧 Attempt 结束、撤权、释放，按 disposition reopen/cancel/fail |
| 执行中修改 scope | 先明确停写/挂起/回收，不能直接把旧重叠范围交给别人 |
| 导入 checkpoint 到新副本 | 不继承活动占用和授权，与同库重启区分 |

这表示协作归属，不是 OS 文件沙箱。Full Access 的旧进程可能继续写文件；数据库回收不能宣称物理终止了它。

## 6. 设计约束和明确删除项

系统负责身份、范围、owner、必要版本、状态和事务；业务语义由 main 判断。Task/Attempt 继续是唯一执行真相，workflows/blackboard 只编排和投影。

删除公开的 claim/preflight/start 多段准备、Worker 手填等价资源声明、周期续租、worker.ready 门槛和重复 assignment 执行状态。只检查任务显式 required_contract_ids，不再因无关契约变化反复准备。工作区策略按 task 保存，实际基线/结果仍按 Attempt 保存，Git 写操作由 main 控制。

不增加跨旧版本迁移、旧新双写、通用规则引擎、第二套消息/任务库、宿主代理平台、周期性 LLM 看守或强制能力问卷。OTel 只覆盖五个调用边界，默认关闭、本机导出；核心时间线不依赖它，不新建观测 WebUI。

## 7. 宿主路径与验收风险

[研究记录](../../.trellis/tasks/09-28-real-test-repair/research/codex-wake-control.md)包含官方资料、本机源码和脱敏实测。后台调用及空闲原会话唤醒已通过，随后两名原 Worker 经 daemon 消息完成各自 MCP 收件箱处理和实际代码提交，见 [原宿主记录](../../.trellis/tasks/09-28-fx4-onboarding/research/live-original-host-20260928.md) 与 [本轮现场记录](../acceptance/evidence/live-repair-20260928T125752Z/live-coordination-notes.md)。早期连接失败保留，不用恢复成功覆盖。同库 daemon 重启后 owner 恢复、显式回收和原 Worker 旧 Attempt 提交拒绝已在后续现场回合核实；旧提交由权限层拒绝，不能宣称更深层的 Attempt 错误码已实测。

FX3 经应用原控制连接发最小“读收件箱”提示，避免新 listener 抢 writer。provider 私有保存绑定，不把原始 host 标识和 endpoint 放入模型提示。调用遵守宿主权限，不改模型/思考设置。若后台调用受限，就保留失败并修路径；主 Agent 常驻代发、替代 thread 或人工继续都不能作为完成证据。

宿主接受、回合开始、inbox 呈现、ACK 是不同事实。失败后人工恢复保留原失败，标记真实来源；消息已持久化不等于自动执行成功。固定观察窗口结束也不意味着可以丢弃未处理消息。

## 8. 与现有文档的关系和最终完成标准

本轮是当前新增修复计划，未重开已完成 M1/PT 任务。四项 FX 决定及本轮任务 design 优先于旧资源 TTL、no-wake 降级、禁止私有接口和旧版迁移约定；其余八模块边界继续保留。[总设计](../../.trellis/tasks/09-28-real-test-repair/design.md)列出八模块和接口主责，[实施调度](../../.trellis/tasks/09-28-real-test-repair/implement.md)规定规范同步顺序。

实现者须随代码同步 Schema、命令目录、生成物、打包协议/Skill 和用户文档。后续操作单须基于已实现命令，不能把设计示例当实际测试结果。

最终必须有：正常安装；main 加两名独立手动 Desktop Worker；真实 A2A 接收及 daemon 原会话唤醒；实际业务提交与审查；重启及显式回收；契约/取消正确性；真实 HTTP/页面正反样本；部署、工作、审查和用户等待分段时间及可查询失败。unknown 时间/用量不填零，不覆盖失败，不以构建或 mock 代替现场结果。

用户已于 2026-09-28 授权实施全部 FX 任务。当前 FX1、FX2 和 FX7 已完成；FX3–FX5 的代码检查/自动化测试及主要原会话路径已通过，仍须按各自 PRD 核对剩余真实场景和后加代码的运行时加载。FX6 的逐项结论见 [验收复核](../acceptance/evidence/live-repair-20260928T150917Z/operator-review.md)：A1–A8 均有现场 pass 记录，A4 权限层拒绝与 A6 主通知没有另启回合的边界详见证据。A7 已用安装 CLI 从公开 Result.created_at 查询提交时间并标明来源，保持私信审计隔离。用户项目完成确认尚未发生；FX3–FX6 和总修复任务仍为 in_progress。
