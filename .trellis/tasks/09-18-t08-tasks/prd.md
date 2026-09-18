# T08 任务、Attempt、委派与验收状态机

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- tasks表/domain/public ports
- Task/Attempt/Result/Review状态机
- 原子claim与DAG测试

## 前置依赖

T06。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 实现create/ready/publish/claim与单owner current Attempt约束
- 实现block/resume准备态、submit/review/self/automated、cancel/orphan/recover
- 实现parent导航与blocks DAG独立，completed follow-up，精确子ResultRef
- 实现scope request/批准后撤Grant阻塞与批量restore_open端口

## 验收标准

- [ ] 并发claim一个owner；主权限不替代Attempt owner
- [ ] resume到claimed，start才running；关闭Attempt不复活
- [ ] 父终态不级联，孩子状态不自动挡父提交
- [ ] review exact result/round，返工新Attempt，batch全成或全败

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
