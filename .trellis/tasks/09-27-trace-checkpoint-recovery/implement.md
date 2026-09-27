# PT4 实施步骤

1. 建立 genesis 和 checkpoint manifest DTO/版本，删除共享 JSON 中动态 runtime 字段。
2. 将 checkpoint 文件 I/O 移到提交后 operation，加入失败、重启、重复 reconcile fixtures。
3. 用真实临时 Git repo 验证 branch/tag/tree 内容；拒绝 OID 子串、remote ref、reflog 和不匹配内容。
4. 演练 clone restore preview/confirm，检查权限全部清除、历史 lineage 正确；不得操作真实用户库。

## PT1 衔接检查

- 项目 registry 已进入事务内 module snapshot 以观察配置/root 变化；现有 handler 的共享文件写入仍早于提交，须在本任务转为提交后幂等物化。
- dispatcher 已在写锁内 capture，但异常后的内存 restore 仍在锁外；同时，提交后 hook 失败可能让调用层误恢复旧内存。必须区分未提交回滚与已提交未应答，覆盖并发命令及进程中断窗口。
- Operation/Job 独立数据库状态变化不经过 ServiceStateRuntime，需接入同一审计包络并记录实际时间/执行主体，不能声称仅有领域快照事件便已覆盖它们。

- 维护循环另有在 writer lock 外 capture snapshot 的路径，需与 dispatcher 的提交/回滚窗口统一验证，避免失败恢复覆盖并发成功状态。

## 执行中记录（2026-09-27）

已落实提交后 CheckpointWorker、Job/outbox、固定重试输入、显式共享 DTO、项目文件投影、Operation/Job 审计、目录原子发布及 Git tree 校验。已接入 clean clone preview/confirm CLI 与恢复端口；恢复保留历史并撤销所有活动权限。

基础 checkpoint/storage/runtime 集成 19 项通过；扩大测试后已修正 genesis 导致的测试水位假设与维护测试替身签名。真实 Windows Git clone 揭示 autocrlf 会破坏 NDJSON 字节摘要，正在补 `.gitattributes` 并继续完整恢复验证。审查仍在进行，本任务未完成，不将局部通过当作整体验收。
