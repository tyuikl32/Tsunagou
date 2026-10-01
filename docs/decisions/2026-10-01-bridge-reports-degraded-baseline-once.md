# D187 降级会话的重报，由 bridge 在同一次工具调用里自己补

日期：2026-10-01
状态：已实施（`packages/bridge-server`）

## 问题

宿主第一次连上时报的基线可能缺一项。典型情形是：这一次调用手上没有票、也还没有自己的会话文件，
于是 `identity.continuity_evidence` 只能是 `unknown`，会话落在 `provisioning`、角色停在 `worker`。

要紧的是，**会话变成 `ready` 的那一次调用，正是 daemon 顺手任命主 Agent 的那一次**
（`modules/authority.py`：`redeem_ticket` / `rebind` 里 `status == "ready"` 才 `appoint_main`）。
把这"再报一次基线"留给模型的下一个工具调用来触发，等于让"连上之后只回一段话、不再调工具"的会话
永远停在 provisioning、角色永远停在 worker。真机上的现象就是这样：前端向导走到第 3 步、显示接入
完成，项目名单里却只有一个子 Agent，主 Agent 从未出现。

机器其实已经在了：`CredentialHandoff.prepare()` 在会话不是 ready 时本来就会附上 `probe_payload`，
会话文件也在第一次调用里写下来了 —— 缺的只是"同一次工具调用里再走一趟"。

## 决定

1. `executeTool()` 拿到会话后，若 `baseline_status !== "ready"`，**再重报一次**（`recover(true)`，
   即一次带上新基线的 `session.reconnect`）。只补一次；补不成就保留第一次拿到的会话，不把一次
   本来可用的调用变成错误。
2. 基线必须按"这一刻磁盘上有什么"现算。续接证据的两个输入（票、会话文件）会在调用过程中变：
   第一次兑换把会话文件写下来、把票删掉。用调用开头那份快照，紧接着的重报会把"已经接上了"
   又说成"还没有续接证据"，白报一次。

## 不做的事

- 不动 `identity.continuity_evidence` 的归属。它"自称入会话前可证、实际要么由票平凡满足、要么
  要求第二次连接"这件事已单独评审，是否把它挪出准入（B2）是另一个决定，本轮只做 D。
- 不试图补 `context.project_read`：第二次重报的还是同一个目录、同一个摘要。窗口开错目录只能靠
  提示兜住（等待遮罩写明"请在「`<项目目录>`」下打开/重载窗口"）。

## 验证

- `pnpm --dir packages/bridge-server run test:credentials`：**27/27 通过**，含新增用例
  「a first call that lands degraded re-reports once and comes back ready」——enroll 回 `degraded` 后，
  同一次工具调用里恰好发生一次 `session.reconnect`（带 `probe_payload`），会话落成 `ready`／epoch 2。
- 同一命令里两个 late-ticket 冒烟（普通模式与 `--implicit-session`）均 `passed`。
- **未做真实宿主验收**：本轮只在进程级 harness 里验证，真机接入复测留给下一轮。
