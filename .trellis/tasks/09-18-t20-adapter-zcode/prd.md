# T20 ZCode正式共同基线适配（首发后）

状态：已规划，首发后置，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- packages/adapter-zcode
- ZCode Hook/MCP安装与诊断
- 版本/能力/生命周期实测记录

## 前置依赖

T17。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 采用T02确认的SessionStart/session_id和工具入口
- 验证hook实际启用、clear/fork与resume语义，不仅检测配置文件存在
- 接共享SDK和最小提示，对gate/wake准确声明强度
- 执行baseline与hook缺失/重复通知/重启真宿主测试

## 验收标准

- [ ] 11 项通过且 ID 连续性有证据（ZCode 未安装，保留 unknown）
- [x] hook 缺失不能假 ready/enforced
- [x] Full Access 仍遵守 API 角色边界
- [x] 安装/卸载可复现，敏感输出脱敏

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
