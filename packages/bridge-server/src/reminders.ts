/** Presentation-only guidance. These rules never execute coordination actions. */
export const WAKE_REMINDER = "需要唤醒其他 Agent 时，请通过 PowerShell 执行对应宿主的唤醒操作；发起方和接收方都为 Codex 时，沿用 Codex 已有的唤醒机制。请确认是否确实需要唤醒，避免重复操作。";
export const COMPLETION_REMINDER = "如果所有工作已经完成，且合并与验收已通过，请记得调用 `project__completion_propose` 发起任务完成提案，不要仅在聊天中宣布完成。已有待确认的提案时不要重复提交，最终完工由用户确认。";

const wakeCommands = new Set([
  "context.project_read", "coordination.plan", "coordination.takeover", "task.publish",
  "task.submit", "task.review.accept", "task.review.request_changes", "task.self_accept",
  "message.send", "message.respond",
]);

export function needsCompletionContext(kind: string): boolean {
  return kind === "task.review.accept" || kind === "task.self_accept";
}

export function reminderContent(kind: string, context: unknown): { type: "text"; text: string }[] {
  const content: { type: "text"; text: string }[] = [];
  if (wakeCommands.has(kind)) content.push({ type: "text", text: WAKE_REMINDER });
  if (kind === "context.project_read" || needsCompletionContext(kind)) {
    const identity = context as { agent_id?: unknown; main_agent_id?: unknown } | null;
    if (typeof identity?.agent_id === "string" && identity.agent_id.trim()
        && identity.agent_id === identity.main_agent_id) {
      content.push({ type: "text", text: COMPLETION_REMINDER });
    }
  }
  return content;
}
