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
| root.bind | `/roots/{id}:bind` | M / root.manage | absolute_path,expected_physical_identity?,reason | RootBinding+Operation；物理验证 |
| repository.register | `/repositories` | M / root.manage | name,root_id,required | RepositoryRegistration+Operation |
| project.reconcile | `:reconcile` | M / project.reconcile | scope_refs,reason | Operation；只读观察、合并计划另确认 |
| ceiling.set | `/control/ceiling:set` | U / — | ceiling,reason | UserCeiling；撤销不再满足范围的Grant |
| project.trust_change | `/control/trust:change` | U / — | change_kind,proposal_ref,proposal_digest,expected_revisions,reason | UserDecision+Operation；协调根/信任边界/高敏root |
| user_decision.propose | `/decisions` | M / decision.propose | kind,proposal_ref,proposal_digest,expected_revisions,choices,summary | UserDecision pending，无deadline |
| user_decision.resolve | `/control/decisions/{id}:resolve` | U / — | choice,proposal_digest,expected_revisions,reason? | UserDecision；审批与相应领域变更同UoW或生成Operation |
| user_decision.cancel | `/decisions/{id}:cancel` | M / decision.propose | reason | UserDecision；仅尚pending，不等于用户拒绝 |
| project.completion.propose.main | `/completion-proposals` | M / project.configure | objective_ref,evidence_refs,outstanding_summary,expected_project_revision | CompletionProposal |
| project.completion.propose.owner | `/completion-proposals:from-owner` | X / task.execute | objective_ref,evidence_refs,outstanding_summary,expected_project_revision | CompletionProposal；必须root/objective owner |
| project.completion.confirm | `/control/completion-proposals/{id}:confirm` | U / — | proposal_digest,expected_project_revision,expected_revisions | Project completed+checkpoint Operation；current Attempts先收敛 |
| project.archive | `:archive` | M / project.archive | reason,expected_checkpoint_digest | Operation；barrier完成再archived |
| project.reactivate.main | `:reactivate` | M / project.configure | reason,expected_runtime_epoch | Project+Operation；policy预授权，无ceiling扩大 |
| project.reactivate.user | `/control:reactivate` | U / — | reason,expected_runtime_epoch | Project+Operation；新runtime，旧执行权不恢复 |
| project.tasks.restore_open | `/tasks:restore-open` | M / task.coordinate | task_ids,expected_revisions,plan_digest,reason | Task[]；全批次原子，无completed |
| project.replica.activate | `/control/replicas/{id}:activate` | U / — | mode:normal|takeover,checkpoint_digest,recovery_evidence_refs,reason | Operation；恢复门槛与单writer |
| project.lineage.reset | `/control/lineage:reset` | U / — | target:checkpoint|empty,checkpoint_digest?,reason | Operation；旧sealed，新unassigned |
| project.unregister | `/control:unregister` | U / — | expected_runtime_epoch,reason | RegistrationResult；不等同删除文件 |
| project.local_copy.delete | `/control:delete-local-copy` | U / — | exact_paths_digest,recovery_evidence_refs,data_loss_acceptance?,reason | Operation；最后副本专门审批 |

普通管理动作需要用户直接操作时，首发只提供以下独立user命令：`project.configure.user`、`root.register.user`、`root.bind.user`、`repository.register.user`、`project.reconcile.user`、`project.archive.user`、`project.tasks.restore_open.user`。URI为相应URI的P后插入`/control`（项目冒号动作如`P/control:configure`）；payload/result不变，principal固定U、无capability、仍验证结构/revision/范围。不得把User token映射为虚假main Grant。T03逐项注册而非运行时通配生成授权。

## Agent、会话与 Authority

