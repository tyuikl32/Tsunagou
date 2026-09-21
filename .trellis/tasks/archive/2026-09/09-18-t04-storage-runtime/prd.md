# T04 SQLite事务、事件与持久Operation运行时

> 2026-09-20：按用户要求关闭旧计划并归档。保留原分项完成记录，不表示独立成品已交付。 当前执行入口：[M1 路线图](../../../../../docs/implementation/roadmap.md)。

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- platform/db和durability核心
- UoW、Alembic、events/commands/outbox/operations/jobs
- 真实SQLite并发与故障测试

## 前置依赖

T03。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 建立每项目单writer队列、OS lock、WAL/FULL/FK和一致读snapshot
- 实现事务内授权回调、幂等hash/result、event_seq与outbox原子写
- 实现Operation/Job/JobAttempt、worker lease、timeout/backoff、effect分类和unknown处理
- 启动恢复登记项目未完成工作；迁移前备份，失败只读诊断

## 验收标准

- [x] commit前后崩溃不丢状态或重复动作（事务回滚与已提交 command_id 重放由 `tests/unit/test_storage_runtime.py` 覆盖；跨进程 crash 注入列为后续专项）
- [x] 同command_id不同hash冲突，旧epoch不能借重放绕权限（`IdempotencyConflict` 与 `rotate_runtime_epoch`/`assert_runtime_epoch`）
- [x] 外部效果未知不盲目重试，Resolution只追加（unknown 状态、外部 lease 过期和 append-only resolution 已覆盖）
- [x] 两个本机writer互斥；Job超时不解释用户沉默（OS lock、lease recovery 与 retry/unknown 分流；双进程压力证据留待专项）

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
