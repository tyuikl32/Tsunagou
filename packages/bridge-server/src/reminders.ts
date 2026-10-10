import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readPrivateJson, writePrivateJson } from "./private-file.js";
import { withPrivateFileLock } from "./private-file-lock.js";

/** Presentation-only guidance. Explicit wake tools alone execute host operations. */
// 版本号一改，**已经见过旧提示**的会话会在下一次 context.project_read 时重新收到一遍
// （reminderContent 按 guide_version 去重，见文件末尾）。所以新增一条首次提示必须同时抬版本，
// 否则装了新桥的老会话永远看不到它。
export const GUIDE_VERSION = "wake-v10-first-read-slim-instructions-2026-10-08";
/** 手册相对 checkout 根的位置；找不到文件时发出的就是这条相对路径。 */
export const OPERATING_MANUAL_RELATIVE_PATH = "docs/overview/agent-operating-manual.md";

/** 这台机器上手册的**绝对**路径，解析自桥自己所在的位置（下面两条提示都用它）。
 *
 * 为什么必须绝对：手册住在**源码 checkout 里**，而指路是相对路径时，"去读手册"就等于
 * "先找到 checkout" —— 2026-10-08 实测里会话正是为了 `expected_physical_identity` 的来源
 * 去翻源码的，那趟寻找就是我们要消掉的东西。桥知道自己在哪（`dist/` 的上一级、上上级…），
 * 所以这件事只有它能答；远端 Worker 的副本位置不同，各自解析各自的那份。
 *
 * 与 server.ts 的 `commandSchema` 同一套办法：**从模块自身位置往上探**，不写死盘符。
 * 找不到就返回相对路径 —— 没带文档的桥只是退化成今天的样子，而不是编一个不存在的路径。*/
export function operatingManualPath(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  // dist/reminders.js 与 dist/server.js 同目录；src 下与 server.ts 同目录，src→dist 不改变深度。
  for (const root of [join(here, "..", "..", ".."), join(here, "..", "..")]) {
    const path = join(root, OPERATING_MANUAL_RELATIVE_PATH);
    if (existsSync(path)) return path;
  }
  return OPERATING_MANUAL_RELATIVE_PATH;
}

/** 按需手册的位置。字段与拒绝码、边界都在里面，**不必去读 Tsunagou 源码**。 */
export const OPERATING_MANUAL_HINT = `字段、拒绝码与边界（含 expected_physical_identity 这类必填值从哪来；不要为查这些去读 Tsunagou 源码、也不要绕开桥）：${operatingManualPath()}。`;

/** MCP `instructions` 里那一句：它**每次模型调用**都要付一遍，所以只留"手册在哪、它回答什么"。
 *
 * 为什么只留这一句：2026-10-08 的实测里，每次调用都在付的那段文本有 840 字符（约 210 token），
 * 其中唤醒通道、"在哪读上下文""主 Agent 怎么派活"这些**每会话只需要听一次**的内容都挤在这里。
 * 它们已经各有更合适的落点 —— 唤醒指引进每会话首次读取（`WAKE_REMINDER`），入口句进
 * `FIRST_READ_GUIDANCE` —— 而这里留下的手册指路是唯一"看不到就会做错事"的那条：字段、拒绝码与
 * 边界都在手册里，会话看到它就不必（也不该）去读 Tsunagou 源码、或绕开桥手搓 HTTP。
 *
 * 绝对路径由桥从自己的安装位置解析（见 operatingManualPath）：相对路径等于让会话先去找 checkout，
 * 那正是 2026-10-08 白跑的那几趟。文档不在时退回相对路径，句子仍然成立。*/
