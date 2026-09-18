# T22 脱敏审计、指标与实验运行框架

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- evaluation模块、structlog与可选OTel
- ExperimentDefinition/Run/Result/Report
- A/B/C/D数据集和指标采集框架

## 前置依赖

T04, T07, T08, T10。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 实现脱敏事件投影/只读审计，权限过滤不可被main绕过
- 实现intervention/rework/latency/token来源与availability口径
- 实现固定实验定义digest、随机种子、预算/版本记录和原始结果引用
- 实现报告Job及统计，不删除失败样本；OTLP默认关闭

## 验收标准

- [ ] secret哨兵不会经日志/error/export/telemetry泄漏
- [ ] 无usage标unavailable不是0
- [ ] 审计不能修改业务真相
- [ ] 统计对相同输入可复现，样本/限制公开

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
