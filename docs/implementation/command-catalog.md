# 首发命令、查询与 CLI 目录

本文件定义唯一公开动作名。T03 将目录逐项落实为 TypedCommand/CommandPolicy/JSON Schema；T16 输出 HTTP/MCP conformance。不得把斜杠组合动作做成含糊 handler。所有 mutation 使用[协议 envelope](protocol.md)，表中只列业务 payload；路由 ID 不重复放 payload。`?` 可省略，其余必填；具体对象类型见模块实体表，所有自由摘要 UTF-8 ≤4 KiB。

`P=/api/v1/projects/{project_id}`；所有 mutation 默认 POST。已存在目标必须 expected_revision；多对象事务额外传 expected_revisions；main 带 authority epoch，Attempt执行带 attempt/execution epoch。query不用command_id。

## 权限记号

| 记号 | principal / 唯一 Grant | 额外谓词 |
|---|---|---|
| U | user_control / 无 | 固定用户入口；MCP不发布 |
| B | agent_session / agent_base | ready、project membership，行中指定self/owner/recipient关系 |
| M | agent_session / main_authority | current main、authority epoch、可委派scope |
| X | agent_session / task_attempt | current owner/attempt/execution epoch、scope、允许状态 |
| R | agent_session / task_review | 指定reviewer slot、result和round |
| H | agent_session / handoff_transition | 冻结对象allowlist，仅安全收敛 |
| D | bootstrap authenticated session / 无普通Grant | 仅自己诊断、reprobe、detach；static allowlist |
| T | enrollment/rebind ticket | 种类、有效期、nonce、宿主限制、单次消费 |

U 命令 capability 为 `—`。D/T 属认证bootstrap端点，不通过一般业务Grant开后门。表中输出为 DTO，字段见模块计划；输出含Operation表示202，其余按创建/更新201/200。

## 项目、授权与用户决定

| command kind | URI（P后缀） | 权限 / capability | payload | result 与额外约束 |
|---|---|---|---|---|
| project.initialize | `/api/v1/projects`（全路径） | U / — | name,objective,coordination_root,initial_policy | Project+Operation；已有Git仓库，创建genesis |
| project.configure | `:configure` | M / project.configure | policy_patch,reason | ProjectPolicy；不能扩大用户ceiling |
| root.register | `/roots` | M / root.manage | name,kind,repository_id?,required,binding_request,reason | RootRegistration；超边界先用户决定 |
| root.bind | `/roots/{id}:bind` | M / root.manage | root_id,absolute_path,expected_physical_identity?,reason | RootBinding+Operation；物理验证 |
| repository.register | `/repositories` | M / root.manage | name,root_id,required | RepositoryRegistration+Operation |
| project.reconcile | `:reconcile` | M / project.reconcile | scope_refs,reason | Operation；只读观察、合并计划另确认 |
| ceiling.set | `/control/ceiling:set` | U / — | ceiling,reason | UserCeiling；撤销不再满足范围的Grant |
| project.trust_change | `/control/trust:change` | U / — | change_kind,proposal_ref,proposal_digest,expected_revisions,reason | UserDecision+Operation；协调根/信任边界/高敏root |
| user_decision.propose | `/decisions` | M / decision.propose | kind,proposal_ref,proposal_digest?,expected_revisions?,choices,summary | UserDecision pending，无deadline；省略 proposal_digest 时由 daemon 根据提案内容计算，省略 expected_revisions 时按初始版本 1。`kind` 是自由字符串，其中 `project.objective` 为**保留值**：`summary` 写主 Agent 与用户谈定的项目目标、`choices` 给可选项，用户确认后它才是项目目标（见[决策](../decisions/2026-10-01-objective-from-dialogue.md)） |
| user_decision.resolve | `/control/decisions/{id}:resolve` | U / — | decision_id,choice,proposal_digest,expected_revisions,reason? | UserDecision；审批与相应领域变更同UoW或生成Operation |
| user_decision.cancel | `/decisions/{id}:cancel` | M / decision.propose | reason | UserDecision；仅尚pending，不等于用户拒绝 |
| project.completion.propose.main | `/completion-proposals` | M / project.configure | objective_ref,evidence_refs,outstanding_summary,expected_project_revision | CompletionProposal |
| project.completion.propose.owner | `/completion-proposals:from-owner` | X / task.execute | objective_ref,evidence_refs,outstanding_summary,expected_project_revision | CompletionProposal；必须root/objective owner |
| project.completion.confirm | `/control/completion-proposals/{id}:confirm` | U / — | proposal_digest,expected_project_revision,expected_revisions | Project completed+checkpoint Operation；current Attempts先收敛 |
| project.archive | `:archive` | M / project.archive | reason,expected_checkpoint_digest | Operation；barrier完成再archived |
| project.reactivate.main | `:reactivate` | M / project.configure | reason,expected_runtime_epoch | Project+Operation；policy预授权，无ceiling扩大 |
| project.reactivate.user | `/control:reactivate` | U / — | reason,expected_runtime_epoch | Project+Operation；新runtime，旧执行权不恢复 |
| project.tasks.restore_open | `/tasks:restore-open` | M / task.coordinate | task_ids,expected_revisions,plan_digest,reason | Task[]；全批次原子，无completed |
| project.replica.activate | `/control/replicas/{id}:activate` | U / — | mode:normal\|takeover,checkpoint_digest,recovery_evidence_refs,reason | Operation；恢复门槛与单writer |
| project.lineage.reset | `/control/lineage:reset` | U / — | target:checkpoint\|empty,checkpoint_digest?,reason | Operation；旧sealed，新unassigned |
| project.unregister | `/control:unregister` | U / — | expected_runtime_epoch,reason | RegistrationResult；不等同删除文件 |
| project.local_copy.delete | `/control:delete-local-copy` | U / — | exact_paths_digest,recovery_evidence_refs,data_loss_acceptance?,reason | Operation；最后副本专门审批 |