| command | URI后缀 | 权限 / capability | payload | result/谓词 |
|---|---|---|---|---|
| agent.ticket.create | `/enrollment-tickets` | M / agent.enroll | kind:worker|session_rebind,adapter_allowlist,ceiling_template,installation_binding?,target_agent_id? | TicketReceipt；secret仅私有交付 |
| agent.ticket.create.user | `/control/enrollment-tickets` | U / — | kind:worker|main|session_rebind,adapter_allowlist,ceiling_template,installation_binding?,target_agent_id?,expected_authority_epoch? | main票据须authority代次 |
| agent.enroll | `/sessions:enroll` | T / — | installation_id,conversation_evidence,descriptor_ref,probe_payload,client_nonce,negotiation | EnrollmentResult；secret走专用header/安全通道 |
| session.rebind | `/sessions:rebind` | T / — | target_agent_id,installation_id,conversation_evidence,probe_payload,client_nonce | replacement HostSession；旧token和Grant撤销 |
| session.reconnect | `/sessions/{id}:reconnect` | D / — | expected_connection_epoch,reconnect_nonce,continuity_evidence,probe_payload | ConnectionResult；token认证+nonce CAS |
| session.reprobe | `/sessions/{id}:reprobe` | D / — | probe_payload,descriptor_ref,reason | CapabilitySnapshot；仅self |
| session.end | `/sessions/{id}:end` | D / — | reason,stop_evidence? | HostSession；self，撤Grant/处理Attempts |
| authority.appoint | `/control/authority:appoint` | U / — | agent_id,expected_authority_epoch,ceiling_template,reason | Authority；ready且baseline通过 |
| authority.revoke | `/control/authority:revoke` | U / — | expected_authority_epoch,reason | Authority unassigned，撤权 |
| authority.handoff | `/authority:handoff` | M / authority.handoff | target_agent_id,expected_authority_epoch,adoption_plan,reason | AuthorityTransition |
| authority.transition.report | `/authority-transitions/{id}:report` | H / authority.converge | stopped_refs,evidence_refs | Transition；只允许收敛对象 |
| authority.transition.adopt | `/authority-transitions/{id}:adopt` | H / authority.converge | adopted_refs,expected_revisions,reason | Transition；target且scope可覆盖 |
| agent.succession | `/agents/{id}:succeed` | M / agent.coordinate | successor_agent_id,attempt_plan,obligation_plan,expected_revisions,residual_risk_refs,reason | SuccessionResult+Operations；不改owner |
| agent.retire | `/agents/{id}:retire` | M / agent.coordinate | expected_revisions,reason,stop_evidence? | Agent；若仍有执行先安全收敛 |

## 任务、Attempt 与验收

| command | URI后缀 | 权限 / capability | payload | result/谓词 |
|---|---|---|---|---|
| task.create | `/tasks` | M / task.create | title,objective,parent_task_id?,execution_scope,required_capabilities,acceptance_policy,prerequisites?,followup_of? | Task draft；parent非终态或明确follow-up |
| task.create.user | `/control/tasks` | U / — | 同task.create | Task；不自动任命自己owner |
| task.update_plan | `/tasks/{id}:update-plan` | M / task.coordinate | title?,objective?,execution_scope?,acceptance_policy?,reason | Task；仅无执行的可编辑态 |
| task.ready | `/tasks/{id}:ready` | M / task.publish | reason? | Task ready；完整结构检查 |
| task.publish | `/tasks/{id}:publish` | M / task.publish | reason? | Task open；ready或changes_requested关闭旧Attempt后 |
| task.edge.add | `/task-edges` | M / task.coordinate | source_task_id,target_task_id,kind,expected_revisions | TaskEdge；blocks无环 |
| task.edge.remove | `/task-edges/{id}:remove` | M / task.coordinate | reason,expected_revisions | EdgeRemoved；留事件 |
| task.claim | `/tasks/{id}:claim` | B / task.claim | capability_snapshot_id | Task+Attempt；open/eligible/原子唯一 |
| task.preflight | `/tasks/{id}:preflight` | B / task.coordinate_self | attempt_id,evidence_refs,expected_revisions | PreflightResult；self current owner，协调态可用 |
| task.start | `/tasks/{id}:start` | B / task.coordinate_self | attempt_id,preflight_id,input_digest,expected_execution_epoch | Task+Grant；claimed，事务内签发执行Grant |
| task.resume | `/tasks/{id}:resume` | B / task.coordinate_self | attempt_id,evidence_refs,input_digest,expected_revisions,expected_execution_epoch | Task claimed；blocked owner，不由main代办；再准备Lease/preflight/start |
| task.progress | `/tasks/{id}:progress` | X / task.execute | summary,evidence_refs | ProgressRecord；running |
| task.block | `/tasks/{id}:block` | B / task.coordinate_self | attempt_id,reason_code,dependency_refs,checkpoint_summary,evidence_refs | Suspension；current owner claimed/running |
| task.submit | `/tasks/{id}:submit` | X / task.execute | summary,evidence_refs,artifact_refs,workspace_result_ref? | TaskResult+ReviewRound；running |
| task.review.accept | `/reviews/{id}:accept` | R / task.review | slot_id,result_digest,evidence_refs,reason | ReviewDecision；指定round/slot |
| task.review.request_changes | `/reviews/{id}:request-changes` | R / task.review | slot_id,result_digest,evidence_refs,reason | ReviewDecision+Task changes_requested |
| task.self_accept | `/reviews/{id}:self-accept` | B / task.coordinate_self | result_digest,evidence_refs,reason | ReviewDecision；原owner、policy low-risk self |
| task.cancel_request | `/tasks/{id}:request-cancel` | M / task.coordinate | reason | Task cancel_requested或无owner时cancelled |
| task.cancel_ack | `/tasks/{id}:ack-cancel` | B / task.coordinate_self | attempt_id,stop_evidence,reason | Task cancelled；owner，仅收敛 |
| task.fail | `/tasks/{id}:fail` | B / task.coordinate_self | attempt_id,reason,evidence_refs,stop_evidence? | Task failed；owner，无成功伪装 |
| task.recover | `/tasks/{id}:recover` | M / task.coordinate | expected_attempt_id,disposition:reopen|cancel|fail,residual_risk_refs,reason | Task；关闭旧Attempt再reopen |
| task.scope.request | `/tasks/{id}/scope-requests` | B / task.coordinate_self | attempt_id,requested_scope,reason,expected_revisions | ScopeExpansionRequest；owner |
| task.scope.resolve | `/scope-requests/{id}:resolve` | M / task.coordinate | choice:approve|reject,proposal_digest,reason | ScopeRequest+Task；审批不超ceiling，执行先block |

