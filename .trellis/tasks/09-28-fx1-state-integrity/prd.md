# FX1 修复契约终态与取消收口

状态：已实施，S1–S6 验证见 [implementation-progress.md](implementation-progress.md)；2026-09-28。归属总任务 FX-R04，独立于宿主唤醒。资源/Grant 的联动由后续 FX2 集成验收。

## 目标与证据

契约和取消应反映真实状态，不让 Agent 反复恢复绕过状态错误。实测契约 6333274b-ff33-4d2d-bbd1-986ae661a208 在 withdraw 后被 proxy accept 改为 accepted；旧任务在无 current attempt 时停在 cancel_requested。

源码锚点：src/tsunagou/modules/cognition.py:255 的 accept_proxy、:219 的参与者构造，以及 modules/tasks.py:181 的 request_cancel（后者同样以 src/tsunagou 为根）。完整证据见[总任务](../09-28-real-test-repair/prd.md)。

## 需求与验收

| 编号 | 结果及验收 |
| --- | --- |
| S1 | withdrawn/rejected/superseded 契约不能被本人或主 Agent 代理接受复活；失败不写 acceptance 或成功事件 |
| S2 | 参与者必须有唯一非空 slot 和有效 agent_id；缺失、跨项目、重复 slot 在首次提交时指出字段问题 |
| S3 | 代理接受记录真实主 Agent 和被代理 Agent；不能把 slot 当 agent_id；不新增用户逐项批准 |
| S4 | 没有 claimed/running 执行者的任务取消直接 cancelled；正在执行的保持 cancel_requested，待 owner 确认或 main 显式回收 |
| S5 | 同一 command_id 重试不重复生成事件；新命令对终态修改明确拒绝 |
| S6 | 同库重启后结果不变；actor、时间及 task/attempt/proposal 关联可查询 |

## 边界

保留主 Agent 代理权限和用户专属权限。依 FX-D02 不修补旧非法记录或编写迁移。公共 Schema、目录、fixtures 与 handler 同步。取消的资源/Grant 原子收口与 FX2 集成验证。

技术设计见 [design.md](design.md)，实施见 [implement.md](implement.md)。