普通管理动作需要用户直接操作时，首发只提供以下独立user命令：`project.configure.user`、`root.register.user`、`root.bind.user`、`repository.register.user`、`project.reconcile.user`、`project.archive.user`、`project.tasks.restore_open.user`、`user_decision.propose.user`。URI为相应URI的P后插入`/control`（项目冒号动作如`P/control:configure`）；payload/result不变，principal固定U、无capability、仍验证结构/revision/范围。不得把User token映射为虚假main Grant。T03逐项注册而非运行时通配生成授权。

## Agent、会话与 Authority

| command | URI后缀 | 权限 / capability | payload | result/谓词 |
|---|---|---|---|---|
| agent.ticket.create | `/enrollment-tickets` | M / agent.enroll | kind:worker\|session_rebind,adapter_allowlist,ceiling_template,installation_binding?,target_agent_id? | TicketReceipt；secret仅私有交付 |
| agent.ticket.create.user | `/control/enrollment-tickets`（实际统一入口 `/api/v1/commands/agent.ticket.create.user`） | U / — | installation_id,conversation_evidence:{conversation_id},kind:worker\|main\|session_rebind?,role:worker\|main?,ttl_seconds?,host_binding? | `role` 为用户请求，默认 worker；host_binding 的 provider/endpoint/thread_id/host_generation 绑定原会话，thread_id 必须等于票据 conversation_id。enroll/rebind 提交后自动登记唤醒 provider，不允许 Worker 指定其他 Agent |
| agent.enroll | `/sessions:enroll` | T / — | installation_id,conversation_evidence,descriptor_ref,probe_payload,client_nonce,negotiation | EnrollmentResult；secret走专用header/安全通道。`descriptor_ref` 今天只用来带**跨机器远端自报**的东西：机器名（裸字符串或对象里的 `machine`），以及它那份代码副本的位置与基线（`{"copy":{"path","baseline"}}`；`agent import --machine/--copy/--baseline` 写进本机身份文件，桥在入席时上送）。两者都只是**自报**：不参与角色/范围/准入判断，乱填当没报；副本位置让主机把工作区按"外部准备"指向它（主机不读该路径，无基线、无清单，见 D192） |
| session.rebind | `/sessions:rebind` | T / — | target_agent_id,installation_id,conversation_evidence,probe_payload,client_nonce | replacement HostSession；旧token和Grant撤销 |
| session.reconnect | `/sessions/{id}:reconnect` | D / — | expected_connection_epoch,reconnect_nonce,continuity_evidence,probe_payload,host_binding_refresh? | ConnectionResult；token认证+nonce CAS；私有宿主刷新仅作用于当前已绑定Agent |
| session.reprobe | `/sessions/{id}:reprobe` | D / — | probe_payload,descriptor_ref,reason | CapabilitySnapshot；仅self |
| session.end | `/sessions/{id}:end` | D / — | reason,stop_evidence? | HostSession；self，撤Grant/处理Attempts |
| authority.appoint | `/control/authority:appoint` | U / — | agent_id,expected_authority_epoch,ceiling_template,reason | Authority；ready且baseline通过 |
| authority.revoke | `/control/authority:revoke` | U / — | expected_authority_epoch,reason | Authority unassigned，撤权 |
| context.project_read | `/context:project-read` | B / coordination.read | — | 脱敏项目上下文；仅当前会话与授权可见 |
| authority.handoff | `/authority:handoff` | M / authority.handoff | target_agent_id,expected_authority_epoch,adoption_plan,reason | AuthorityTransition |
| authority.transition.report | `/authority-transitions/{id}:report` | H / authority.converge | stopped_refs,evidence_refs | Transition；只允许收敛对象 |
| authority.transition.adopt | `/authority-transitions/{id}:adopt` | H / authority.converge | adopted_refs,expected_revisions,reason | Transition；target且scope可覆盖 |
| agent.succession | `/agents/{id}:succeed` | M / agent.coordinate | successor_agent_id,attempt_plan,obligation_plan,expected_revisions,residual_risk_refs,reason | SuccessionResult+Operations；不改owner |
| agent.retire | `/agents/{id}:retire` | M / agent.coordinate | expected_revisions,reason,stop_evidence? | Agent；若仍有执行先安全收敛 |
| agent.retire.user | `/control/agents/{id}:retire` | U | agent_id,reason? | Agent；只有用户能删。退役=他不能再动、历史一字不改；当前主 Agent 与手上还有活的都拒绝 |

