# PT4 项目真相、checkpoint 与恢复

- created_at: 2026-09-27T14:39:38Z
- status: planning；parent: persistence-traceability；depends_on: PT2, PT3

## 目标

建立 genesis、提交后 checkpoint、可验证 Git anchor 和不继承活动权限的 clone 恢复，消除共享 JSON、SQLite 和动态 runtime 互相覆盖。

## 范围与约束

- SQLite 事件/领域状态是运行时事实；共享快照使用白名单 DTO。runtime epoch、grant、lease、宿主 conversation、private inbox 和 job claim 不进入共享真相。
- checkpoint 只在初始化、用户/主 Agent 明确的里程碑或完成确认产生；提交后物化，通过 operation/outbox 可重试。文件失败不回滚已提交业务事实。
- Git anchor 只接受允许的本地 heads/tags 并验证 manifest/tree 实际内容；不接受 remote ref、reflog 或 OID 子串匹配。
- 恢复先 preview 后 user-only confirm；新 runtime 取消旧 session/grant/lease/job claim/bridge ticket。

## 交付与验收

1. genesis 与 checkpoint manifest 有 schema/projection、through_event_seq、actor、原因、digest、验证时间和状态，且没有 secret、绝对路径或活动权限。
2. 注入事务后物化前、物化中、物化后、重启和重复 reconcile，验证 operation 状态和幂等结果。
3. 验证正确 refs/tree、错误 OID 子串、remote/reflog、内容不匹配的 Git 情况。
4. 在临时干净 clone 演练 preview/confirm，证明历史保留而活动权限不继承。

## 不做

不自动 commit/push，不把整个模块 JSON 改成全量 Event Sourcing，不在规划轮操作真实项目库。
