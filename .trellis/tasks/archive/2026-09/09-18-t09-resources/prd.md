# T09 资源冲突、等待与Lease

> 2026-09-20：按用户要求关闭旧计划并归档。保留原分项完成记录，不表示独立成品已交付。 当前执行入口：[M1 路线图](../../../../../docs/implementation/roadmap.md)。

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- ResourceIntent/LeaseSet/WaitQueue
- Lease时钟/续租/到期流程
- scope和冲突属性测试

## 前置依赖

T08。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 实现规范path/named资源key及physical alias归一
- 实现read/consistent_read/exclusive_write/exclusive_use冲突矩阵与all-or-none获取
- 实现TTL120/renew30、FIFO+aging、无抢占，claimed预留
- 到期/离开running时同UoW撤许可并释放，外部观察仅证据

## 验收标准

- [x] 交叠prefix冲突正确，普通read不假装快照（canonical ResourceKey 与冲突矩阵）
- [x] 旧session/execution epoch不能续租（renew 精确校验 epoch/scope）
- [x] blocked无execution Lease，wait不自动start
- [x] 物理Agent仍跑时保留残余风险，不声明强制停止（external observation 仅记录证据）

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
