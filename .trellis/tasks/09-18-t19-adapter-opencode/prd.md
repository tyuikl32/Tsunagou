# T19 OpenCode正式共同基线适配

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

- [ ] 11项通过且和Codex用同一conformance口径
- [ ] plugin关闭/能力下降转相应degraded或降级
- [ ] 模型不能指定sender/owner
- [ ] 不复制领域Schema或绕REST授权

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