## 认知与契约

| command | URI后缀 | 权限 / capability | payload | result/谓词 |
|---|---|---|---|---|
| cognition.report | `/reports` | B / cognition.report | task_id,attempt_id?,boundary,understanding,assumptions,uncertainties,claims,confidence,confidence_reason,evidence_refs,input_revisions,supersedes_id? | EpistemicReport；owner/指定参与者 |
| discrepancy.create | `/discrepancies` | B / cognition.discuss | subject_ref,report_refs,severity,participants,summary,affected_actions | Discrepancy；有subject参与关系 |
| discrepancy.advance | `/discrepancies/{id}:advance` | B / cognition.discuss | status:clarifying|negotiating,reason,evidence_refs | Discrepancy；participant |
| discrepancy.resolve | `/discrepancies/{id}:resolve` | M / cognition.resolve | kind:consensus|dismissal|override,reason,evidence_refs,accepted_by,input_digest | Resolution；override不冒充共识 |
| contract.propose | `/contracts:propose` | B / contract.propose | contract_id?,subject_ref,contract_kind,payload,participants_required,participants_optional,input_refs,supersedes_id? | ContractProposal；subject participant |
| contract.accept | `/contract-proposals/{id}:accept` | B / contract.accept | proposal_digest,evidence_refs | Acceptance；self slot |
| contract.accept_proxy | `/contract-proposals/{id}:accept-proxy` | M / contract.proxy | participant_slot_id,proposal_digest,proxy_policy_ref,reason,evidence_refs | Acceptance；policy明确允许 |
| contract.reject | `/contract-proposals/{id}:reject` | B / contract.accept | proposal_digest,reason,evidence_refs | Proposal rejected；participant |
| contract.withdraw | `/contract-proposals/{id}:withdraw` | B / contract.propose | reason | Proposal；原提议者，尚未accepted |
| risk.request | `/risk-assessments` | B / cognition.report | attempt_id,input_snapshot,input_digest,candidates | RiskRequest；owner；默认120秒fallback窗口 |
| risk.submit | `/risk-assessments/{id}:submit` | M / risk.assess | input_digest,risk_level,reason,recommended_driver,scope,conditions,evidence_refs | RiskSubmission；输入仍当前 |
| risk.accept | `/risk-acceptances` | M / risk.accept | subject_ref,input_digest,accepted_risks,reason | RiskAcceptance；不绕用户/结构不变量 |
| risk.revoke | `/risk-acceptances/{id}:revoke` | M / risk.accept | reason | RiskAcceptance revoked |

## 资源与工作空间