## 任务、Attempt 与验收

| command | URI后缀 | 权限 / capability | payload | result/谓词 |
|---|---|---|---|---|
| task.create | `/tasks` | M / task.create | title,objective,execution_scope,parent_task_id?,required_contract_ids?,blocks? | Task draft；execution_scope 必填但可为 `{}`（空=不额外限制：不声明 path，begin 不准备 workspace、不产生占用）；parent非终态或明确follow-up |
| task.create.user | `/control/tasks` | U / — | 同task.create | Task；不自动任命自己owner |
| task.update_plan | `/tasks/{id}:update-plan` | M / task.coordinate | title?,objective?,required_contract_ids?,reason? | Task；仅无执行的可编辑态 |
| task.ready | `/tasks/{id}:ready` | M / task.publish | reason? | Task ready；完整结构检查 |
| task.publish | `/tasks/{id}:publish` | M / task.publish | reason? | Task open；ready或changes_requested关闭旧Attempt后 |
| task.edge.add | `/task-edges` | M / task.coordinate | source_task_id,target_task_id,kind,expected_revisions | TaskEdge；blocks无环 |
| task.edge.remove | `/task-edges/{id}:remove` | M / task.coordinate | reason,expected_revisions | EdgeRemoved；留事件 |
| task.begin | `/tasks/{id}:begin` | B / task.claim | expected_task_revision | 一次取得 owner、基线、资源占用和执行授权；同 owner running 可恢复；失败不保留半套准备 |
| task.progress | `/tasks/{id}:progress` | X / task.execute | summary,evidence_refs | ProgressRecord；running |
| task.block | `/tasks/{id}:block` | B / task.coordinate_self | attempt_id,reason_code,dependency_refs,checkpoint_summary,evidence_refs | Suspension；current owner claimed/running |
| task.submit | `/tasks/{id}:submit` | B / task.execute | attempt_id,summary,evidence_refs?,artifact_refs?,validation_metadata? | 自动收集 WorkspaceResult，提交后显式释放资源/撤执行权；submitted 等待 main 审查 |
| task.review.accept | `/reviews/{id}:accept` | R / task.review | slot_id,result_digest,evidence_refs,reason | ReviewDecision；指定round/slot |
| task.review.request_changes | `/reviews/{id}:request-changes` | R / task.review | slot_id,result_digest,evidence_refs,reason | ReviewDecision+Task changes_requested |
| task.self_accept | `/reviews/{id}:self-accept` | B / task.coordinate_self | result_digest,evidence_refs,reason | ReviewDecision；原owner、policy low-risk self |
| task.cancel_request | `/tasks/{id}:request-cancel` | M / task.coordinate | reason | current Attempt claimed/running 时 cancel_requested；否则直接 cancelled，保留 submitted 结果 |
| task.cancel_ack | `/tasks/{id}:ack-cancel` | B / task.coordinate_self | attempt_id,stop_evidence,reason | Task cancelled；owner，仅收敛 |
| task.fail | `/tasks/{id}:fail` | B / task.coordinate_self | attempt_id,reason,evidence_refs,stop_evidence? | Task failed；owner，无成功伪装 |
| task.recover | `/tasks/{id}:recover` | M / task.coordinate | task_id,expected_attempt_id,disposition:reopen\|cancel\|fail,reason? | Task；关闭旧Attempt再reopen |
| task.scope.request | `/tasks/{id}/scope-requests` | B / task.coordinate_self | attempt_id,requested_scope,reason,expected_revisions | ScopeExpansionRequest；owner |
| task.scope.resolve | `/scope-requests/{id}:resolve` | M / task.coordinate | scope_request_id,choice:approve\|reject,approved_scope?,reason? | ScopeRequest+Task；审批不超ceiling，执行先block |

