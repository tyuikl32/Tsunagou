# 04 显式认知、分歧、契约与风险

## 边界

保存 Agent 主动提交的理解、假设、不确定性、结论和证据。代码只做可枚举、可测试的结构比较；不调用模型推断隐藏分歧，不解析自由文本判定两个方案是否等价。主 Agent 和参与者负责语义判断。

## 实体与索引

| 表（`cognition_`） | 字段与规则 |
|---|---|
| reports | author_agent_id,task_id,attempt_id?,boundary:pre_start\|scope_change\|contract_change\|pre_submit\|manual,understanding,assumptions[],uncertainties[],claims[],confidence:unknown\|low\|medium\|high,confidence_reason,evidence_refs,input_revisions,supersedes_id?,digest |
| discrepancies | subject_ref,source_report_refs,rule_id?,severity:info\|soft\|hard,status,participants[],summary,affected_actions,resolution_ref?,revision |
| discrepancy_resolutions | discrepancy_id,actor,kind:consensus\|dismissal\|override,reason,evidence_refs,accepted_by[],input_digest；override 不伪装 consensus |
| contracts | subject_ref,contract_kind:api_interface\|data_schema\|behavioral\|integration,current_proposal_id,revision |
| proposals | contract_id,version,payload,participants_required[],participants_optional[],input_refs[],digest,status,supersedes_id?；参与者集合属于 digest |
| acceptances | proposal_id,participant_slot_id,actor_agent_id,mode:direct\|proxy,proposal_digest,proxy_policy_ref?,reason?,evidence_refs；同 slot/proposal 唯一 |
| risk_requests | attempt_id,input_snapshot,input_digest,candidates[],requested_from_main_id,status:pending\|answered\|fallback_used\|superseded,deadline_at |
| risk_submissions | request_id,assessor_id,risk_level:low\|medium\|high\|unknown,reason,recommended_driver,scope,conditions[],evidence_refs,input_digest |
| risk_acceptances | subject_ref,actor_main_id,reason,accepted_risks[],input_digest,valid_until_task_terminal,status:active\|superseded\|revoked |

不可变报告/提案保存新版本而非 PATCH 内容。索引 `(task_id,created_at)`、discrepancy `(status,severity)`、acceptance `(proposal_id,participant_slot_id)`。认知正文默认项目共享；敏感材料通过有领域权限的 ArtifactRef，不能混入公开事件摘要。

## 确定性分歧规则

claims 是显式类型结构 `{subject_key,claim_type,equality_key,value,evidence_refs}`。首发只支持同 subject/equality_key 的枚举或字面值不一致、schema 类型/required 标记不一致、契约 digest 不一致、声明资源用途冲突，以及 Agent 显式 report_discrepancy。自由文本仅展示，不能从句子相似度阻塞任务。

rule registry 固定 rule_id/version 与严重度默认值，触发记录 input digests；同一规则+subject+输入集去重。info 仅提示，soft 建议协商，hard 按显式 affected_actions 建 blocker。主 Agent可按 policy 处置或 override，但不能 override 用户上限/会话身份/原子所有权不变量。

## 契约协议

propose 固化正文、参与者与 digest。required/optional 元素统一为 `{slot,agent_id}`，两字段均非空白，slot 在两组间唯一，Agent 必须属于当前项目；required 至少一项，同一 Agent 可以承担多个不同 slot。字符串参与者不再接受，不从 slot 猜测身份。输入引用等业务元数据可选，代码不推断其含义。

accept 和 accept_proxy 只接受 proposed 且 digest 一致的提案；accepted、withdrawn、rejected、superseded 均拒绝新接受。已接受的 slot 不允许新命令覆盖；只有同 command_id 的幂等重放返回原结果。所有 required slots 接受后才将 proposal 改为 accepted；optional 不阻塞。返回的 `status=accepted` 表示本 slot 已接受，`proposal_status=proposed|accepted` 表示整份提案状态，两者不能混用。

proxy 是独立 `contract.accept_proxy` 命令，要求 main 的 `contract.accept_proxy` 权限；服务从 slot 解析被代表的实际 Agent，保存 `real_actor_id`、`represented_participant=agent_id` 与 `via_proxy=true`。理由、policy 引用和证据可附带，不增加用户逐项审批。不能把 slot 名写作被代理身份或伪造直接接受。参与者替换、内容修改、前提失效必须新 proposal，旧接受不能迁移。

reject 只允许参与者终结 proposed；withdraw 只允许原提议者终结 proposed。原提议者可通过 `contract.propose` 的 `supersedes_id` 替代 proposed/accepted 提案；先验证并创建替代提案，再在同一 UoW 中把旧提案设为 superseded，失败时两者都不变。其他终态不可替代。任务只引用精确 proposal；具体门禁简化按 FX2 实施。

## 风险建议与内核判断

风险请求记录 scope、资源、root/repo 状态、能力快照、可用 drivers 的 input digest，发给 current main。默认 120 秒评估窗口是已确认的机械 fallback 例外，不影响用户等待。fallback 只从满足明确 hard constraints 的候选中按已配置确定性顺序选；没有合格候选就 blocked，不把未知解释为低风险。

风险建议由 cognition 保存；最终 IsolationDecision 由 workspaces 校验授权、driver能力、资源约束后保存。main 的 risk acceptance 在任务终态前有效，不设累计次数/时长上限，但输入 digest 变化即失效；不能扩大 ceiling、让旧 epoch 有效或替代 user-only 决定。

## 端口、事件、验收

`get_preflight_evidence(task,attempt,revisions)` 返回报告/契约/风险摘要；`get_contract_participation` 校验 slot；`replace_participant_obligations` 只新建提案，不能改旧接受。事件 report_submitted、discrepancy_opened/resolved、contract_proposed/accepted/superseded、risk_assessment_submitted。

测试：相同输入不重复分歧；自然语言不同但无显式规则不自动 hard block；旧 hash 接受失败；代理保留真实 actor；继任重新接受；risk 输入变更失效；参与者/主 Agent处理业务分歧而非用户被迫选每个参数。实施 T10/T13/T15。
