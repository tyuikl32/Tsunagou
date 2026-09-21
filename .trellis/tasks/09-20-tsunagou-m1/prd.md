# M1 独立运行最小成品

状态：M1 acceptance passed；负责人：tyuikl32；平台：Codex。十二条最小产品标准已通过；R1-R6 中未覆盖完整原设计的部分保留为后续 follow-on。

## 目标

交付能独立安装、启动、操作、协作并重启恢复的本机程序。用户初始化协调项目，接入一个主 Agent 和一个独立 worker，通过真实 CLI/HTTP/stdio MCP 完成任务、认知协商、shared 工作区执行、审查及用户确认项目完成。

范围：Windows 本机 loopback、单 daemon/活动项目、多 root、SQLite 唯一事实源、通用 stdio MCP。主 Agent 控制 Git，用户决定重大设计和项目完成；模型由已有宿主提供。宿主能力报告、正式兼容认证、Web 和研究实验不阻塞 M1。

## 子任务

- [ ] [R1 协议与独立安装入口](../09-20-r1-protocol-package/prd.md)；前置：无。
- [ ] [R2 常驻 daemon、统一 SQLite 和真实 CLI](../09-20-r2-runtime-storage-cli/prd.md)；前置：R1。
- [ ] [R3 任务状态机与主从边界](../09-20-r3-task-ownership/prd.md)；前置：R2。
- [ ] [R4 认知、资源与工作空间闭环](../09-20-r4-coordination-loop/prd.md)；前置：R3。
- [ ] [R5 Agent 接入、用户决定与恢复](../09-20-r5-agent-user-recovery/prd.md)；前置：R4。
- [ ] [R6 封装、回归与独立交付](../09-20-r6-standalone-delivery/prd.md)；前置：R5。

顺序 R1 → R2 → R3 → R4 → R5 → R6。meta.depends_on 与[机器计划](../../../docs/implementation/task-plan.json)维护依赖，父子关系只分组。

## 最终完成标准

以下全部通过才是M1完成；现有110/29测试保持通过只是其中一部分。逐条记录见 [M1 acceptance](../../../docs/standalone/m1-acceptance-2026-09-21.json)。

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

## 历史处置

旧 T01-T17/T22 共 18 项保留 completed，T18-T21/T23-T24 和旧 V1 总计划共 7 项 cancelled（放弃）。旧产物可复用，关闭状态不证明 M1 已完成。详见[归档记录](../../../docs/standalone/trellis-transition-2026-09-20.json)。
