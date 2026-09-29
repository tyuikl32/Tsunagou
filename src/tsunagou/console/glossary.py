"""The console's Chinese for the protocol's vocabulary.

The protocol speaks in short English tokens — ``open``, ``holder_released``,
``superseded`` — because machines compare them and a stable token never has to be
translated at the wire. A person reading the console wants the opposite: short,
consistent Chinese. The table lives here rather than in the page so that there is
one place to fix a word, and one place to see what the console claims a token means.

Two rules the table follows:

* **short** — 「已答复」, not 「已经得到答复」; 「等待中」, not 「正在等待中」;
* **incomplete on purpose** — a token with no entry is shown as itself, never guessed
  at. The page looks up what it displays and falls back to the raw token, so a value
  added to the protocol later appears as ``some.new.thing`` instead of silently
  becoming a wrong Chinese word.

The keys are display domains, not field names: ``message_status`` is what a person
reads in the 消息 table, whichever exit happened to answer. ``message_status`` now
has a real source — the daemon derives it in the messages exit (no response
obligation → ``none``, an ``open`` one → ``pending``, otherwise ``answered``).
``delivery_status`` is still waiting for one: the daemon keeps a delivery row for
every message (``pending``/``leased``/``acked``) but no exit sends it yet, so the
word is here only so the page never has to invent one.
"""

from __future__ import annotations

from typing import Any

GLOSSARY_VERSION = 4

