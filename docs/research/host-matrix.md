# 四宿主与 MCP 可行性矩阵

核验日期：2026-09-18（Windows 11，Python 3.13.13，Node 24.19.0）。这是 T02 的研究证据，不等同于四个正式适配器已交付。原始会话 ID、token、转录和本机私密路径不写入仓库；证据只保存 keyed digest、状态和可复现原因。

## 环境与接入面

| 宿主 | 本机状态 | 目标接入面 | 结论 |
|---|---|---|---|
| Codex CLI/App Server | codex 0.154.0-alpha.6.2 可执行 | app-server --stdio、thread lifecycle、MCP | 已取得无模型轮次的协议/身份探针；完整共同基线仍 unknown |
| OpenCode | `opencode-ai 1.18.31` 可通过 npm 临时运行 | headless server REST、Session、fork、MCP/OpenAPI | 已完成无模型轮次真实 probe；完整共同基线仍 unknown |
| ZCode Agent | 未安装；公开 npm/GitHub 结果只有非官方客户端或社区桥接 | z.ai 原生 session/hook/MCP | unknown；没有可锁定的官方 CLI/API 版本，hook 资料要求变更后新会话，不能假设热生效 |
| DeepSeek Harness | `@deepseek-ai/dsh 0.1.5-rc.2` 可通过 npm 临时运行 | deepseek-ai/deepseek-harness Web RPC、session/tool 扩展 | 已完成临时家目录的无模型真实 probe；完整共同基线仍 unknown |

## 共同基线

状态只允许 supported、unsupported、unknown；unknown 不可用于 ready。当前 Codex 的无模型探针只能证明安装和部分生命周期协议，业务任务/认知/契约等项目功能保留 unknown。

| capability | Codex | OpenCode | ZCode | DeepSeek Harness | 证据 |
|---|---|---|---|---|---|
| identity.session_isolation | supported（两个 thread digest 不同） | supported（两个 session 与 fork digest 不同） | unknown | supported（两个同目录 session digest 不同） | 各宿主 disposable/temporary-home probe |
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
| managed_launch | observed（本机 app-server 可启动） | observed（本机 `opencode serve --pure` 可启动） | unknown | observed（本机 `dsh web --no-open` 可启动） |
| managed_stop | observed（探针可终止 disposable process） | unknown | unknown | unknown |
| model_presented_evidence | unknown | unknown | unknown | unknown |

## 运行证据与边界

- 探针入口在 tools/conformance/probes/<host>/；会启动宿主的探针使用一次性目录和独立环境，外部 Web 服务探针必须由调用者用临时 Harness home 启动，凭据不写入证据。
- tools/conformance/probes/common.py 的 require_baseline 只有在 11 项全部 supported 且每项有 evidence_refs 时返回 true。
- 未安装宿主仍要保留缺口记录；不能用模拟器或模型 API 将 unknown 改成 supported。
- OpenCode 证据由 `tools/conformance/probes/opencode/probe.py` 对 `opencode-ai 1.18.31` headless server 产生；它只发送 session/project/fork/history/doc 请求，不发送模型 prompt。证据文件为 `docs/research/evidence/opencode-2026-09-18.json`。
- DeepSeek 证据由 `tools/conformance/probes/deepseek/probe.py` 对官方 `@deepseek-ai/dsh 0.1.5-rc.2` 产生；服务使用临时 `DSH_HOME`/`DSH_AGENTS_HOME`，通过官方 token→HttpOnly cookie 流程调用 `session/create`、`session/list`，不发送模型 prompt。证据文件为 `docs/research/evidence/deepseek-2026-09-18.json`；探针不接受用户持久家目录作为运行环境。
- DeepSeek 的认证与 Web RPC 依据官方 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)、[browser-auth.ts](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/connection/src/browser-auth.ts) 和 [session-controller](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/api/session-controller/src/index.ts)；token、cookie、session 原始 ID 不进入证据。
- ZCode 证据文件 `docs/research/evidence/zcode-2026-09-18.json` 由 `tools/conformance/probes/zcode/probe.py` 生成，明确记录 `executable_not_found` 和 11 项 unknown；非官方客户端不进入宿主支持证据。
- MCP 共享服务的 Python SDK、bridge 使用的 TypeScript SDK 和具体版本在 T02/T17 锁定；本矩阵只记录研究状态。
