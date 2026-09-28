# 持久化审计证据与边界

observed_at: 2026-09-27T14:02:11.721Z
source_commit: a3954ae
sample_project: SegaImageManageTool
sample_project_id: a8ed4700-2472-41ee-91a7-be8e887e8a98

本轮对演示数据库仅使用 SQLite mode=ro；不重新启动 daemon，不导出原始凭据、不迁移样本。本页统计是采样事实，不是未来验收结论。

## 样本

events 252，commands 243，module_state 7，operations/jobs/outbox 均 0。
119 条 session.reconnect；122 条 command result 含 secret_token 或 reconnect_nonce 字段。
任务 3 个：后端/前端 completed，初始设计任务 cancelled。此前 HTTP 检查记录 8 Attempt、2 Task Result、9 Report、2 resolved Discrepancy、1 accepted Contract、5 Message；本轮任务状态与数据库计数已复核，其余不冒充本轮重新执行的 HTTP 结果。
3 个 patch 大小 91935、185981、375798 字节；按生成顺序分别嵌入 0、1、2 个先前 patch 的 diff 条目。

## 源码锚点

| 问题 | 可复查位置（行号针对上述版本） |
|---|---|
| result 原样写入幂等表 | src/tsunagou/platform/db/sqlite.py dispatch，约 478 行 |
| 每条 command 重写所有 module_state；lineage 固定 local-lineage；事件仅 command_kind | src/tsunagou/platform/state.py persist，约 441 行 |
| audit 丢弃已有 occurred_at，固定 200 条且无下一页 | src/tsunagou/bootstrap/container.py query audit，约 397 行；api/app.py project_audit |
| baseline 根据 git status 名称而非文件内容计算 | src/tsunagou/modules/workspaces.py scan_root / _patch_bytes |
| 输入 patch_artifact_ref 可覆盖系统扫描得到的 digest | src/tsunagou/application/handlers.py workspace_result |
| artifact 写到 .tsunagou/artifacts 并按 hash 直接读取 | src/tsunagou/bootstrap/container.py artifact_root / artifact query |
| checkpoint 在 handler/UoW 中进行文件物化；原始模块快照以字段黑名单过滤 | application/handlers.py checkpoint_create_user / completion_confirm；platform/checkpoints.py |
| Git anchor 用 checkpoint digest 与 commit OID 字符串匹配 | platform/checkpoints.py GitAnchorScanner.scan |
| 查询 CLI 尚不齐全 | src/tsunagou/cli/app.py；上一轮真实 --help 输出 |
| 最近代码新增 coordination 状态与两套 wake 记录 | modules/coordination.py；platform/state.py；hostwake/。修复必须覆盖这些事实，不另外复制 Task 真相 |

## 对上一轮结论的校正

1. 演示项目 checkpoint 为 0，不表示产品没有 checkpoint 实现；已有创建/失败重试和 tests/integration/test_checkpoint_failure.py。缺口是初始化接通、导出内容、事务外物化、历史查询和 clone 导入闭环。
2. 119 条 reconnect 与演示中临时 bridge 频繁启动有关。先验证常驻 bridge 行为，再减少多余握手；epoch 真变化必须保留。
3. 8 Attempt 是历史故障事实，应保留。这里不据此擅自修改 Lease TTL 或取消 fencing。
4. 共享工作区的 diff 不能证明作者。数据库中的 submitted_by 证明持该认证身份提交了结果，不能证明每一行来自该会话。
5. 现有结果中的 working-tree 引用和测试命令字符串是弱证据；实际浏览器/大文件修复没有自动纳入原 Task Result，应作为新的后续任务，不能追补冒充当时验收。
6. events 时间已有整数毫秒，部分实体为浮点秒，另一些无时间；问题包括查询丢失、单位不统一和缺少来源，不是所有时间都没记录。
7. 本次不把同机数据库摘要升级为不可抵赖证明；Full Access 持有者仍可改本机文件。

## 外部依据

访问日期 2026-09-27。只用于工程机制，不改变用户权限：
- [RFC 3339](https://www.rfc-editor.org/rfc/rfc3339)：公共时间使用明确偏移，规范输出 UTC 毫秒。
- [SQLite Backup API](https://sqlite.org/backup.html)：一致备份使用数据库 API，不能遗漏 WAL 后直接复制主文件。
- [SQLite WAL](https://sqlite.org/wal.html)：清理秘密要考虑 WAL/SHM 与连接生命周期。
- [SQLite secure_delete](https://sqlite.org/pragma.html#pragma_secure_delete)：行级清理不构成整个文件系统/备份介质的秘密擦除保证。