export const OPERATING_MANUAL_LINE = `Per-command required fields (including where expected_physical_identity comes from), refusal codes and why the bridge must not be bypassed: ${operatingManualPath()}.`;
/** 每会话首次读取那条通道的入口句：instructions 里只留最短指路，其余内容都在这里交付。 */
export const FIRST_READ_GUIDANCE = "开工前先调一次 context__project_read，并在每个自然停顿（做完一小步、跑完一次构建或测试）后重读：本机工作目录与唤醒指引都由它交付；写文件、派活、契约与验收的规矩也在同一处。";
export const WAKE_REMINDER = "main 和 worker 均可在已有权限内唤醒协作者。先用 coordination__peer_hosts 核实并记住宿主、版本和机器，不凭模型品牌猜测。Codex → Codex 只走现有 Tsunagou Codex 通道（默认开启，尊重明确关闭）；其他宿主先查 coordination__wake_status {message_id}，按返回入口操作：返回值里的 delivery 说明这个宿主**什么时候**能把消息送进去（step=下一个步骤边界、turn_boundary=下一回合、idle_only=只在空闲、none=没有唤醒路径、unknown=读不到证据），声明与实际不一致时带 degraded，不静默降级。DSH Desktop 既有插件后台排队、也有 daemon 自动投递（绑定未核实时报 host_binding_not_found：那表示这条自动通道不可用，不等于 DSH 不能唤醒）。跨机器（远端）没有唤醒路径：消息留在本机收件箱，等对方自己来取，不要重试唤醒或换入口绕过。当前工具不支持不等于宿主不能唤醒；独立宿主操作须核实原会话、授权及同一消息无在途或结果未知的执行，不绕过认证。入队不等于已处理；失败核对宿主与错误，勿循环重试，不要求用户手动唤醒。操作指南：docs/overview/agent-wake-guide.md（本机安装源码优先）；https://github.com/tyuikl32/Tsunagou/blob/HEAD/docs/overview/agent-wake-guide.md。";
export const COMPLETION_REMINDER = "如果所有工作已经完成，且合并与验收已通过，请记得调用 `project__completion_propose` 发起任务完成提案，不要仅在聊天中宣布完成。已有待确认的提案时不要重复提交，最终完工由用户确认。";

/** 告诉这个会话：它在**这台机器**上的工作目录是哪里。
 *
 * 为什么由桥来说：daemon 的上下文快照**故意不含绝对路径**（`context_project_read` 的原话是
 * "No token, credential or absolute path enters the snapshot"）—— 主机不可能知道远端 Worker 的
 * 副本在哪，Worker 也不该拿到主机的路径。而桥跑在各自机器上、配置里就有本机的那份
 * `TSUNAGOU_PROJECT_ROOT`（远端导入时它就是代码副本），所以只有它能回答这个问题。
 *
 * 这是"指路"，不是授权：能不能改由任务的 execution_scope 决定。没有它，Worker 手上一个地址都
 * 没有，只能自己找 —— 2026-10-05 的实测就是它读并写进了隔壁实验组的目录（事件 C001）。
 * 与唤醒指引一样**每个 guide 版本说一次**：被告知过的会话不需要反复听。*/
export function workingRootGuidance(projectRoot: string): string {
  const path = projectRoot.trim();
  if (!path) return "";
  return `你在这台机器上的工作目录是：${path}。只在这个目录里改动；任务声明了范围时，以那个范围为准。`;
}

type Row = Record<string, unknown>;
const row = (value: unknown): Row => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
const digest = (value: unknown): string => createHash("sha256").update(JSON.stringify(value)).digest("hex");
const text = (value: unknown): string => typeof value === "string" ? value : "unknown";

export function needsCompletionContext(kind: string): boolean {
  return kind === "task.review.accept" || kind === "task.self_accept";
}

export function reminderMessageIds(kind: string, result: unknown, args: Row): string[] {
  const value = row(result);
  const ids: unknown[] = [];
  if (kind === "coordination.plan" && Array.isArray(value.assignments)) {
    for (const assignment of value.assignments) ids.push(row(assignment).message_id);
  }
  if (kind === "message.send" && row(args.response_contract).required === true) ids.push(value.message_id);
  return [...new Set(ids.filter((id): id is string => typeof id === "string" && id.length > 0))];
}

export function needsWakeContext(kind: string, result: unknown, args: Row): boolean {
  return kind === "task.submit" || reminderMessageIds(kind, result, args).length > 0
    || kind === "coordination.wake_status" || kind === "coordination.wake";
}

