# T18 Codex正式共同基线适配

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- packages/adapter-codex
- Codex安装/卸载/诊断指南
- 真实版本窗与conformance证据

## 前置依赖

T17。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 采用T02已验证的Codex官方会话/工具接口，绑定installation和conversation
- 连接共享SDK，处理resume/compact/new/clear/fork事件与工具调用上下文
- 映射实际可用hook/wake/gate，不修改用户全局Full Access设定
- 执行11项baseline与跨同目录会话、重启、故障真宿主验收

## 验收标准

- [ ] 11项全部通过才ready/正式支持
- [ ] 无可靠ID就diagnostic，不用猜测
- [ ] 增强矩阵与实际启用配置一致
- [ ] 安装可逆且不把token写prompt/env/MCP args

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
