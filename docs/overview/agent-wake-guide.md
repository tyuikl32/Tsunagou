# Agent 原会话唤醒操作指南

需要其他 Agent 开始处理已分派的工作时，默认通过 PowerShell 使用目标宿主的原会话入口；**发起方和接收方均为 Codex 时，沿用已有 Codex 唤醒机制**。本文是操作指引，提醒 hook 本身不会执行命令或发送消息。

优先读取当前安装源码内的本文；[在线入口](https://github.com/tyuikl32/Tsunagou/blob/HEAD/docs/overview/agent-wake-guide.md) 随仓库发布更新，未发布的本地更新以安装源码为准。

## 先确认目标与是否需要操作

核对目标 Agent、宿主、机器和原会话。目标已在处理同一请求时不要重复唤醒。Tsunagou Agent ID 不等于宿主会话 ID，不能把昵称或自己编造的 ID 传给宿主作为原会话。跨机器时，应在目标宿主所在机器上通过已有授权入口操作，本机 PowerShell 不能凭空控制远端 Desktop。

**不要把尚未完整实现或未经当前宿主验证的 Tsunagou 自动唤醒作为继续协作的前提。** 已可用的唤醒路径可继续使用；若明确返回 unsupported、未配置、无绑定或无法访问原会话，记录具体原因，转向下列宿主入口。不要反复运行 hostwake 配置、probe、prepare/connect 或重绑来等待一次普通唤醒成功。接入 ready、`host_binding:null` 和宿主自动唤醒是不同事实。

## Codex

双方均为 Codex 时，使用当前宿主已提供且已验证的原会话唤醒/跟进工具，按工具的真实参数定位原会话；不要为本提醒替换已工作的机制。若当前工具目录没有该入口，不要猜工具名或伪造会话。

跨宿主发往 Codex 时，通过 PowerShell 调用部署中已验证的 Codex 原会话入口。先读该入口的本机操作说明，确认它实际连接到持有目标会话的宿主；本指南不把 CLI resume 视为任意 Desktop 会话的通用唤醒方式。原 Desktop 的 writer 冲突不能通过删锁、另建身份或反复启动外部进程解决。找不到可用入口时，按下文失败排查流程自行定位原因，不把操作转交用户。

证据入口：[已验证的原 Desktop 协作记录](../acceptance/evidence/live-repair-20260928T150917Z/operator-review.md)、[历史外部 resume 冲突及限制](../acceptance/evidence/sega-image-manage-tool-2026-09-28/native-wake-followup.md)。历史限制不否定后来已验证的路径，也不证明任意安装都已配置成功。

## OpenCode

在目标机器的 PowerShell 先检查已安装版本及其帮助：

```powershell
opencode --version
opencode run --help
```

本仓库 [OpenCode v2.0.21 实测记录](../acceptance/cross-machine-step0-2026-10-02.md) 使用 `opencode run --session <会话ID> --model <模型> --auto "<提示词>"` 驱动回合，提示词是位置参数，不是 `--prompt`。历史实测包含 `--auto`，但唤醒不能改变用户批准模式，因此下方示例不添加它。仅当本机帮助支持这些参数，且已确认原会话真实存在、模型配置有效、没有并发驱动冲突时，才可按此形状操作；保留原有权限与审批设置：

```powershell
# 示例占位符必须换成已核对的真实值；不能直接照抄运行。
$targetSession = '<已存在的原会话ID>'
$targetModel = '<该会话使用的已配置模型>'
opencode run --session $targetSession --model $targetModel '请读取自己的 Tsunagou 项目上下文和收件箱，按已有授权处理待办。'
```

该宿主曾允许指定不存在的 ID 创建新会话，因此不能仅凭命令返回成功就认定恢复了原 Agent。无法验证原会话或当前版本入口不匹配时，自行核对注册信息与实际版本的会话入口，不创建替代会话。

## DeepSeek Harness

先在目标机器确认已安装的 DSH launcher；使用其完整路径在 PowerShell 调用 `--help`，以实际版本的会话操作说明为准。不要临时用 `npx` 下载另一个版本来尝试唤醒，也不要把 `tsunagou_connect` 当唤醒命令。

当前 [DeepSeek Harness 验收说明](../acceptance/deepseek-harness-11-baseline-2026-10-01.md) 记录了 web 会话的 `session/prompt` 入口及 `mode: queue|steer`，**这不证明普通 Desktop 可用同一接口**，也不提供可直接复制的通用 PowerShell 唤醒命令。只有已验证的当前宿主接口、端点与原会话映射均存在时才使用该接口；不要猜 URL、端口、身份或请求结构。无此部署说明时，自行检查已安装版本的帮助、宿主源码或现有操作说明，确认 Desktop/web/TUI 的实际控制入口；不要要求用户手动唤醒。

## 唤醒失败时先自行排查

1. **先反思是否认错了目标厂商或宿主。** 从真实身份和注册信息核对接收方的 adapter、所在机器及实际运行宿主。模型品牌、昵称和发起方宿主都不是接收方宿主的证据，例如 OpenCode 使用 DeepSeek 模型不等于 DeepSeek Harness。
2. 核对原会话 ID、实际版本、端点与选择的原生操作是否匹配；不要把 Agent ID 当宿主会话 ID，也不要把 web API 当通用 Desktop API。按当前安装的帮助、源码和本机部署记录自行调查。
3. 有证据表明选错宿主、会话或操作后，修正调用并确认上次未已触发回合，再尝试正确路径。不要盲目重复同一失败命令，不要陷入 Tsunagou 自动唤醒配置或重绑循环。
4. 不请求用户手动唤醒。若自行调查后仍存在真实能力缺口或权限阻塞，记录已确认的宿主、尝试入口、具体错误与未解决状态，通过现有协作消息渠道向 main 报告；main 保留此阻塞供后续处理。不得伪造成功、接入替代身份或扩大既有权限。

## 确认结果与停止条件

- 命令成功、消息 accepted/queued、bridge ready 或 presentation 记录都不能单独证明新回合开始。核对原会话出现新回合，并由对方自己读取上下文/收件箱、处理或回复；不要替对方读取私有收件箱或 ACK。
- 若命令超时或结果不明，先核对目标是否已开始处理，再决定是否重试，避免重复回合。明确入口不支持或身份不匹配时停止该调用路径，按上述顺序自行排查并如实记录结果。
- 只传递必要的任务提示；不要把 token、ticket、bridge session 或私有路由文件内容放进命令、聊天或日志。唤醒不增加权限，不能借此接入新 Agent 或代用户确认。
