# R2 实施步骤与交接

先读 [PRD](prd.md)、[design](design.md) 和 implement.jsonl。以下拆自独立成品方案，不表示已经修改代码。

## 启动

先确认 R1 的全部验收条件通过。

```powershell
python .trellis/scripts/task.py validate .trellis/tasks/09-20-r2-runtime-storage-cli
python .trellis/scripts/task.py start .trellis/tasks/09-20-r2-runtime-storage-cli
```

## 实施顺序

最小故障：HTTP用内存Service、CLI另建Service；事实不能跨重启保持、不能事务回滚或幂等。

实施：

1. 装配一个ProjectRuntime，项目路径固定到`<coord-root>/.tsunagou/local/state.sqlite3`。没有已初始化项目时明确拒绝项目命令，不生成内存默认项目。
2. daemon使用进程寿命的项目OS独占锁、单writer队列、统一UoW；第二个进程打开同项目即失败。现有数据库方法内短期文件锁不能替代daemon生命周期锁。
3. 建八模块M1事实表，连接handler用repository。内存仅作请求内对象，不再有独立持久“真相”。身份、Grant、消息也迁移，不能JSON和SQLite双写。
4. CLI的enroll/appoint/decision/operation全部经HTTP到同daemon；新增真实`daemon start/stop/status`、`--project`、必要list/show。连接失败退出5，未知对象404；取消固定`[]/submitted/unknown/ok`成功占位输出。
5. `ProjectDatabase.dispatch`进入原子执行路径。认证/当前epoch检查先于幂等命中；同键同语义返回旧结果，异语义409；主对象revision检查在幂等命中之后。
6. 实现server lifespan启动恢复和优雅停止。启动轮换runtime epoch，撤旧execution Grant/Lease，将未结束执行转blocked/recovery_review（保留Attempt所有者；不宣称进程已经停止）。接入身份可恢复，写代码必须重新resume/preflight/start。
7. 正常查询用只读快照和query port，提供project/tasks/agents/authority/decisions/operations/blackboard。没有数据库就不报告业务健康。
8. 对旧JSON目录做显式一次性导入：先备份，记录源digest/迁移版本，导入在事务内；校验ID/关系失败则保留原件并失败。不存在的旧Task/Contract不能凭Grant反造出来，旧execution Grant一律失效。

出口：重启不丢Task/Contract/Message，CLI票据立即可用；同command重试只一份事实；事务失败不留部分Task/Grant/Event；第二writer无法启动。F01/F02/F05/F11–F14解决。

## 验证与调试

1. 以真实 daemon 子进程测试 CLI→HTTP→SQLite 一致性；中途杀掉进程再启动，查询相同 IDs 和 revisions。
2. 为同键重试/异输入、事务中途异常、第二 writer、旧 epoch、JSON 导入失败增加集成断言。
3. 对照审计 F01/F02/F05/F11-F14 重现并关闭缺陷；旧审计器若因 R1 协议变化失效，迁移案例到正式入口测试，不能只删除失败项。

相关检查入口：

```powershell
uv run python -m pytest -q
corepack pnpm run check
corepack pnpm exec vitest run
python tools/docs/validate_docs.py
```

按实际变更运行对应 lint/type/schema 检查。本轮仅建任务，以上不是已通过的实现验收记录。

旧审计器若因协议变化不能运行，需迁移行为断言到正式入口测试，不能删除失败项后声称完成。

## 交接记录

- [ ] PRD 逐项通过，记录真实命令、退出码、公开查询和数据库事实。
- [ ] 公共接口同步 Schema、registry、生成类型、fixtures 与操作文档。
- [ ] 拒绝用例零部分写入；持久化改动经过重启验证。
- [ ] 记录修改文件、兼容处理、后继依赖和剩余范围，清除成功占位。
- [ ] 验收通过后更新任务/机器计划；按用户授权处理 Git，不自动提交或发布。

实际实现结果（2026-09-21）：daemon lifespan、进程锁、统一 SQLite runtime snapshots、事务幂等、真实 CLI、checkpoint/operation/recovery/audit 查询和公开 endpoint 已落地。Python 105 测试、16 项 standalone backend audit、`tools/dev/smoke_standalone.py` 的启动/停止/重启流程均通过；恢复查询补充了持久 runtime epoch。八模块规范化 repository、后台 Job/outbox 和完整命令矩阵仍未关闭，因此任务保持 planning。
