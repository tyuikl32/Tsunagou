# T13 跨模块Preflight与认知协作闭环

> 2026-09-20：按用户要求关闭旧计划并归档。保留原分项完成记录，不表示独立成品已交付。 当前执行入口：[M1 路线图](../../../../../docs/implementation/roadmap.md)。

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- application/workflows/task_execution
- scope/report/contract/resource/workspace组合preflight
- 首个模拟多Agent认知协作场景

## 前置依赖

T07, T09, T10, T11, T12。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 将所有模块证据组成带revisions/digest的PreflightResult
- 实现claimed/start原子核验及Grant签发、submit撤权/Lease和review
- 实现block保存快照、resume重新准备，相关scope blocker与无关工作继续
- 完成两Agent显式分歧→契约→任务结果的持久端到端场景

## 验收标准

- [x] 任何输入变更使旧preflight失效，无半启动（PreflightResult digest 复核）
- [x] blocked仍可报告/协商但不能执行
- [x] 用户无响应不timeout，resume不自动start
- [x] 流程层无自有领域表且仅用public端口

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。

## 本轮补充验收

- [x] coordination-walkthrough中的main+A+B事实轨迹通过，claim/resume只准备，start才执行（`tests/unit/test_task_execution.py`）。