## Main 协调计划与 Worker 唤醒

| command kind | URI后缀 | 权限 / capability | payload | result/谓词 |
|---|---|---|---|---|
| coordination.plan | `/coordination/plans` | M / coordination.write | objective,assignments,auto_wake? | 原子创建 Task、Assignment、持久通知；依赖读取 Task，唤醒读取 hostwake；不设模型 ready 回执 |
| coordination.takeover | `/coordination/assignments/{id}:takeover` | M / coordination.write | assignment_id,takeover_reason | 显式 Main 接管；记录原 worker、失败状态证据和原因后才能 claim |

## 认知与契约

| command | URI后缀 | 权限 / capability | payload | result/谓词 |
|---|---|---|---|---|
| cognition.report | `/reports` | B / cognition.report | task_id,attempt_id?,boundary,understanding,assumptions,uncertainties,claims,confidence,confidence_reason,evidence_refs,input_revisions,supersedes_id? | EpistemicReport；owner/指定参与者 |
| discrepancy.create | `/discrepancies` | B / cognition.discuss | subject_ref,report_refs,severity,participants,summary,affected_actions | Discrepancy；有subject参与关系 |
| discrepancy.advance | `/discrepancies/{id}:advance` | B / cognition.discuss | discrepancy_id,status:clarifying\|negotiating,reason?,evidence_refs? | Discrepancy；participant |
| discrepancy.resolve | `/discrepancies/{id}:resolve` | M / cognition.resolve | discrepancy_id,kind:consensus\|dismissal\|override,reason?,evidence_refs?,accepted_by?,input_digest? | Resolution；override不冒充共识 |
| contract.propose | `/contracts:propose` | B / contract.propose | contract_id?,subject_ref?,contract_kind?,payload,participants_required,participants_optional?,input_refs?,supersedes_id? | 两组元素为 {slot,agent_id}；required 至少一项、slot 全局唯一、Agent 属于本项目；替代只允许原提议者 |
| contract.accept | `/contract-proposals/{id}:accept` | B / contract.accept | participant_slot,proposal_digest,evidence_refs? | self slot；仅 proposed；status 表示本 slot 接受，proposal_status 表示整个契约 |
| contract.accept_proxy | `/contract-proposals/{id}:accept-proxy` | M / contract.accept_proxy | participant_slot_id,proposal_digest,proxy_policy_ref?,reason?,evidence_refs? | 仅 proposed；返回 proposal_status、real_actor_id 与 represented_participant（实际 Agent ID） |
| contract.reject | `/contract-proposals/{id}:reject` | B / contract.accept | proposal_digest,reason,evidence_refs | Proposal rejected；participant |
| contract.withdraw | `/contract-proposals/{id}:withdraw` | B / contract.propose | reason | Proposal；原提议者，尚未accepted |
| risk.request | `/risk-assessments` | B / cognition.report | attempt_id,input_snapshot,input_digest,candidates | RiskRequest；owner；默认120秒fallback窗口 |
| risk.submit | `/risk-assessments/{id}:submit` | M / risk.assess | input_digest,risk_level,reason,recommended_driver,scope,conditions,evidence_refs | RiskSubmission；输入仍当前 |
| risk.accept | `/risk-acceptances` | M / risk.accept | subject_ref,input_digest,accepted_risks,reason | RiskAcceptance；不绕用户/结构不变量 |
| risk.revoke | `/risk-acceptances/{id}:revoke` | M / risk.accept | reason | RiskAcceptance revoked |

