/** Presentation-only guidance. These rules never execute coordination actions. */
export const WAKE_REMINDER = "需要唤醒其他 Agent 时，请通过 PowerShell 执行对应宿主的唤醒操作；发起方和接收方都为 Codex 时，沿用 Codex 已有的唤醒机制。请确认是否确实需要唤醒，避免重复操作。请优先使用已验证的宿主原会话入口，不要把尚未完整实现或未经当前宿主验证的 Tsunagou 自动唤醒当作前提，也不要反复配置、探测或重绑来等待它生效。各宿主操作指南：优先读取当前安装源码中的 docs/overview/agent-wake-guide.md；在线入口 https://github.com/tyuikl32/Tsunagou/blob/HEAD/docs/overview/agent-wake-guide.md（未发布的本地更新以安装源码为准）。消息已入队不等于对方已开始新回合。唤醒失败时先自行排查是否认错目标厂商或宿主、原会话及操作入口，依据真实注册信息纠正后再试；不要请用户手动唤醒。仍受真实能力或权限阻塞时，向 main 记录证据和未解决状态，不要宣称成功或扩大权限。";
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