function compactHint(status: Row, kind: string): string {
  const target = row(status.target);
  const messageId = text(status.message_id);
  const reference = JSON.stringify({ message_id: messageId });
  const identity = `目标 ${text(target.agent_id)}，宿主 ${text(target.host)} ${text(target.version)}，位置 ${text(target.machine)}`;
  const progress = row(status.progress);
  const facts = `投递=${String(progress.durably_received ?? "unknown")}；宿主回合=${String(progress.host_turn_started ?? "unknown")}；已呈现=${String(progress.presented ?? "unknown")}；业务回复=${String(progress.business_response ?? "unknown")}`;
  let next = `先调用 coordination__wake_status ${reference} 核对状态。`;
  if (status.lane === "native") {
    const native = row(status.native);
    next = `沿用 Tsunagou Codex 原生通道，不切换补位；路由不代表已派发。开关=${String(native.enabled ?? "unknown")}，投递=${text(native.outbox_status)}，尝试=${String(native.attempt_count ?? "unknown")}/${text(native.attempt_state)}。`;
    next += native.enabled === false
      ? "项目已明确关闭自动唤醒，尊重设置并报告阻塞。"
      : "按原生执行记录推进；unknown 不代表未运行。";
  }
  else if (status.lane === "unsupported" || status.result === "unsupported") {
    next = "当前工具路径不支持，不等于宿主不能唤醒。核对宿主和原因，按 docs/overview/agent-wake-guide.md 判断已有授权的同机操作；须确认同一消息无在途或结果未知的执行，不绕过认证。无法解决时 worker 向 main 升级一次，main 记录阻塞。";
  }
  else if (status.result === "queued" || status.result === "request_already_delivered" || status.result === "pending"
    || status.result === "same_request_running" || status.result === "already_delivered"
    || (status.state === "running" && status.request_associated === true)) next = "该请求已受理或正在处理，等待对应结果，不追加回合。";
  else if (status.result === "failed" || status.result === "unknown" || status.retry_allowed === false
    || (typeof status.error_code === "string" && status.error_code.length > 0)) {
    const uncertain = status.preflight_failed !== true
      && (status.result === "unknown" || status.prior_result === "unknown" || status.prior_result === "starting");
    next = uncertain
      ? kind === "coordination.wake_status"
        ? "本次已查询；无新证据不循环查询，结果未知不再次唤醒。"
        : `结果未知，调用 coordination__wake_status ${reference} 核实，不重发。`
      : "核对宿主与错误，参考 docs/overview/agent-wake-guide.md；独立操作须确认同一消息无在途或结果未知的执行，不绕过认证。";
    next += "无法解决时保留错误，worker 向 main 升级一次，main 记录阻塞。";
  }
  else if (row(status.entry).tool === "coordination__wake") {
    next = `需唤醒时调用 coordination__wake ${reference}` + (target.host === "deepseek"
      ? "（DSH 插件后台排队，无需打开窗口或粘贴发送；受理不等于已执行）。"
      : "（由对应宿主入口执行）。");
  }
  if (target.host === "deepseek" && ["deepseek_wake_setup_required", "deepseek_wake_binding_required",
    "deepseek_wake_plugin_not_running", "deepseek_wake_runtime_invalid", "deepseek_wake_unauthorized"].includes(text(status.error_code))) {
    next += "检查 DSH Desktop 初始化及原会话接入是否完成、插件是否已加载；配置与宿主启动是前置条件，不需要手动打开对话唤醒。见 docs/overview/agent-wake-guide.md。";
  }
  // 投递时机是宿主的能力，不是调用方的选择：das 返回里的 `delivery` 说清"声明了什么、这次实际
  // 用了什么"，降级时带 degraded（2026-10-10 待改 15）。远端没有本地路由和入向通道，所以那条路
  // 的正确答案是"等它自己来取"——不是重试唤醒，也不是换入口绕过（待改 13）。
  const delivery = row(row(status.delivery));
  if (Object.keys(delivery).length) {
    const used = text(delivery.used) || "unknown";
    const declared = text(delivery.declared) || "unknown";
    next += `投递时机：实际=${used}，宿主声明=${declared}（none=没有唤醒路径，unknown=读不到证据）。`
      + (delivery.degraded === true
        ? `已降级（原为 ${text(delivery.degraded_from) || "unknown"}）：${text(delivery.reason)}；`
        : "")
      + "两者都不能被读成「已经叫醒」。";
  }
  if (text(status.error_code) === "cross_machine_unsupported") {
    next = "跨机器不支持主动唤醒：对方在另一台机器上，本机既没有可核实的本地宿主路由，也没有入向通道。"
      + "消息留在本机收件箱里，需要对方自己来取（coordination__wake_status 只能报告这个事实）—— "
      + "提示它自己来读，不要重试唤醒，也不要换别的入口绕过。";
  }
  const diagnostic = (value: unknown): string => {
    const info = row(value);
    if (!Object.keys(info).length) return "";
    return `阶段=${text(info.stage)}，解释器=${text(info.interpreter)}，解释器版本=${text(info.interpreter_version)}，退出码=${String(info.exit_code ?? "unknown")}，错误类别=${text(info.error_class)}`;
  };
  const current = diagnostic(status.diagnostics);
  const prior = diagnostic(status.prior_diagnostics);
  const preflight = status.preflight_failed === true ? "本次前置检查失败，尚未执行唤醒操作。" : "";
  const details = `${preflight}${current ? `诊断：${current}。` : ""}${prior ? `上次执行诊断：${prior}。` : ""}`;
  return `协作消息 ${messageId}：${identity}；状态=${text(status.state)}，排队能力=${String(status.can_queue ?? "unknown")}，结果=${text(status.result)}，错误=${text(status.error_code)}。${facts}。${details}${next}`;
}

