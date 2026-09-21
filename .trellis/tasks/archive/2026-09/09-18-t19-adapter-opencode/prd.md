# T19 OpenCode正式共同基线适配

> 2026-09-20：按用户要求关闭旧计划并归档。本任务放弃，由 M1 / R1-R6 新计划替代；未达验收项不记为完成。 当前执行入口：[M1 路线图](../../../../../docs/implementation/roadmap.md)。

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- packages/adapter-opencode
- OpenCode安装与probe说明
- 版本化真宿主证据

## 前置依赖

T17。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 采用T02确认的SDK session/plugin事件并绑定工具请求
- 共享bridge身份/消息/恢复实现，验证多session同目录隔离
- 映射wake/工具观察/生命周期增强，未知证据保守处理
- 执行baseline、重复事件、乱序事件、断线恢复真宿主测试

## 验收标准

- [ ] 11 项通过且和 Codex 用同一 conformance 口径（1.18.31 真实 probe 只证明 session isolation/fork，其他能力保留 unknown）
- [x] plugin 关闭/能力下降转相应 degraded 或降级（共享 status 语义）
- [x] 模型不能指定 sender/owner（适配器只产生 host identity/evidence）
- [x] 不复制领域 Schema 或绕 REST 授权（仅复用 bridge-sdk）

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
