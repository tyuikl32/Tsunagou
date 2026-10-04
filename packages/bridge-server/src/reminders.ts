import { createHash } from "node:crypto";
import { join } from "node:path";
import { readPrivateJson, writePrivateJson } from "./private-file.js";
import { withPrivateFileLock } from "./private-file-lock.js";

/** Presentation-only guidance. Explicit wake tools alone execute host operations. */
export const GUIDE_VERSION = "wake-v3-default-on-2026-10-04";
export const WAKE_INSTRUCTIONS = "首次 context__project_read 提供宿主协作指南；使用 coordination__peer_hosts 核对真实宿主，按消息调用 coordination__wake_status / coordination__wake。不要凭模型品牌判断宿主或重复唤醒。";
export const WAKE_REMINDER = "先调用 coordination__peer_hosts 读取并记住项目成员的真实 Agent ID、宿主类型/版本/机器与证据；模型品牌、昵称和发起方宿主不能代替目标宿主。每次执行前复核当前消息与原会话绑定。Codex → Codex 只走现有 Tsunagou Codex 通道，不追加后备命令；未配置的项目默认启用，尊重用户明确关闭。路由不代表已派发，按实际执行证据继续既有流程；其他已验证的同机宿主通过 coordination__wake_status {message_id} 检查，再显式 coordination__wake {message_id}，由认证后的固定 PowerShell 入口执行。main 和 worker 同样可在已有权限内直接唤醒协作者；未知宿主只查询，跨机器后备不支持。已处理或排队的同一请求不要重复唤醒；消息入队、宿主回合、收件人呈现、业务回复是四件事。失败先自行核对是否认错目标宿主/厂商、版本、原会话与入口，不要反复配置/探测/重绑未完整实现的自动唤醒，不要求用户手动唤醒；真实阻塞记录证据并升级 main。操作指南：优先当前安装源码 docs/overview/agent-wake-guide.md；在线 https://github.com/tyuikl32/Tsunagou/blob/HEAD/docs/overview/agent-wake-guide.md（未发布内容以本机源码为准）。";
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

function compactHint(status: Row): string {
  const target = row(status.target);
  const messageId = text(status.message_id);
  const reference = JSON.stringify({ message_id: messageId });
  const identity = `目标 ${text(target.agent_id)}，宿主 ${text(target.host)} ${text(target.version)}，位置 ${text(target.machine)}`;
  const progress = row(status.progress);
  const facts = `投递=${String(progress.durably_received ?? "unknown")}；宿主回合=${String(progress.host_turn_started ?? "unknown")}；已呈现=${String(progress.presented ?? "unknown")}；业务回复=${String(progress.business_response ?? "unknown")}`;
  let next = `先调用 coordination__wake_status ${reference} 核对状态。`;
  if (status.lane === "native") {
    const native = row(status.native);
    next = `沿用现有 Tsunagou Codex 原生通道；路由不代表已派发。开关=${String(native.enabled ?? "unknown")}，投递记录=${text(native.outbox_status)}，尝试次数=${String(native.attempt_count ?? "unknown")}，尝试状态=${text(native.attempt_state)}。`;
    next += native.enabled === false
      ? "项目已明确关闭自动唤醒，保留该设置并报告阻塞。"
      : "继续依据原生通道执行记录推进；仅在确认已有派发或处理时避免重复，不切换后备路径。";
    next += "宿主回合 unknown 表示缺少证据，不代表确定未运行。";
  }
  else if (status.lane === "unsupported" || status.result === "unsupported") next = "当前路径不支持；先核对目标宿主/原会话，记录证据并向 main 升级一次；main 自己记录阻塞，不自发消息。不要求用户手动唤醒。";
  else if (status.result === "queued" || status.result === "request_already_delivered" || status.result === "pending"
    || status.result === "same_request_running" || status.result === "already_delivered"
    || (status.state === "running" && status.request_associated === true)) next = "该请求已在处理或排队，先检查结果，不追加回合。";
  else if (row(status.entry).tool === "coordination__wake") {
    next = `需要继续时显式调用 coordination__wake ${reference}；认证后内部执行固定 PowerShell 入口，保留原权限。`;
  }
  return `协作消息 ${messageId}：${identity}；状态=${text(status.state)}，排队能力=${String(status.can_queue ?? "unknown")}，结果=${text(status.result)}，错误=${text(status.error_code)}。${facts}。${next}`;
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
        const hint = compactHint(status);
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
