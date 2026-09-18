# 四宿主与 MCP 可行性矩阵

核验日期：2026-09-18（Windows 11，Python 3.13.13，Node 24.19.0）。这是 T02 的研究证据，不等同于四个正式适配器已交付。原始会话 ID、token、转录和本机私密路径不写入仓库；证据只保存 keyed digest、状态和可复现原因。

## 环境与接入面

| 宿主 | 本机状态 | 目标接入面 | 结论 |
|---|---|---|---|
| Codex CLI/App Server | codex 0.154.0-alpha.6.2 可执行 | app-server --stdio、thread lifecycle、MCP | 已取得无模型轮次的协议/身份探针；完整共同基线仍 unknown |
| OpenCode | 未安装 | 官方 SDK/Session/MCP 资料待 T19 版本锁定 | unknown，不宣称支持 |
| ZCode Agent | 未安装 | z.ai 原生 session/hook/MCP | unknown；hook 资料要求变更后新会话，不能假设热生效 |
| DeepSeek Harness | 未安装 | deepseek-ai/deepseek-harness session/tool 扩展 | unknown；模型 API 不作为 Harness 证据 |

## 共同基线

状态只允许 supported、unsupported、unknown；unknown 不可用于 ready。当前 Codex 的无模型探针只能证明安装和部分生命周期协议，业务任务/认知/契约等项目功能保留 unknown。

| capability | Codex | OpenCode | ZCode | DeepSeek Harness | 证据 |
|---|---|---|---|---|---|
| identity.session_isolation | supported（两个 thread digest 不同） | unknown | unknown | unknown | Codex disposable probe |
| identity.continuity_evidence | observed（resume API 面） | unknown | unknown | unknown | 不把 API 存在当完整 ready |
| context.project_read | unknown | unknown | unknown | unknown | 需 bridge |
| command.typed_tools | unknown | unknown | unknown | unknown | 需共享 MCP |
| task.lifecycle | unknown | unknown | unknown | unknown | 需 T08/T17 |
| cognition.report | unknown | unknown | unknown | unknown | 需 T10/T17 |
| contract.participation | unknown | unknown | unknown | unknown | 需 T10/T17 |
| inbox.pull_fetch_ack | unknown | unknown | unknown | unknown | 需 T07/T17 |
| response.structured | unknown | unknown | unknown | unknown | 需 T07/T17 |
| recovery.idempotent_reconnect | unknown | unknown | unknown | unknown | 需独立 bridge |
| delivery.deduplicate | unknown | unknown | unknown | unknown | 需独立 bridge |

## 增强能力

| capability | Codex | OpenCode | ZCode | DeepSeek Harness |
|---|---|---|---|---|
| wake.push | unknown | unknown | unknown | unknown |
| tool_gate.file/command/network | unknown | unknown | unknown | unknown |
| managed_launch | observed（本机 app-server 可启动） | unknown | unknown | unknown |
| managed_stop | observed（探针可终止 disposable process） | unknown | unknown | unknown |
| model_presented_evidence | unknown | unknown | unknown | unknown |

## 运行证据与边界

- 探针入口在 tools/conformance/probes/<host>/；每个探针都使用一次性目录和独立环境，凭据过滤到子进程前。
- tools/conformance/probes/common.py 的 require_baseline 只有在 11 项全部 supported 且每项有 evidence_refs 时返回 true。
- 未安装宿主仍要保留缺口记录；不能用模拟器或模型 API 将 unknown 改成 supported。
- MCP 共享服务的 Python SDK、bridge 使用的 TypeScript SDK 和具体版本在 T02/T17 锁定；本矩阵只记录研究状态。
