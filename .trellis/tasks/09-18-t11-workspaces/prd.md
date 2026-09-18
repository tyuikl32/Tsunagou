# T11 隔离驱动、工作空间与Git请求

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- shared/worktree/external drivers
- IsolationDecision/Baseline/Result/GitActionRequest
- Git只读allowlist与manifest核验

## 前置依赖

T09, T10。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 实现driver候选与hard constraints校验，不规定单一默认隔离
- 把worktree创建/移除及所有Git写操作转为main请求，daemon仅核验
- 实现baseline/result、单repo worktree、未提交patch引用和多repo部分结果
- 实现integration/cleanup计划与terminal+checkpoint屏障，dirty强制user-only

## 验收标准

- [ ] 抓取daemon Git调用无mutation或网络Git
- [ ] 无main时保持pending不兜底执行
- [ ] dirty/untracked baseline、HEAD变化明确阻塞
- [ ] 清理不跨scope，最后副本风险单独控制

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