## 资源与工作空间

| command | URI后缀 | 权限 / capability | payload | result/谓词 |
|---|---|---|---|---|
| workspace.select | `/workspace-decisions` | M / workspace.select | task_id,driver_kind,root_binding_refs?,repository_id?,external_locator?,hard_constraints?,evidence_refs?,reason? | Task policy; scope revision bound; main prepares Git paths before begin |
| workspace.attach_external | `/workspaces:attach-external` | M / workspace.manage | attempt_id,decision_id,root_binding_refs,external_locator,evidence_refs | Workspace+Operation；不创建容器 |
| workspace.git.report | `/git-requests/{id}:report` | M / git.control | exact_input_digest,outcome,evidence_refs,result_manifest | GitActionReport+Operation；main实际执行 |
| workspace.integrate | `/integrations` | M / git.control | source_result_ref,target_repository_id,target_baseline_digest,plan_digest,reason | Integration+Operation；main执行 |
| workspace.cleanup | `/workspaces/{id}:cleanup` | M / workspace.manage | input_digest,required_checkpoint_ref,reason | Operation；terminal+干净，Git仍main执行 |
| workspace.cleanup_force | `/control/workspaces/{id}:cleanup-force` | U / — | input_digest,required_checkpoint_ref,exact_paths_digest,data_loss_acceptance,reason | UserDecision+Operation；dirty/最后副本要求 |

## 消息、附件与持久操作

