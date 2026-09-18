# 06 隔离、工作空间与主 Agent Git 控制

## 产品支持矩阵

| driver | 首发支持 | 机械职责 |
|---|---|---|
| shared | 多 roots 的原目录协作 | 记录 binding/基线/Lease 需求，不创建隔离幻觉 |
| worktree | 单 Git 仓库的 Worktree | 生成主 Agent GitActionRequest；只读核验实际 worktree、commit、状态 |
| external | 外部已准备的容器/目录/环境 attach | 验证用户/main 提供的能力与绑定证据，不创建容器平台 |

没有全局单一默认隔离方式。主 Agent按任务风险建议，系统验证 candidate 满足授权与 hard constraints。首发不实现跨多个仓库的原子 Git commit/merge，也不内建容器编排。

## 数据

| 表（`workspaces_`） | 字段 |
|---|---|
| drivers | 静态 registry：kind,version,capabilities,required_evidence,supported_platforms；不接受运行时任意代码插件 |
| decisions | task_id,attempt_id,risk_submission_ref?,driver_kind,input_digest,hard_constraints,evidence_refs,decided_by,decision_digest |
| instances | attempt_id,decision_id,driver_kind,status,root_binding_refs,repository_id?,external_locator?,baseline_manifest_id?,result_manifest_id?,revision |
| git_requests | workspace_id?,repository_id,action:worktree_create|worktree_remove|commit|integrate|publish|repair,requested_main_id,exact_input_digest,parameters,operation_id,status:pending|reported|verified|rejected|unknown |
| baselines | workspace_id,root/repo identities,head_commit?,branch?,index_digest,tracked_state_digest,untracked_summary,captured_at,digest |
| results | workspace_id,attempt_id,baseline_digest,commit_refs[],patch_artifact_ref?,changed_paths,untracked_summary,validation_refs,digest |
| integrations | source_result_ref,target_repository_id,target_baseline_digest,plan_digest,operation_id,status,evidence_refs |
| cleanup_requests | workspace_id,input_digest,required_checkpoint_ref,dirty_state,actor,force_approval_ref?,operation_id,status |

manifest 不把“有一个 commit”当作工作树干净证明；tracked/index/untracked 分别记录。结果未提交必须以 patch/附件与文件摘要提供证据；忽略文件默认不收集其内容。

## 创建与使用

选择 driver→记录 IsolationDecision→Workspace requested→建立 Operation/主 Agent请求→main 执行 Git或外部准备→报告结构化 evidence→后台只读核验→ready→task.start 绑定 in_use。scope、repo HEAD、root identity、能力快照变化使 preflight 陈旧，必须重验。

worktree baseline 必须对应明确 commit，且新 worktree 的 index/工作树无修改、无未跟踪产物后才 ready。跨仓库任务可选 shared/external，不能让一个 worktree ID 代表多个仓库。

**所有 Git mutation 归 current main**，包括 `git worktree add/remove`、checkout/reset、commit、merge、push。daemon 平台 Git port 使用只读 allowlist，禁用会触发外部网络、交互凭据或隐式写入的操作。没有 main 则请求 pending，不用 daemon 兜底执行。

## 整合、发布与清理

main 决定整合顺序、冲突解决与结果是否合格；系统验证目标 repo/基线、权限、manifest 和关联 Operation。多个仓库逐个报告，部分成功保留明确结果，不能伪造事务回滚。publication report 由 main 提交 remote/ref/commit/证据；daemon 不联网验证远端，因此标注 `main_reported`，不能显示 independently_verified。

task terminal +必要 checkpoint 完成后才允许 cleanup。干净 workspace 可由 main 明确发起；dirty 强制清理需要 user-only 决定。清理同样由 main 执行 Git，再核验。存在最后本机副本删除风险时必须额外满足恢复证据或用户精确 data-loss acceptance；本机 anchor 不等于异地备份。

旧 owner 无 stop evidence 时生成残余风险，阻塞相交路径/工作空间的后续动作；不冻结整个无关项目。main 在可委派边界内接受风险并留 digest，用户上限不可被风险接受绕过。

## 端口、事件、验收

`list_driver_candidates`、`get_workspace_preflight`、`record_isolation_decision`、`record_baseline/result`；对外都返回 manifest DTO，不暴露 Git subprocess。事件 isolation_decided、workspace_requested/ready、workspace_result_recorded、git_action_reported、integration_verified、workspace_cleaned。

测试强制抓取所有 daemon Git 调用并验证只读；无 main请求保持 pending；dirty/untracked baseline 拒绝；target HEAD变化使 integration陈旧；重复报告不重复动作；多仓库部分完成可观察；强制清理必须 user_control。实施 T11/T12/T15。
