# T10 认知报告、分歧、契约和风险

> 2026-09-20：按用户要求关闭旧计划并归档。保留原分项完成记录，不表示独立成品已交付。 当前执行入口：[M1 路线图](../../../../../docs/implementation/roadmap.md)。

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- Report/Discrepancy/Contract/Risk实体与端口
- 确定性规则registry
- 契约hash与proxy测试

## 前置依赖

T08。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 实现版本化认知报告和显式claims/uncertainties，报告边界校验
- 实现显式分歧和固定类型/字面/hash/resource规则及去重
- 实现proposal不可变payload/participants、全required exact digest接受和获准proxy
- 实现main风险请求/建议、120秒fallback、input digest风险接受有效性

## 验收标准

- [x] 无语义模型/文本相似度硬判定（仅显式 Claim 结构和固定 rule registry）
- [x] 参与者或内容变化需新proposal及新接受（immutable digest/supersede）
- [x] proxy保留真实actor，policy不允许则拒绝
- [x] 风险接受不能越ceiling或把unknown判成功

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