| command | URI后缀 | 权限 / capability | payload | result/谓词 |
|---|---|---|---|---|
| message.send | `/api/v1/commands/message.send` | B / message.send | recipient_agent_id,summary,kind?,subject_ref?,payload?,priority?,response_contract?,in_reply_to? | message_id+recipient_agent_id；发送者取认证身份；summary 非空且最多4096字符，payload最多256KiB |
| message.respond | `/api/v1/commands/message.respond` | B / message.respond | obligation_id,response_message_id | 已存在的关联回复满足 Obligation；仅原recipient |
| message.waive_response | `/response-obligations/{id}:waive` | B / message.send | reason | Obligation；原sender；main只能以原sender身份 |
| inbox.claim | `/api/v1/commands/inbox.claim` | B / inbox.consume | limit? | messages 摘要列表+count；authenticated self；limit为1–200，默认50；不返回payload正文 |
| inbox.fetch | `/api/v1/commands/inbox.fetch` | B / inbox.consume | message_id | 完整Message视图含payload/in_reply_to/响应义务；仅原recipient |
| inbox.renew | `/deliveries/{id}:renew` | B / inbox.consume | delivery_lease_id | DeliveryLease；不超过2分钟 |
| inbox.presented | `/api/v1/commands/inbox.presented` | B / inbox.consume | message_id,evidence_kind?,evidence_digest? | message_id+presented；仅记录展示声明，当前不验证摘要格式或证据强度 |
| inbox.ack | `/api/v1/commands/inbox.ack` | B / inbox.consume | message_id,reason? | message_id+acked；仅原recipient；不自动响应 |
| inbox.defer | `/deliveries/{id}:defer` | B / inbox.consume | defer_until,reason | Delivery；只改投递调度 |
| artifact.upload.create | `/artifact-uploads` | B / artifact.attach | domain_ref,visibility:project_shared\|recipient_only,size_bytes,media_type,expected_digest | UploadIntent；领域允许该actor附加 |
| artifact.upload.finalize | `/artifact-uploads/{id}:finalize` | B / artifact.attach | digest,size_bytes | ArtifactRef；相同领域授权重验 |
| artifact.promote | `/artifacts/{digest}:promote` | M / artifact.promote | domain_ref,reason | ArtifactRef+Operation；project_shared，禁止hash绕授权 |
| artifact.promote.user | `/control/artifacts/{digest}:promote` | U / — | domain_ref,reason | 同上 |
| checkpoint.create | `/checkpoints` | M / durability.checkpoint | reason?,minimum_event_seq? | Operation；事务保存固定快照，提交后物化 |
| checkpoint.create.user | `/control/checkpoints` | U / — | reason?,minimum_event_seq?,retry_operation_id? | Operation；retry复用原里程碑快照 |
| operation.cancel | `/operations/{id}:cancel` | M / operation.coordinate | reason | Operation；能否中止取决于handler，不伪造撤回外部效果 |
| operation.resolve | `/operations/{id}:resolve` | M / operation.coordinate | conclusion,evidence_refs,reason,followup_plan? | OperationResolution；原unknown保留，只能可授权范围 |
| operation.resolve.user | `/control/operations/{id}:resolve` | U / — | 同上 | User保留动作与越权风险专用 |
| durability.reconcile | `/durability:reconcile` | M / durability.checkpoint | scope_refs,reason | Operation；重试物化，非盲重外部动作 |
| publication.report | `/publication-reports` | M / git.control | repository_id,remote_name,ref_name,commit_oid,checkpoint_digest,evidence_refs,reported_at | PublicationReport；main_reported |
| shared.reconcile | `/shared-state:reconcile` | M / project.reconcile | ancestor_digest,left_digest,right_digest,resolution_plan,expected_revisions,plan_digest | Operation；同lineage且冲突已明确解决 |

上述六个已实现消息命令列出实际完整 HTTP 路径，业务 ID 放 payload；不沿用旧 recipient_ids、response_payload、delivery_lease_id 或未实现的 max_bytes。`kind` 是开放字符串，默认 `message`；`response_contract={required?:boolean,schema?:object}`，required 默认 true，schema 为回复 payload 的 JSON Schema。发送回复先调用 message.send，使用原发送者作为 recipient_agent_id，并设置 in_reply_to；返回的 message_id 再交给 message.respond 关闭义务。发送、展示、ACK 和业务响应是不同事实；当前 ACK 不以前置 presented 为机械门禁。MCP message.send 的可选 command_id 属于 envelope 幂等键，bridge 从工具参数移入 envelope，不是业务 payload。

附件二进制单独 `PUT P/artifact-uploads/{id}/content`，body为bytes，session凭据+upload ownership认证，不接受任意文件路径；字节重传幂等以expected_digest/length判断。它不直接创建领域事实，finalize才提交引用。

实验管理独立U入口：`experiment.create` → `P/control/experiments`（definition），`experiment.run` → `.../{id}:run`（arm,replicate,config_digest），`experiment.report` → `.../{id}:report`（method_version）；都返回Operation或受控record。内部runner写样本无公共Agent入口。

## 查询目录

