# 按需唤醒补位实测记录 — 2026-10-04

## 环境与范围

Windows，本机已安装 OpenCode **2.0.18**，原有后台服务。只创建了一个隔离临时目录中的受控宿主会话，权限为 deny-all，要求测试回复且禁止工具/入组/其他项目操作。没有接入新的真实 Tsunagou 项目成员，没有修改用户既有会话或宿主审批模式。

项目权限层使用测试 fixture 创建的两个已认证 Worker；目标绑定受控真实 OpenCode 会话。经 `CommandDispatcher` 的 `coordination.wake_status` / `coordination.wake` 调用真实 Python→PowerShell→OpenCode 链路。**身份和项目数据是测试夹具，OpenCode 服务、原会话及执行记录是真实的**，不等同于两个已接入生产项目的 Agent 端到端验收。

## 观察结果

- 目标原会话查询成功；会话目录与协调 fixture 目录不同，仍正确识别原会话。
- 状态查询返回 `idle`，版本 2.0.18，排队能力为真，提供显式 wake 入口。
- 显式 wake 返回 `queued`；它只证明宿主受理，没有被冒充为业务回应或收件箱呈现。
- 受控原会话产生 **1 条 user 输入和 1 条 assistant 执行记录**。默认模型 `opencode/fledge-alpha-free` 随后返回 `provider.auth` / 403，说明免费模型拒绝该外部客户端调用；未得到测试业务回复。
- 再次 status/wake 返回 `request_already_delivered`，同会话仍只有 1 条 user 输入，没有重复入队。
- 额外通过实际 bearer 认证入口重新检查同一测试消息，仍返回 `request_already_delivered`，未追加输入；测试凭据未输出或提交。
- 通用返回保持 `host_turn_started=false`：当前宿主活动接口没有本消息的回合关联证据，不用受控测试中的单一输入推断规则替代通用证据。

初次直接访问本地 HTTP 接口返回 `UnauthorizedError`。实现据此改为官方已安装 CLI 的 `opencode api` 内部认证；没有读取或输出凭据，没有新增 token 参数。CLI 与服务版本都核实后才操作原会话。

## 验收边界

已证明受控原会话可经认证 Worker 入口驱动，且重复调用不追加输入。模型业务回复被宿主默认提供商拒绝，不能宣称完整业务闭环通过；没有自动替换模型、权限或配置。DeepSeek Harness 本轮返回明确未验证/不支持，未宣称实际唤醒通过。Codex 原生唤醒未被本轮脚本替代。

结构化、已脱敏的观察保存在任务目录 `live-opencode-evidence.json`；不包含原始宿主会话标识、端点或凭据。异常状态和权限矩阵另由模拟宿主、协议与真实 stdio bridge 回归覆盖，不将这些测试冒充真实多宿主项目验收。

临时会话与目录的组合清理操作被自动审批规则拒绝（仅返回 `blocked by policy`），因此隔离测试内容暂时保留，未绕过规则重试删除。
