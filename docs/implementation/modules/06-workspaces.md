# 06 工作区、隔离策略与主 Agent Git 控制

FX2 将隔离选择归属 Task，基线与结果仍归属每个 Attempt。不存在全局默认隔离方式；main 按实际任务选择一次。

## 策略和对象

| 对象 | 关键语义 |
|---|---|
| IsolationDecision | task_id、scope_revision、revision、driver_kind、root_binding_refs、repository_id、external_locator、input_digest、hard_constraints、evidence_refs、decided_by、decision_digest |
| Workspace | attempt_id、decision_id、driver、绑定根、scope_paths/scope_roots/scope_digest、baseline_manifest_id、result_manifest_id、status |
| BaselineManifest | 当前 HEAD/branch、index 与文件摘要、untracked、根 identity、逐根观察与 digest |
| ResultManifest | 精确 workspace/attempt/baseline、changed_paths、patch 引用、逐根观察、observed_at、Agent 报告的 validation_metadata |
| GitActionRequest | main 发起的整合/清理等意图及报告，不能替代实际 Git 结果 |

## 三种隔离方式

- shared：使用已绑定的单个或多个原目录，可接受 dirty 基线。
- worktree：main 先准备单仓库的实际 worktree 并注册绑定；策略需 repository_id，开始时要求干净基线。daemon 不创建 worktree。
- external：main 先准备外部目录/环境并绑定根；策略记录 external_locator。实际文件观察以受任务 scope 约束的 root bindings 为准，locator 不额外授予任意路径访问。

仅有 named 资源或空 scope 的任务无需 workspace。文件 scope 必须能解析到本机已绑定且物理 identity 一致的 roots；Worker 无权在 begin 时扩大路径。

## 正常执行

1. main 创建 Task 的范围，准备 Git/外部目录，并调用 workspace.select。选择绑定 task/scope_revision，不需要 attempt_id。
2. Worker task.begin 校验策略，在写事务外采集实际文件基线；短 UoW 原子保存 Workspace/Baseline、Attempt、资源占用和 Grant。
3. Worker 工作后 task.submit 自动扫描同一 scope，物化必要 patch，再原子保存结果、提交 Task 并释放占用。
4. main 查看结果、测试报告及文件变化，决定接受或返工。Git 写和整合仍由 main 执行。

纯任务状态变化、重新连线或同 owner 恢复不要求 main 重新选择策略。新 Attempt 创建新 Workspace 和新基线。scope 改变后必须选适用于新 scope_revision 的策略；active Attempt 期间禁止改变策略。

## 证据的含义

文件观察是 daemon 观测事实；validation_metadata 中的测试命令、起止时间、退出码是 Agent 报告，不能自动提升为系统验证。用户手动写入可能与 Worker 写入一起出现在观察差异中；系统不猜写入者，不自动回滚。

patch 默认排除私有 .tsunagou 数据与 scope 外内容；符号链接只记录链接事实，不读取目标秘密。patch 物化可以在失败提交后留下未引用内容，但失败事务不能留下有效结果/附件引用或释放占用。

## Git、整合和清理

所有 Git 写操作由 main 控制，包括 worktree add/remove、checkout/reset、commit、merge、push。daemon 的 Git port 仅执行已允许的只读命令。任务流程不因没有 commit 而强迫提交代码。

整合请求引用明确 source result、目标 repo/基线及方案 digest。部分成功按实际结果记录；跨仓库没有伪造的原子回滚。发布证据由 main 报告，不声称 daemon 已独立核验远端。

清理遵守任务终态、checkpoint 与现有 dirty/user-only 边界。FX2 不新增清理平台或自动回收计时器。

## 验证

tests/unit/test_workspaces.py、test_workspace_evidence.py 验证读写边界和 scope；tests/integration/test_execution_begin.py 验证策略复用、新 Attempt 新基线、准备/物化不占 SQLite 写事务、失败回滚和自动提交；test_trace_workspace_access.py 验证附件访问身份与重启恢复。