| command | URI后缀 | 权限 / capability | payload | result/谓词 |
|---|---|---|---|---|
| resource.intent | `/resource-intents` | B / resource.coordinate | attempt_id,scope_digest,resources,reason | ResourceIntent；claimed owner、scope子集 |
| resource.acquire | `/lease-sets:acquire` | B / resource.coordinate | attempt_id,intent_id,intent_revision,scope_digest | LeaseSet或Wait；claimed/running owner |
| resource.renew | `/lease-sets/{id}:renew` | X / resource.lease | scope_digest | LeaseSet；running owner，TTL不自行扩大 |
| resource.release | `/lease-sets/{id}:release` | B / resource.coordinate | attempt_id,reason | LeaseSet；owner，允许收敛 |
| resource.wait.cancel | `/resource-waits/{id}:cancel` | B / resource.coordinate | attempt_id,reason | Wait；self |
| workspace.select | `/workspace-decisions` | M / workspace.manage | attempt_id,driver_kind,risk_submission_ref?,input_digest,hard_constraints,evidence_refs | IsolationDecision；结构验证 |
| workspace.prepare | `/workspaces` | B / workspace.request | attempt_id,decision_id,input_digest | Workspace+Operation；owner；Git请求发main |
| workspace.attach_external | `/workspaces:attach-external` | M / workspace.manage | attempt_id,decision_id,root_binding_refs,external_locator,evidence_refs | Workspace+Operation；不创建容器 |
| workspace.git.report | `/git-requests/{id}:report` | M / git.control | exact_input_digest,outcome,evidence_refs,result_manifest | GitActionReport+Operation；main实际执行 |
| workspace.result | `/workspaces/{id}:record-result` | X / workspace.use | baseline_digest,commit_refs,patch_artifact_ref?,changed_paths,untracked_summary,validation_refs | WorkspaceResult |
| workspace.integrate | `/integrations` | M / git.control | source_result_ref,target_repository_id,target_baseline_digest,plan_digest,reason | Integration+Operation；main执行 |
| workspace.cleanup | `/workspaces/{id}:cleanup` | M / workspace.manage | input_digest,required_checkpoint_ref,reason | Operation；terminal+干净，Git仍main执行 |
| workspace.cleanup_force | `/control/workspaces/{id}:cleanup-force` | U / — | input_digest,required_checkpoint_ref,exact_paths_digest,data_loss_acceptance,reason | UserDecision+Operation；dirty/最后副本要求 |

## 消息、附件与持久操作

| command | URI后缀 | 权限 / capability | payload | result/谓词 |
|---|---|---|---|---|
| message.send | `/messages` | B / message.send | kind:notification|request,subject_ref,recipient_ids,summary,payload,artifact_refs,response_contract? | Message+Deliveries；关系/大小/收件权限 |
| message.respond | `/messages/{id}:respond` | B / message.respond | obligation_id,response_payload,summary,evidence_refs | Response+Obligation；原recipient |
| message.waive_response | `/response-obligations/{id}:waive` | B / message.send | reason | Obligation；原sender；main只能以原sender身份 |
| inbox.claim | `/inbox:claim` | B / inbox.consume | limit?,max_bytes? | DeliveryLeaseBatch；authenticated self |
| inbox.fetch | `/deliveries/{id}:fetch` | B / inbox.consume | delivery_lease_id | MessageEnvelope；recipient |
| inbox.renew | `/deliveries/{id}:renew` | B / inbox.consume | delivery_lease_id | DeliveryLease；不超过2分钟 |
| inbox.presented | `/deliveries/{id}:presented` | B / inbox.consume | evidence_kind,evidence_digest | Delivery；能力证据足够才presented |
| inbox.ack | `/deliveries/{id}:ack` | B / inbox.consume | reason? | Delivery；不自动响应 |
| inbox.defer | `/deliveries/{id}:defer` | B / inbox.consume | defer_until,reason | Delivery；只改投递调度 |
| artifact.upload.create | `/artifact-uploads` | B / artifact.attach | domain_ref,visibility:project_shared|recipient_only,size_bytes,media_type,expected_digest | UploadIntent；领域允许该actor附加 |
| artifact.upload.finalize | `/artifact-uploads/{id}:finalize` | B / artifact.attach | digest,size_bytes | ArtifactRef；相同领域授权重验 |
| artifact.promote | `/artifacts/{digest}:promote` | M / artifact.promote | domain_ref,reason | ArtifactRef+Operation；project_shared，禁止hash绕授权 |
| artifact.promote.user | `/control/artifacts/{digest}:promote` | U / — | domain_ref,reason | 同上 |
| checkpoint.create | `/checkpoints` | M / durability.checkpoint | reason,minimum_event_seq? | Operation |
| checkpoint.create.user | `/control/checkpoints` | U / — | 同上 | Operation |
| operation.cancel | `/operations/{id}:cancel` | M / operation.coordinate | reason | Operation；能否中止取决于handler，不伪造撤回外部效果 |
| operation.resolve | `/operations/{id}:resolve` | M / operation.coordinate | conclusion,evidence_refs,reason,followup_plan? | OperationResolution；原unknown保留，只能可授权范围 |
| operation.resolve.user | `/control/operations/{id}:resolve` | U / — | 同上 | User保留动作与越权风险专用 |
| durability.reconcile | `/durability:reconcile` | M / durability.checkpoint | scope_refs,reason | Operation；重试物化，非盲重外部动作 |
| publication.report | `/publication-reports` | M / git.control | repository_id,remote_name,ref_name,commit_oid,checkpoint_digest,evidence_refs,reported_at | PublicationReport；main_reported |
| shared.reconcile | `/shared-state:reconcile` | M / project.reconcile | ancestor_digest,left_digest,right_digest,resolution_plan,expected_revisions,plan_digest | Operation；同lineage且冲突已明确解决 |

