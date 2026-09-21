# R4 实施步骤与交接

先读 [PRD](prd.md)、[design](design.md) 和 implement.jsonl。以下拆自独立成品方案，不表示已经修改代码。

## 启动

先确认 R3 的全部验收条件通过。

```powershell
python .trellis/scripts/task.py validate .trellis/tasks/09-20-r4-coordination-loop
python .trellis/scripts/task.py start .trellis/tasks/09-20-r4-coordination-loop
```

## 实施顺序

实施：

1. 认知报告校验task/attempt/author关系，保存boundary、understanding、assumptions、uncertainties、claims和input revisions。superseded报告不当作当前理解。
2. 分歧比对限定同项目、同subject和相关当前报告；记录两侧report refs；提供list/show/resolve。主Agent裁决语义与受影响动作，内核只检查结构、主体、版本和契约接受。
3. Contract与相关task/subject关联；required slots全部按同一proposal digest接受才生效。proposal改变或参与者变化使旧接受失效。仅报告存在不等于分歧已解决。
4. resources落实intent/acquire/renew/release；校验有效scope；同物理路径alias归一；整组资源获取失败全部不授予。claim/preflight可预留，blocked释放。
5. background维护到期：一个事务内expired Lease、撤Grant、Task orphaned、事件和通知。bridge每30秒续running Lease，默认TTL120秒；claimed预留过期则重新申请，不能假装已有X执行身份续租。
6. workspace.select由main明确选择shared。prepare创建Operation，Job只读扫描实际roots/Git和文件摘要；把核验过的baseline和revision登记后ready。Git mutation仍由main。
7. task.start核对baseline输入版本；workspace.result采集changed paths、patch/artifact及验证引用。允许Agent预期改动；无法归因的改动记录为观察，由main处理。至少在准备、执行前和结果/整合检查点重验，不把缺watcher写成实时保护。
8. 附件使用现有流式blob算法，新增持久上传intent/ref；领域权限控制读取。TaskResult必须引用本Attempt的workspace result与有效验证记录。
9. 黑板在同一ReadSnapshot中返回任务、reports、契约、分歧、Lease、workspace和blocker；私信只对接收者可见，主Agent无自动旁路。

出口：main+worker围绕同一字段提交不同理解，协商后同意同一契约，worker才可start；重启后仍能查询协商；相交任务等待、无关任务可继续；提交的真实文件patch可取回且hash相符。

## 验证与调试

1. 用两个独立 principal 通过实际 API 构造认知分歧、协商和契约变化，检查 start 的正反结果。
2. 使用临时 Git 项目执行真实文件写入、测试、结果采集与 patch 下载，验证字节/hash。
3. 模拟同物理路径 alias、资源部分冲突、TTL 到期、检查点间手改文件；断言不越权、不部分授予、不静默覆盖。

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

实际实现结果（2026-09-21）：cognition report/query、自动 literal mismatch、contract propose/accept gate、resource intent/acquire/renew/release、shared workspace baseline/result/patch 和 baseline conflict 已接入；双 bridge smoke 覆盖认知分歧、契约双接受、租约及真实文件结果。本轮新增公开 `discrepancy.create/advance/resolve` 以及 `contract.accept_proxy/reject/withdraw`：worker 只能推进分歧，主 Agent通过 `cognition.resolve` 解决，契约拒绝要求参与者和 digest，撤回要求提出者；证据为 `test_cognition_discrepancy_and_contract_resolution_are_public_and_scoped`。

本轮新增 `RuntimeMaintenance` daemon 生命周期维护线程。它在同一 SQLite 文件锁和 UoW 内处理 Lease 到期、Attempt/Task orphan、执行 Grant 撤销和审计事件，并回收过期 Job lease；用户或主 Agent仍需通过 recovery 命令决定 reopen/cancel/fail。`tests/unit/test_runtime_maintenance.py` 覆盖过期后的状态和持久事件，`test_physical_root_aliases_conflict_even_with_distinct_root_ids` 覆盖不同 root_id 的物理 alias 冲突。scope、bridge 自动续租、worktree/external driver、完整风险流程仍待验收，因此任务保持 planning。