| GET URI | DTO / 权限 |
|---|---|
| `/api/v1/projects` | ProjectRegistrationPage / U；Agent只能已绑定project |
| `P`、`P/conditions`、`P/blockers` | ProjectView/ConditionPage/BlockerPage / B、U，敏感字段裁剪 |
| `P/blackboard` | BlackboardSnapshot / B、U；统一read transaction，见runtime-prompts |
| `P/{roots,repositories,agents,tasks,attempts,results,jobs,reports,discrepancies,contracts,workspaces,operations,checkpoints}` | 对应分页；每种都注册独立route，不在生产解析花括号 |
| `P/<上述集合>/{id}` | 对应DTO、ETag；必须同project可见 |
| `P/tasks/{id}/{attempts,results,reviews,preflight}` | Task子资源及当前有效preflight；无秘密 |
| `P/authority`、`P/capabilities`、`P/protocol` | AuthorityView、服务端registry、版本/schema bundles |
| `P/sessions/{id}/diagnostics` | SessionDiagnostics / self D或U；诊断不能顺带读项目正文 |
| `P/inbox`、`P/messages/{id}`、`P/response-obligations` | self recipient；sender可读自己发送记录，其他人包括main不能读 |
| `P/artifacts/{digest}?domain_kind=...&domain_id=...` | 经领域引用授权的bytes；hash不是凭据 |
| `P/events`、`P/events:stream` | EventPage或SSE提示；按可见性过滤 |
| `P/decisions`、`P/decisions/{id}` | 待决摘要/详情 / current main、U；关联参与者只见自身阻塞摘要 |
| `P/audit` | AuditPage / U、B；actor/subject/time 筛选和签名游标；私信关联行仅发送者/收件人，main/U 不绕过 |
| `P/{id}/history` | `GET /api/v1/projects/{id}/history`；与 `P/audit` 同一 AuditPage 投影，默认50、最大200 |
| `P/tasks/{task_id}/history` | `GET /api/v1/projects/{id}/tasks/{task_id}/history`；包含任务及其 Attempt/Result/Workspace/认知和可见消息关联事件 |
| `P/audit/events/{event_id}` | `GET /api/v1/audit/events/{event_id}`；单事件因果、证据和变更详情，仍执行项目与私信权限 |
| `P/{id}/history/export` | `GET /api/v1/projects/{id}/history/export`；脱敏 `tsunagou.audit-export.v1`，带 `source`、`lineage_id`、`exported_at` |
| `P/{id}/checkpoints` | `GET /api/v1/projects/{id}/checkpoints?verify=true`；共享 checkpoint 清单/current 指针和可选文件校验 |
| `P/checkpoints/{digest}/verify` | `GET /api/v1/checkpoints/{digest}/verify`；验证 manifest、文件摘要和本地 heads/tags Git anchor |
| `P/{id}/diagnostics` | `GET /api/v1/projects/{id}/diagnostics`；U/B 可见的 callback、wake、presentation、turn 诊断证据，不改变 domain revision |
| `P/metrics`、`P/experiments` | 脱敏MetricPage/ExperimentPage；敏感实验原始证据U |
| `/api/v1/config`、`/api/v1/doctor` | 脱敏设置来源、诊断 / U；不触发repair |

凭据交付的 transport 入口为 `POST /api/v1/credential-deliveries/{delivery_ref}/ack`，认证后消费私有 delivery；它不创造新的业务权限，不作为普通 MCP 工具。状态、时间和重试规则见 [凭据交付](credential-delivery.md)。

## CLI 映射与退出码

OpenCode 本机原对话入口：`agent prepare --adapter opencode` 一次性安装用户级无凭据工具与共享 MCP，不创建身份；`agent join --adapter opencode` 由宿主工具调用，使用真实会话身份认领匹配控制台申请并复用现有 U 签票流程。`agent join` 默认 Codex 不变。无参数宿主工具 `tsunagou_connect` 不是 daemon 领域命令，不新增权限或业务 Schema；原会话的 MCP context 回执才确认到达，helper 不产生回执。

FX4 已实现 `agent prepare --adapter codex --role worker|main`（只准备私有真实宿主请求）、`agent connect --request-file PATH`（用户授权接入及角色选择）、`agent list [--json]`（只读）。connect 输出 enrolled，原会话 MCP context 验证后才 ready；profile 不决定 Agent 身份。全局 `--project-root` 和子目录发现共享同一 runtime resolver。

DeepSeek 项目选择修复：`agent pending --adapter deepseek` 投影申请 ID/项目/角色，宿主适配器通过 `--project-root` 和隐藏的 `agent connect --pending-enrollment-id` 固定选择。connect 的项目优先级为显式路径/绑定环境、该宿主申请、cwd；显式选择与申请冲突则拒绝，已有会话跨项目也拒绝。无申请保留手动接入；不改变领域 payload、权限或控制台 arrived 状态机。