附件二进制单独 `PUT P/artifact-uploads/{id}/content`，body为bytes，session凭据+upload ownership认证，不接受任意文件路径；字节重传幂等以expected_digest/length判断。它不直接创建领域事实，finalize才提交引用。

实验管理独立U入口：`experiment.create` → `P/control/experiments`（definition），`experiment.run` → `.../{id}:run`（arm,replicate,config_digest），`experiment.report` → `.../{id}:report`（method_version）；都返回Operation或受控record。内部runner写样本无公共Agent入口。

## 查询目录

| GET URI | DTO / 权限 |
|---|---|
| `/api/v1/projects` | ProjectRegistrationPage / U；Agent只能已绑定project |
| `P`、`P/conditions`、`P/blockers` | ProjectView/ConditionPage/BlockerPage / B、U，敏感字段裁剪 |
| `P/blackboard` | BlackboardSnapshot / B、U；统一read transaction，见runtime-prompts |
| `P/{roots,repositories,agents,tasks,reports,discrepancies,contracts,workspaces,operations,checkpoints}` | 对应分页；每种都注册独立route，不在生产解析花括号 |
| `P/<上述集合>/{id}` | 对应DTO、ETag；必须同project可见 |
| `P/tasks/{id}/{attempts,results,reviews,preflight}` | Task子资源及当前有效preflight；无秘密 |
| `P/authority`、`P/capabilities`、`P/protocol` | AuthorityView、服务端registry、版本/schema bundles |
| `P/sessions/{id}/diagnostics` | SessionDiagnostics / self D或U；诊断不能顺带读项目正文 |
| `P/inbox`、`P/messages/{id}`、`P/response-obligations` | self recipient；sender可读自己发送记录，其他人包括main不能读 |
| `P/artifacts/{digest}?domain_kind=...&domain_id=...` | 经领域引用授权的bytes；hash不是凭据 |
| `P/events`、`P/events:stream` | EventPage或SSE提示；按可见性过滤 |
| `P/decisions`、`P/decisions/{id}` | 待决摘要/详情 / current main、U；关联参与者只见自身阻塞摘要 |
| `P/audit`、`P/metrics`、`P/experiments` | 脱敏AuditPage/MetricPage/ExperimentPage；敏感实验原始证据U |
| `/api/v1/config`、`/api/v1/doctor` | 脱敏设置来源、诊断 / U；不触发repair |

## CLI 映射与退出码

命令树：`daemon start|stop|status`；`project init|list|show|archive|reactivate|unregister|reset-lineage`；`root register|bind|list`；`agent enroll|list|show|reprobe|retire`；`authority appoint|revoke|handoff|show`；`task create|list|show|publish|recover`；`decision list|show|resolve`；`checkpoint create|list|show`；`operation list|show|cancel|resolve`；`config show|validate`；`doctor`；`experiment run|report`。

CLI是user_control入口，必要的Agent执行命令由typed tools完成，不能通过CLI伪造owner。未列出的管理高级命令可通过公共HTTP调用，不承诺为每个底层动作做交互向导。CLI `--json`输出同一DTO/Problem；无secret，quiet/stdout与日志stderr分开。

退出码：0成功或异步已受理（输出operation_id）；2输入/用法；3认证/授权；4revision/state/blocker冲突；5基础设施失败；6`--wait`达到明确客户端等待上限但Operation仍继续。不要用等待超时反推业务失败。daemon start只本机管理，不改用户宿主安全配置。