#: domain -> {token: 中文}
GLOSSARY: dict[str, dict[str, str]] = {
    # 项目生命周期（Project.lifecycle）
    "lifecycle": {
        "active": "进行中",
        "completed": "已完成",
        "archived": "已归档",
    },
    # Agent 席位状态（agents 出口的 status）
    "agent_status": {
        "active": "可用",
        "provisioning": "接入中",
        "retired": "已退役",
    },
    # Agent 角色（agents 出口的 role）
    "agent_role": {
        "main": "主 Agent",
        "worker": "子 Agent",
    },
    # 会话状态（agents 出口的 session_status；agent_status 说的是"这个席位"，
    # 它说的是"现在这条会话"，降级时席位名字不变、会话已经不能干活了）
    "session_status": {
        "ready": "已就绪",
        "degraded": "降级中",
        "ended": "已结束",
    },
    # 任务状态。注意：任务表的徽章文字是 CSS（.st-N 的 ::after）生成的，
    # 这一份是协议词汇本身，供详情/别处要用文字时取。
    "task_status": {
        "draft": "草稿",
        "ready": "待发布",
        "open": "待领取",
        "claimed": "已领取",
        "running": "执行中",
        "blocked": "受阻",
        "submitted": "待评审",
        "changes_requested": "待返工",
        "cancel_requested": "待取消",
        "cancelled": "已取消",
        "failed": "失败",
        "orphaned": "已失联",
        "completed": "已完成",
    },
    # Attempt 状态（同一次执行的生命周期）
    "attempt_status": {
        "claimed": "已领取",
        "running": "执行中",
        "blocked": "受阻",
        "submitted": "已提交",
        "completed": "已完成",
        "cancelled": "已取消",
        "failed": "失败",
        "orphaned": "已失联",
    },
    # 资源租约状态（resources 出口）
    "lease_status": {
        "active": "生效中",
        "expired": "已过期",
        "released": "已释放",
    },
    # 工作区状态（workspaces 出口）
    "workspace_status": {
        "requested": "待准备",
        "preparing": "准备中",
        "ready": "就绪",
        "result_recorded": "已记录结果",
        "cleanup_pending": "待清理",
    },
    # 消息的答复状态（messages 出口的 status；后端据回应义务派生，见
    # bootstrap/container.py 的 message_status）
    "message_status": {
        "answered": "已答复",
        "pending": "等待中",
        "none": "无需答复",
        "unknown": "未知",
    },
    # 回应义务状态（ResponseObligation.status）
    "obligation_status": {
        "open": "待回应",
        "responded": "已回应",
        "waived": "已豁免",
        "superseded": "已作废",
    },
    # 投递状态（Delivery.status；daemon 有，出口还没给）
    "delivery_status": {
        "pending": "待投递",
        "leased": "投递中",
        "acked": "已确认",
    },
    # 契约提案状态（ContractProposal.status）
    "contract_status": {
        "proposed": "提议中",
        "accepted": "已接受",
        "rejected": "已拒绝",
        "withdrawn": "已撤回",
        "superseded": "已被替代",
    },
    # 用户决定状态（UserDecision.status）
    "decision_status": {
        "pending": "待决定",
        "resolved": "已决定",
        "cancelled": "已取消",
        "superseded": "已被替代",
    },
    # 认知分歧（Discrepancy.status）与严重度（severity）
    "discrepancy_status": {
        "open": "未处理",
        "clarifying": "澄清中",
        "negotiating": "协商中",
    },
    "discrepancy_severity": {
        "soft": "轻微",
        "hard": "严重",
        "critical": "致命",
    },
    # 存档点状态（checkpoints 出口）
    "checkpoint_status": {
        "sealed": "已封存",
        "verified": "已校验",
        "pending": "待落盘",
        "failed": "失败",
    },
    # 任务级验收结论（reviews 出口的 decision）
    "review_decision": {
        "accepted": "通过",
        "changes_requested": "打回",
        "rejected": "拒绝",
    },
    # 工作区隔离方式（workspaces 出口的 driver_kind）
    "isolation": {
        "shared": "共享目录",
        "worktree": "独立检出",
        "external": "外部准备",
    },
    # 资源用法（resource intent / lease 的 resources[].mode）
    "mode": {
        "read": "只读",
        "write": "可写",
    },
    # 租约冲突的结局（conflicts 出口机械推断出的 resolution）
    "conflict_resolution": {
        "retried_and_won": "重试后拿到",
        "gave_up": "放弃/失败",
        "holder_released": "占用方释放",
        "open": "仍未解决",
    },
    # 宿主的 11 项能力基线，正好就是「Agent 管理」那两栏：
    # 4 项准入（入会话前就能证，决定会话 ready/degraded）+ 7 项运营（真干过活才证）。
    # 哪几项缺，由 agents 出口的 missing_admission / missing_operational 说；
    # 这两张表只负责"共有哪些、叫什么"（顺序也跟着它）。
    "capability_admission": {
        "identity.session_isolation": "会话隔离",
        "identity.continuity_evidence": "身份续接",
        "context.project_read": "读取项目",
        "command.typed_tools": "类型化工具",
    },
    "capability_operational": {
        "task.lifecycle": "任务流转",
        "cognition.report": "认知报告",
        "contract.participation": "契约参与",
        "inbox.pull_fetch_ack": "收件确认",
        "response.structured": "结构化答复",
        "recovery.idempotent_reconnect": "断线重连",
        "delivery.deduplicate": "投递去重",
    },
    # 写操作被拒的原因码（总路径的 reason_code 就是它；带冒号时只查冒号前那截）
    "denial_reason": {
        "resource_conflict": "资源被占用",
        "lease_expired": "租约已过期",
        "capability_denied": "没有该能力",
        "ready_session_required": "会话未就绪",
        "invalid_session_or_grant": "会话已失效",
        "unknown_payload_field": "多了未知字段",
        "malformed_command_envelope": "信封不完整",
        "stale_authority_epoch": "权威代次过期",
        "stale_runtime_epoch": "运行代次过期",
        "stale_execution_epoch": "执行代次过期",
        "stale_connection_epoch": "连接代次过期",
        "authentication_failed": "身份验证失败",
        "project_not_found": "找不到项目",
        "session_not_rebindable": "会话不可重接",
        "task_not_claimable": "任务不可认领",
    },
}


def public() -> dict[str, Any]:
    """The whole table, for the page to apply to what it displays."""

    return {
        "version": GLOSSARY_VERSION,
        "domains": {domain: dict(entries) for domain, entries in GLOSSARY.items()},
    }