`daemon start --reuse ROOT` 使用已有 daemon 原启动项目 U 控制凭据调用 `POST /api/v1/daemon/projects`，请求 `{project_root,state_dir}`。此本机注册入口不是 Agent 业务命令，不增加 M/B 权限。每项目独立 SQLite/凭据；HTTP 由 URL project_id 或 `Tsunagou-Project-Id` 路由，冲突拒绝，多项目无选择拒绝。stop 停止全部成员，输出 project_ids；保留私有注册位置用于从任一成员重启。上述为已实现入口；下文宽泛命令树仍含设计目标，应以 CLI help 为准。

PT2 加入 `daemon migrate-credentials --coordination-root <path> [--dry-run] [--confirm-plan-digest <digest>]` 本机离线修复入口：默认只预览，显式计划确认后撤销旧权限并清理秘密；拒绝活跃 daemon writer，未完成迁移阻止启动，完成后重新接入。不是 Agent 领域写命令，不增加 `*.user` 冒充权限。

可落地的用户命令树：`daemon start|stop|status`；`project init|bootstrap|list|show|history|diagnostics|archive|reactivate|unregister|reset-lineage`；`root register|bind|list`；`agent enroll|list|show`；`authority appoint|revoke|show`；`task history`；`decision list|show|resolve`；`audit event`；`checkpoint create|retry|list|verify`；`operation list|show|resolve`；`config show|validate`；`doctor`；`experiment run|report`。安装器的 `--project-root` 是显式选择后的安装联动参数，不是新的领域命令。

离线 Git clone 的确认恢复是 CLI 本地维护动作：`project restore --coordination-root <clone> --checkpoint-digest <digest>` 只预览；用户检查预览后补 `--confirm-plan-digest <plan_digest>` 才写入全新的本地 SQLite。它不调用 daemon、不为 Agent 授权，也不能覆盖已有本地状态；不纳入 MCP/U command registry。

旧概览曾列出`agent reprobe/retire`、`authority handoff`、`task publish/recover`、`operation cancel`，但对应目录只有D/M主体handler，尚无U授权。首发用户CLI不注册这些未绑定动作；相同领域行为仍由自身bridge/current main工具完成。不得为补齐help表而让CLI读取Agent token或自行增加user权限。参数、组合接入和映射见[CLI契约](cli-contract.md)。

`project confirm-completion <proposal_id> --request-file <json> --expected-revision <n>`只映射已注册的U-only `project.completion.confirm`。`proposal_id`进入URI，`--expected-revision`成为CompletionProposal的If-Match；请求文件必须提供同一版本的`proposal_digest`、`expected_project_revision`和`expected_revisions`。CLI不补“最新”值，也不从决定解决、归档或其他动作自动确认项目完成。

CLI是user_control入口，必要的Agent执行命令由typed tools完成，不能通过CLI伪造owner。未列出的管理高级命令可通过公共HTTP调用，不承诺为每个底层动作做交互向导。CLI `--json`输出同一DTO/Problem；无secret，quiet/stdout与日志stderr分开。

PT5 已接入只读 `project history <project_id> [--from RFC3339] [--to RFC3339] [--actor REF] [--subject REF] [--limit 1..200] [--cursor CURSOR] [--json] [--export]`、`task history <task_id> [--project-id ID]`、`audit event <event_id> [--project-id ID]`、`checkpoint list <project_id> [--verify]` 和 `checkpoint verify <digest>`。它们分别映射到上述 HTTP 查询，使用私有控制凭据、同一 AuditPage/验证投影，不写事件或推进 revision；`--export` 额外输出带 schema/source/lineage/exported_at 的脱敏导出。

退出码：0成功或异步已受理（输出operation_id）；2输入/用法；3认证/授权；4revision/state/blocker冲突；5基础设施失败；6`--wait`达到明确客户端等待上限但Operation仍继续。不要用等待超时反推业务失败。daemon start只本机管理，不改用户宿主安全配置。
