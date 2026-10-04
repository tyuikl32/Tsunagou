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

GLOSSARY_VERSION = 5

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
        "ready": "待发布",
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
        "submitted": "待验收",
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
        # 跨机器：工作区在另一台机器上，主机没扫过它 —— 没有基线、交活时也没有清单（D192）
        "remote_reported": "远端自报",
        "remote_result_reported": "远端已交活",
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
        "main_agent_must_be_local": "本机才能当主",
        "main_agent_cannot_retire": "主不能删",
        "agent_has_open_work": "还有活",
        "agent_retired": "已退役",
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
        # 跨机器：远端干文件活的两道门（D191 拒绝 → D192 在"报了副本 + 外部准备 + 位置对得上"时放行）
        "remote_worker_needs_a_code_copy": "远端没报副本",
        "remote_worker_requires_external_workspace": "远端外部准备",
        "remote_workspace_locator_mismatch": "副本位置不符",
    },
    # 事件自己那句"为什么"（审计出口的 reason_code）。拒绝码有单独一张表
    # （denial_reason），这里放的是**不是拒绝**的那些：用户裁决、后台作业用尽重试、
    # 凭据迁移、克隆恢复…… 页面查这两张表时先查拒绝码、再查这张。
    "event_reason": {
        "user_decision": "用户决定",
        "job_attempts_exhausted": "重试用尽",
        "lease_expired": "租约过期",
        "legacy_credentials_revoked": "旧凭据已撤",
        "confirmed_clone_restore": "克隆恢复",
    },
    # 命令名（审计/总路径的 `action` 就是它）。总路径那一列以前直接印
    # `agent.ticket.create.user` 这种机器话，人读不动；这里一个命令一个短中文。
    # 被拒的写操作在账本里叫 `command.<命令>.denied`，页面查表前会剥掉这层壳、
    # 再补一句「（被拒）」—— 所以这里只登记命令名本身。
    "command_kind": {
        # task.*（任务的流转）
        "task.create": "建任务",
        "task.create.user": "用户建任务",
        "task.update_plan": "改计划",
        "task.ready": "标记就绪",
        "task.publish": "发布任务",
        "task.begin": "开工",
        "task.progress": "报进度",
        "task.block": "挂起",
        "task.fail": "报失败",
        "task.recover": "恢复任务",
        "task.cancel_request": "请求取消",
        "task.cancel_ack": "确认取消",
        "task.submit": "交活",
        "task.self_accept": "自验收",
        "task.review.accept": "验收通过",
        "task.review.request_changes": "要求返工",
        "task.scope.request": "申请扩围",
        "task.scope.resolve": "裁决扩围",
        "task.edge.add": "加依赖",
        "task.edge.remove": "删依赖",
        # agent.* / session.*（接入与席位）
        "agent.ticket.create": "签发接入码",
        "agent.ticket.create.user": "用户发接入码",
        "agent.enroll": "入席",
        "agent.retire": "退役",
        "agent.retire.user": "删除",
        "agent.succession": "继任",
        "session.rebind": "重绑会话",
        "session.reconnect": "重连",
        "session.reprobe": "重新探测",
        "session.end": "结束会话",
        "authority.appoint": "任命",
        "authority.revoke": "撤销任命",
        "authority.handoff": "交接",
        "authority.transition.adopt": "接手",
        "authority.transition.report": "交接报告",
        # project.*（项目本身）
        "project.initialize": "初始化",
        "project.configure": "改项目设置",
        "project.completion.propose.main": "提请完工",
        "project.completion.propose.owner": "属主提完工",
        "project.completion.confirm": "确认完工",
        "project.archive": "归档项目",
        "project.reactivate.main": "重启项目",
        "project.reactivate.user": "用户重启项目",
        "project.lineage.reset": "重置血缘",
        "project.reconcile": "对账",
        "project.trust_change": "改信任",
        "project.unregister": "注销项目",
        "project.local_copy.delete": "删本机副本",
        "project.replica.activate": "激活副本",
        "project.tasks.restore_open": "恢复未完成",
        # 目录与仓库
        "root.register": "登记目录",
        "root.bind": "绑定路径",
        "repository.register": "登记仓库",
        # 认知、分歧与契约
        "cognition.report": "认知报告",
        "discrepancy.create": "记分歧",
        "discrepancy.advance": "推进分歧",
        "discrepancy.resolve": "了结分歧",
        "contract.propose": "提议契约",
        "contract.accept": "接受契约",
        "contract.accept_proxy": "代签契约",
        "contract.reject": "拒绝契约",
        "contract.withdraw": "撤回契约",
        # 需要用户拍板的事
        "user_decision.propose": "提请决定",
        "user_decision.resolve": "用户已决定",
        "user_decision.cancel": "撤回决定",
        # 消息与收件箱
        "message.send": "发消息",
        "message.respond": "回应消息",
        "message.waive_response": "免除回应",
        "inbox.claim": "取件",
        "inbox.fetch": "读正文",
        "inbox.presented": "报已阅",
        "inbox.ack": "收讫",
        "inbox.defer": "延后取件",
        "inbox.renew": "续期",
        # 工作区、资源与存档点
        "workspace.select": "定工作区",
        "workspace.integrate": "集成请求",
        "workspace.cleanup": "清理工作区",
        "workspace.cleanup_force": "强制清理",
        "workspace.git.report": "Git 报告",
        "workspace.attach_external": "外部接管",
        "checkpoint.create": "建存档点",
        "checkpoint.create.user": "用户建存档点",
        "durability.reconcile": "存档对账",
        # 分工、风险与产物
        "coordination.plan": "下达计划",
        "coordination.takeover": "接管分工",
        "risk.request": "申请风险",
        "risk.submit": "提交风险",
        "risk.accept": "接受风险",
        "risk.revoke": "撤销风险",
        "artifact.upload.create": "建上传",
        "artifact.upload.finalize": "定稿上传",
        "artifact.promote": "提升产物",
        "artifact.promote.user": "用户提升产物",
        "ceiling.set": "设上限",
        "publication.report": "发布报告",
        "shared.reconcile": "共享对账",
        # 读操作与长流程
        "context.project_read": "读项目",
        "operation.cancel": "取消操作",
        "operation.resolve": "了结操作",
        "operation.resolve.user": "用户了结操作",
        # 不是命令，但会出现在总路径上的框架事件（后台作业、存档点落盘、重启、凭据迁移）
        "operation.created": "建操作",
        "job.queued": "作业排队",
        "job.started": "作业开始",
        "job.finished": "作业完成",
        "job.exhausted": "作业放弃",
        "job.lease_expired": "作业租约过期",
        "checkpoint.materialize": "落盘存档点",
        "checkpoint.retry_requested": "重试存档",
        "runtime.recovery": "服务重启",
        "credential.migrate": "凭据迁移",
    },
    # 引用的**前缀** → 那是个什么东西。总路径的「任务」列拿到的是 `task/<id>`、
    # `ticket/0`、`session/<id>` 这种 ref：认前缀才知道该怎么称呼它，
    # 后面的短号原样留着（人要靠它跟别的屏对上）。
    "ref_kind": {
        "task": "任务",
        "ticket": "接入码",
        "session": "会话",
        "decision": "用户决定",
        "operation": "操作",
        "job": "后台作业",
        "attempt": "执行",
        "contract": "契约",
        "message": "消息",
        "result": "结果",
        "review": "验收",
        "checkpoint": "存档点",
        "root": "目录",
        "repository": "仓库",
        "agent": "席位",
        "project": "项目",
        "discrepancy": "分歧",
        "report": "认知报告",
        "delivery": "投递",
        "obligation": "回应义务",
        "wake": "唤醒",
        "evidence": "证据",
        "artifact": "产物",
    },
    # 操作人（审计的 actor_ref）里那几个不是 Agent 的主体。Agent 自己按档案显示昵称；
    # 剩下认不出来的，页面再退回"前缀 + 短号"。
    "actor_kind": {
        "user_control": "用户",
        "runtime": "后台",
        "daemon": "协调中心",
        "console": "控制台",
        "host": "宿主",
        "device": "设备",
    },
}


def public() -> dict[str, Any]:
    """The whole table, for the page to apply to what it displays."""

    return {
        "version": GLOSSARY_VERSION,
        "domains": {domain: dict(entries) for domain, entries in GLOSSARY.items()},
    }
