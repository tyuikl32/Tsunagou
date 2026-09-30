# OpenCode 11 项共同基线实测

## 目标

使用真实 OpenCode 宿主（v2.0.18）对 OpenCode 适配器完成 11 项共同基线测试，修复发现的代码缺口，留下可复核的脱敏证据。

## 范围

- 11 项能力逐项实测，每项记录期望结果、实际结果、负例和脱敏证据
- 遇到项目代码缺口时定位、修复、运行相关测试
- 不修改发布门禁来制造通过结果
- 不自动 commit、push 或发布

## 11 项能力

1. identity.session_isolation — 两个真实会话的 Agent、Session、凭据及任务权限隔离
2. identity.continuity_evidence — resume、compact 保持身份；new、clear、fork 正确产生新身份
3. context.project_read — 读取正确项目和黑板，不串项目
4. command.typed_tools — MCP 工具结构及调用者身份约束正确
5. task.lifecycle — claim、preflight、start、block、resume、submit，拒绝旧 revision
6. cognition.report — 认知与分歧报告的作者身份可信
7. contract.participation — 接受准确摘要的契约，拒绝过期摘要
8. inbox.pull_fetch_ack — 拉取、读取和 ACK 分离，正文仅收件人可读
9. response.structured — 业务响应义务正确，ACK 不冒充响应
10. recovery.idempotent_reconnect — 重启恢复同一 Agent，拒绝旧 epoch，重试不重复执行
11. delivery.deduplicate — 重复或乱序投递不导致重复动作

## 验收标准

- 11/11 取得充分真实证据才能报告 supported
- 每项留下脱敏 evidence_refs、运行命令及退出码
- 记录 OpenCode 版本和 Git commit 标识
- 缺口如实标记 blocked/unknown，给出单步操作

## 约束

- 使用独立临时 Git 协调项目、真实 daemon、stdio MCP bridge 和真实 OpenCode 会话
- main 和 worker 必须使用不同 profile、配置及私有 session 文件
- 不读取或输出 token、ticket、私有 session 内容
- 不放宽身份、owner、scope 或用户专属权限边界来使测试通过
- 双 profile 接入不能替代 OpenCode 原生会话隔离测试
- 自动唤醒属于额外增强能力，单独报告，不计入这 11 项
