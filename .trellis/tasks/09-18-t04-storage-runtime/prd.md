# T04 SQLite事务、事件与持久Operation运行时

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

- [ ] commit前后崩溃不丢状态或重复动作
- [ ] 同command_id不同hash冲突，旧epoch不能借重放绕权限
- [ ] 外部效果未知不盲目重试，Resolution只追加
- [ ] 两个本机writer互斥；Job超时不解释用户沉默

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
