# PT 执行顺序与启动门槛

created_at: 2026-09-27T14:39:38Z
status: in_progress / implementation_authorized

用户已下令开始实施。以下步骤现为执行顺序；保留初次规划检查结果作为历史记录。

1. 重新检查 git HEAD、工作树、相关新代码，保存不含秘密的基线；不要覆盖别的任务修改。
2. 读取主设计、PT1–PT7 PRD/design/implement 和上下文；确认用户已批准本版实施。
3. PT1：先落时间、责任、事件与协议契约。
4. PT2：修复秘密交付；发布前完成旧库清理路径，禁止因删秘密破坏恢复。
5. PT3：内容基线、scope patch、ArtifactRef、验证回执。
6. PT4：唯一项目真相、checkpoint 物化/共享/恢复。
7. PT5：完整只读 CLI/HTTP 查询、时间线和权限。
8. PT6：重连与查询降噪、wake 状态关联、后续修复关联。
9. PT7：整体验收、手动说明、迁移演练与最终审核。

每步通过子任务测试后再推进。PT1–PT6 的成功只代表局部验收；PT7 才判定本计划整体通过。开发期间保持真实项目原始库不变，先在脱敏 fixture/临时项目演练迁移；对真实运行库的停止、会话撤销、迁移和恢复作为实施末尾需确认的明确操作。

## 文档与依赖校验

```powershell
python tools/docs/validate_docs.py
python .trellis/scripts/task.py validate .trellis/tasks/09-27-persistence-traceability
python .trellis/scripts/task.py list --mine
git diff --check
```

机器计划还应检验七个子任务依赖无环、plan_id 与 depends_on 一致、状态与实际验收进度一致、上下文文件存在。验证结果填入本文件，不能将文档检查标作产品测试。

## 本轮规划检查结果

- 2026-09-27T14:39:38Z：已写入总设计、机器索引、父子 PRD/design/implement 和上下文 JSONL；尚未运行文档校验，待本轮最后执行。
- 产品代码、外部项目 SQLite、daemon、bridge 和用户运行服务：未修改、未迁移、未重启。

## 验收后回滚原则

按主设计分层回滚。秘密迁移完成后不得恢复带活跃旧令牌的库；checkpoint/协议版本升级禁止旧 writer 写新格式。Git 提交由用户授权的 main 操作；本轮不提交。

## 实施状态（2026-09-27T16:14:31Z）

用户已授权 PT1–PT7。分支为 `codex/persistence-traceability`，未提交。PT1 后端由 `pt1_audit_implementation` 实施，主 Agent 同步协议和验收。已有局部存储/工作区/checkpoint 测试通过，但实体归因、权限分页、秘密交付和 Git 内容验证仍有缺口，任何子任务均未据此标记完成。后续结果继续记录到各子任务 implement.md。
