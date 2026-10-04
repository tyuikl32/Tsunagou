import { createHash } from "node:crypto";
import { join } from "node:path";
import { readPrivateJson, writePrivateJson } from "./private-file.js";
import { withPrivateFileLock } from "./private-file-lock.js";

/** Presentation-only guidance. Explicit wake tools alone execute host operations. */
export const GUIDE_VERSION = "wake-v5-compact-guidance-2026-10-04";
export const WAKE_INSTRUCTIONS = "使用 coordination__peer_hosts 核对真实宿主；Codex 双方沿用原生通道，其他宿主按消息查询 coordination__wake_status。操作见 docs/overview/agent-wake-guide.md。";
export const WAKE_REMINDER = "main 和 worker 均可在已有权限内唤醒协作者。先用 coordination__peer_hosts 核实并记住宿主、版本和机器，不凭模型品牌猜测。Codex → Codex 只走现有 Tsunagou Codex 通道（默认开启，尊重明确关闭）；其他宿主先查 coordination__wake_status {message_id}，按返回入口操作。当前工具不支持不等于宿主不能唤醒；独立宿主操作须核实原会话、授权及同一消息无在途或结果未知的执行，不绕过认证。入队不等于已处理；失败核对宿主与错误，勿循环重试，不要求用户手动唤醒。操作指南：docs/overview/agent-wake-guide.md（本机安装源码优先）；https://github.com/tyuikl32/Tsunagou/blob/HEAD/docs/overview/agent-wake-guide.md。";
export const COMPLETION_REMINDER = "如果所有工作已经完成，且合并与验收已通过，请记得调用 `project__completion_propose` 发起任务完成提案，不要仅在聊天中宣布完成。已有待确认的提案时不要重复提交，最终完工由用户确认。";

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
    next = `需唤醒时调用 coordination__wake ${reference}（内部通过 PowerShell 执行）。`;
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
  kind: string, context: unknown, stateDir: string, statuses: unknown[] = [],
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
  if ((kind === "context.project_read" || needsCompletionContext(kind))
      && typeof identity.agent_id === "string" && identity.agent_id.trim()
      && identity.agent_id === identity.main_agent_id) {
    content.push({ type: "text", text: COMPLETION_REMINDER });
  }
  return content;
}
