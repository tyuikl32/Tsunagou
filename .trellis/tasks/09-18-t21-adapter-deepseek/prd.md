# T21 DeepSeek Harness正式共同基线适配

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- packages/adapter-deepseek
- Harness具体版本与接入runbook
- 真宿主conformance证据

## 前置依赖

T17。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 确认T02指定Harness产品/版本及session事件对象，不以模型API替代
- 绑定持久conversation和新分支、处理重复事件/重启
- 接共享SDK工具/消息/黑板，声明可用enhancement
- 执行11项baseline与恢复/去重/并行会话真实验收

## 验收标准

- [ ] 11 项通过才正式支持；0.1.5-rc.2 临时家目录已证明 session isolation，但其余 10 项仍 unknown，未达到正式支持
- [x] 模型 API 调用成功不能当作 Harness 集成成功
- [x] 事件回放不重复业务动作（共享 command_id/去重层）
- [x] 与其他三 adapter 协议和身份语义一致

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
