# 实测缺陷修复与协作流程简化

状态：**in_progress；用户已授权完成全部 FX 任务**。日期 2026-09-28；开发者 tyuikl32，平台 Codex。具体进度见各子任务，尚未完成最终真实验收。

## 目标与证据

本机多 Agent 从接入、领取、执行到提交，不再需要用户修复 session、手工续租或代替 daemon 催醒。允许删除低效旧设计，保留身份、owner、scope 和用户重大决策边界。

源码核对基线 main@1fb86e0，已经包含 PT1–PT7。已有 history、diagnostics、audit、checkpoint 复用，不因先前读取到旧版本而重复开发。[本轮复盘数据](../../../docs/acceptance/sega-test-retrospective-2026-09-28.json)记录 11 个 Attempt 中 9 个 orphaned、12 次资源过期、169 条 session.reconnect；最终仅两项提交。[原生补测](../../../docs/acceptance/evidence/sega-image-manage-tool-2026-09-28/native-wake-followup.md)证明独立 listener 存在 active writer 冲突，应用手动跟进不能计为 daemon 唤醒。

[42 项异常处置表](research/issue-disposition.json)逐项区分修复、回归、正确边界、退役路径和范围外项。原始证据保留，不以规划状态覆盖历史事实。

## 需求和可观察验收

| ID | 用户结果 | 完成条件 | 任务 |
| --- | --- | --- | --- |
| FX-R01 | 长回合稳定执行 | 无资源 TTL/模型续租，静默或重启不错误 orphan/reopen，待领取任务持续存在 | FX2 |
| FX-R02 | 执行步骤少 | 一次 begin 完成机械准备；策略无变化不重选；一次 submit 自动收集工作区结果 | FX2 |
| FX-R03 | 自动唤醒真正可用 | daemon 触发手动创建的原 Codex Desktop 会话并读取消息；managed 也回归；替代身份、人工继续不算成功 | FX3 |
| FX-R04 | 状态可靠 | 契约终态不能复活、参与者无歧义、无执行者取消收口、重试无重复副作用 | FX1 |
| FX-R05 | 独立安装和简单接入 | 从业务目录工作，自动取得真实身份；用户最多复制一条已填好参数的接入命令；安装项目规则，main 主动处理请求 | FX4 |
| FX-R06 | 失败和时间可追溯 | 失败、来源、真实时间及对象关联可查；只读无业务噪声；关键调用有可选实际 trace | FX5 |
| FX-R07 | 真实协作闭环 | 两名独立 Worker 在原 Desktop 对话完成工作、恢复和审查；部署/工作/等待分开计时 | FX6 |
| FX-R08 | 业务缺陷独立修复 | BTID 校验及截断处理在业务仓库修复，真实 HTTP/页面回归 | FX7 |

## 已确认决定

- [FX-D01](../../../docs/decisions/2026-09-28-explicit-resource-release.md)：资源占用明确释放，不引入自动保活或替代 TTL。后台 Job 内部 lease 不受影响。
- [FX-D02](../../../docs/decisions/2026-09-28-clean-break-upgrade.md)：daemon/CLI/bridge/Skill 统一破坏兼容升级，无旧运行数据/身份迁移，无双写、旧格式适配；新版自身持久化和同版本恢复必须保留。
- [FX-D03](../../../docs/decisions/2026-09-28-desktop-wake-required.md)：用户手动创建的原 Desktop 会话自动唤醒为本轮必达，不以 managed 成功关闭总任务。
- [FX-D04](../../../docs/decisions/2026-09-28-codex-local-app-interface.md)：允许 Codex adapter 依赖应用本机私有接口，接受版本适配成本；不修改应用二进制、不伪造活跃调用身份。

没有剩余待用户选择的产品分叉。真实后台调用上下文仍是首项工程验证，不把未测路径写成已可用。

## 任务与依赖

| 任务 | 前置 | 交付 |
| --- | --- | --- |
| [FX1 状态正确性](../09-28-fx1-state-integrity/prd.md) | 无 | 参与者/终态/取消 |
| [FX2 执行简化](../09-28-fx2-execution-flow/prd.md) | FX1 | begin/submit、ResourceReservation、工作区与依赖 |
| [FX3 原会话唤醒](../09-28-fx3-desktop-wake/prd.md) | 无 | 本机 provider、原会话绑定刷新、投递与真实唤醒 |
| [FX4 安装接入](../09-28-fx4-onboarding/prd.md) | FX2、FX3 | 独立入口、自动身份、项目规则、agent list |
| [FX5 时间线与追踪](../09-28-fx5-traceability/prd.md) | FX2、FX3、FX4 | 失败落盘、计时、查询与最小可选 OTel |
| [FX7 BTID](../09-28-fx7-btid-integrity/prd.md) | 无 | 外部业务完整性修复 |
| [FX6 实测验收](../09-28-fx6-live-acceptance/prd.md) | FX1–FX5、FX7 | 两 Worker、原 Desktop、业务成果与用户验收 |

每项已有 PRD/design/implement 和非空 implement/check 上下文。执行依赖以 [机器索引](../../../docs/implementation/live-test-repair-tasks.json) 与 meta.depends_on 为准，父子关系只分组。

## 不做什么

不增加规则引擎、第二套任务真相、通用宿主代理平台、强制能力证明、周期性 LLM 看守、常驻观测平台或新用户审批链。主 Agent 仍控制 Git，判断业务语义；系统检查机械不变量。普通子任务审查由 main 完成，重大交付/项目设计变更仍由用户决定；主 Agent 不能读取 Worker 私信。

## 关闭条件

子任务验收通过，FX6 实际证据完整，公共 Schema/生成物/Skill/手册与实现同步，并由用户确认重大交付。源码 mock 或编译通过不替代真实原会话唤醒。当前仅交付方案与任务；下一阶段收到实施指令后再开始。

进一步阅读：[总设计](design.md)、[实施调度](implement.md)、[面向审阅的方案](../../../docs/implementation/live-test-repair-plan.md)。
