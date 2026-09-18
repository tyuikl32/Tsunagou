# 四宿主适配与共同 bridge-sdk

首发发布门禁覆盖 Codex、OpenCode、DeepSeek Harness 三个宿主。ZCode 适配器仍保留在共享 SDK、目录和研究矩阵中，但正式共同基线与首发验收后置；unknown 不得写成 supported。

`packages/bridge-sdk` 拥有协议客户端、私有凭据注入、command_id/重试、连接 epoch、probe 报告、inbox 拉取去重、MCP 传输、提示渲染、后台 Lease 续租和诊断。四 adapter 只负责宿主生命周期、可信 conversation ID、工具/上下文入口和增强能力，不重定义领域协议。

daemon 的共享项目 MCP 服务由官方 Python SDK 接入 FastAPI/ASGI；官方 TS SDK 仅用于 bridge 所需传输/stdio 转发。每连接独立 HostSession，不共用全项目 token。SDK 具体 API 和版本由 T02 实测，不臆造厂商方法。

## 正式共同基线

服务端注册 `collaboration_baseline_v1`，逐项验证，adapter 不能自报一个通过布尔值。

| capability ID | 必需实测证据 |
|---|---|
| identity.session_isolation | 同目录两个会话产生不同身份和凭据，不能交叉操作 Attempt |
| identity.continuity_evidence | resume/compact 保持 ID，new/clear/fork 不同 |
| context.project_read | 正确项目摘要与黑板入口，不串项目 |
| command.typed_tools | schema 与 REST 语义一致，不能自报 actor |
| task.lifecycle | claim/preflight/start/block/resume/submit 与旧 revision 拒绝 |
| cognition.report | 显式认知与分歧读写，作者可信 |
| contract.participation | exact proposal digest 接受，旧 hash 无效 |
| inbox.pull_fetch_ack | 无 push 仍能拉取与 ACK，正文仅 recipient |
| response.structured | 业务响应绑定义务，ACK 不代替响应 |
| recovery.idempotent_reconnect | 重启恢复同 Agent，旧 epoch 拒绝 |
| delivery.deduplicate | 重传不重复动作，不循环注入已 fetch 正文 |

增强单列 `wake.push`、`tool_gate.file/command/network`、`managed_launch`、`managed_stop`、`model_presented_evidence`。每项 status=supported/unsupported/unknown，strength=advisory/observed/enforced，带来源和证据摘要。无 pre-tool hook 不能称 enforced；Full Access 不会让系统拥有 OS 沙箱。

## 四条接入路线

| adapter | T02 核验的官方接入面 | 关键难点 |
|---|---|---|
| Codex | CLI/App Server/MCP 与已发布 hooks，固定版本 | thread ID 的 resume/compact/fork 语义；工具身份不来自模型 |
| OpenCode | 官方 SDK、Sessions API、plugin 事件/MCP | 多 session 隔离、事件连续性与工具调用绑定 |
| ZCode | 官方 Hook/session_id、SessionStart 来源、MCP | hook 是否实际启用，clear/fork 与恢复 ID 变化 |
| DeepSeek Harness | 官方 session 事件/持久对象与工具扩展 | 分支与恢复证据、重复事件、实际工具入口 |

这是研究候选路线，尚未完成当前版本真宿主验证。T02 必须保存官方 URL、版本、最小 probe、脱敏结果和可行性结论。不凭产品名猜接口；DeepSeek 模型 API 不是 Harness。宿主未安装或资料不足就标具体缺口，其他内核工作可以继续；不能因此把 diagnostic-only 算正式支持。

## 身份、凭据与生命周期

统一输入含 `adapter_installation_id,host_kind,host_conversation_id,parent_host_conversation_id?,lifecycle_event,host_version`。ID 来自原生宿主或可靠绑定的对话生命周期；禁用 PID/cwd/显示名/LLM 自报。core 只做规范字符串比较并持久 keyed digest，原 ID 不进日志、prompt、共享 Git。installation UUIDv7 升级保持，重装/reset identity 新建。

token 由 bridge 私有内存/当前 OS 用户私有文件持有，经 header 注入；静态 MCP 配置只包含命令和非秘密 profile 引用，不写 args/env token。control token 不给 adapter。多个组件共享同一个逻辑 Connection。

attach 收集 probe 后兑换 ticket，ready 或 diagnostic-only。resume CAS 新 connection epoch 并新快照；配置/插件变化显式 reprobe；不在每条普通命令执行慢 probe。必需能力下降冻结相关业务 Grant 并收敛执行；增强下降只禁增强。上升不自动扩大权限或恢复任务。

Lease 续租与 transport 独立于 LLM 轮次；挂起先释放执行 Lease。无 wake 不强制外部重启对话，用户打开时 pull/blackboard 恢复。只有真实宿主呈现证据才标 presented。

## 本项目端口与交付

TS adapter 接口为 `getIdentity/probeCapabilities/installTools/renderContext/observeLifecycle`；增强为 `wake/gateTool/observeTool/launch/stop`。这些是本项目接口名，不是厂商 API。返回结构包含不可用分支与证据，不以空字符串伪造成功。

T17 实现共享 SDK，T18–T21 各自 adapter。两层测试：同一 host simulator conformance；真实宿主正式版本窗。每个 adapter 的 11 项 baseline 全过、增强如实降级、错误/身份/token 隔离通过、安装卸载诊断可复现才算完成。一个 adapter 通过不替代另三个实测。
