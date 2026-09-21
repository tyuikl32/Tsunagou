# T15 重大决定、完成、继任与Lineage转换

> 2026-09-20：按用户要求关闭旧计划并归档。保留原分项完成记录，不表示独立成品已交付。 当前执行入口：[M1 路线图](../../../../../docs/implementation/roadmap.md)。

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- UserDecision/Completion/Archive/Reactivate workflows
- AuthorityTransition/AgentSuccession
- ReplicaActivate/LineageReset/OperationResolution

## 前置依赖

T13, T14。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 实现精确revision/digest用户控制决定，不从宿主对话伪造批准
- 实现completion当前Attempt收敛，completed立即事务生效，checkpoint异步屏障
- 实现handoff/succession冻结/收敛、义务替换、新契约与残余风险
- 实现新lineage unassigned/新runtime无旧授权、显式恢复任务；unknown追加Resolution

## 验收标准

- [x] 用户沉默无限持久不拒绝/失败（UserDecision 无 deadline fallback）
- [x] checkpoint失败保留completed，归档受阻但repair可用
- [x] 旧owner/session/grant在继任和reset后不能复活（reset_runtime）
- [x] 用户ceiling/项目完成等固定边界不能被main风险接受绕过（user_control exact digest）

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
