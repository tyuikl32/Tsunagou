# T17 共享Bridge SDK与适配器一致性测试框架

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- packages/bridge-sdk
- host-neutral Adapter接口和simulator
- 统一conformance harness

## 前置依赖

T16, T02。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 实现身份/私有凭据/connection、typed client和重试去重
- 实现共享MCP和逐session stdio转发，模型看不到token
- 实现inbox调度/提示裁剪/后台Lease renew与诊断
- 实现全部baseline与增强降级的统一mock-host验收

## 验收标准

- [ ] 两个session无凭据/上下文串用
- [ ] 断线/重传/旧epoch同协议预期
- [ ] 未知呈现/停止证据不虚报
- [ ] 四adapter仅做宿主翻译，不复制协议/任务状态机

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。

## 本轮补充验收

- [ ] attach与managed_launch增强分开；票据签发和bridge兑换保持不同principal，不能复制main token。
