# T23 端到端与故障恢复发布门槛

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- tests/integration与fault_injection
- Windows CI/本机发布检查
- 端到端操作证据与缺陷清单

## 前置依赖

T15, T16, T17, T22。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 实现validation列出的12类最低故障，真实SQLite/Git/loopback
- 覆盖认知闭环、长期用户等待、继任、未知外部结果、完成物化失败、reset
- 校验全部命令权限矩阵、双语言fixtures、import边界与生成物
- 记录Windows基准/补丁和macOS/Linux实际支持范围

## 验收标准

- [ ] 无消息丢失/双owner/旧epoch授权复活
- [ ] 崩溃恢复不伪造成功和不盲重不可验证动作
- [ ] 所有工程阻断项通过，失败有最小复现
- [ ] mock adapter通过不冒称真宿主已完成

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