export async function reminderContent(
  kind: string, context: unknown, stateDir: string, statuses: unknown[] = [], projectRoot = "",
): Promise<{ type: "text"; text: string }[]> {
  const content: { type: "text"; text: string }[] = [];
  const identity = row(context);
  const validIdentity = typeof identity.agent_id === "string" && identity.agent_id.trim()
    && typeof identity.project_id === "string" && identity.project_id.trim();
  if (validIdentity) {
    const path = join(stateDir, "reminders", digest([identity.project_id, identity.agent_id]) + ".json");
    await withPrivateFileLock(path, () => {
      const saved = row(readPrivateJson(path));
      const messages = row(saved.messages);
      let changed = false;
      if (kind === "context.project_read" && saved.guide_version !== GUIDE_VERSION) {
        const working = workingRootGuidance(projectRoot);
        if (working) content.push({ type: "text", text: working });
        // 顺序有意如此：工作目录与手册（字段、拒绝码）是接下来每一轮都要用的，
        // 入口句说明"该读上下文"，唤醒指引只在真的需要唤醒时才相关。
        content.push({ type: "text", text: OPERATING_MANUAL_HINT });
        content.push({ type: "text", text: FIRST_READ_GUIDANCE });
        content.push({ type: "text", text: WAKE_REMINDER });
        saved.guide_version = GUIDE_VERSION;
        changed = true;
      }
      for (const candidate of statuses) {
        const status = row(candidate);
        if (typeof status.message_id !== "string") continue;
        const messageKey = digest(status.message_id);
        // Observation timestamps are deliberately excluded: unchanged evidence is quiet.
        const hint = compactHint(status, kind);
        const fingerprint = digest(hint);
        const explicit = kind === "coordination.wake_status" || kind === "coordination.wake";
        if (explicit || messages[messageKey] !== fingerprint) content.push({ type: "text", text: hint });
        if (messages[messageKey] !== fingerprint) { messages[messageKey] = fingerprint; changed = true; }
      }
      if (changed) writePrivateJson(path, { ...saved, messages });
    });
  }
  // 已有待确认的完成提案时不再重复那句话：它自己就写着"不要重复提交"，而用户确认之前
  // 主 Agent 在这件事上无事可做 —— 每次读上下文都重复一遍只是噪音（方案整改 7）。
  // 这个事实来自 project_read 的结果，所以桥不需要为了它多发一次调用。
  const completion = row(row(context).completion);
  const completionPending = typeof completion.pending_proposal_id === "string"
    && completion.pending_proposal_id.trim() !== "";
  if (!completionPending
      && (kind === "context.project_read" || needsCompletionContext(kind))
      && typeof identity.agent_id === "string" && identity.agent_id.trim()
      && identity.agent_id === identity.main_agent_id) {
    content.push({ type: "text", text: COMPLETION_REMINDER });
  }
  return content;
}
