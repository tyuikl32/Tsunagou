# A6 用户决定源码修复与回归

日期：2026-09-28。仅记录源码/自动化回归，不将 A6 原 Desktop 用户答复后的恢复实测改为通过。未操作现场 daemon、凭据或会话，未提交 Git。

## 实际断点和修改边界

核对当前工作区后，`bootstrap/container.py` 已有 lifecycle 非空时的决定列表分支；末尾空列表是 lifecycle 缺省分支。因此不能把本次问题写成“所有决定查询永远为空”。实际缺口是列表的 `expected_revision` / `input_digest` 与 CLI 文档的 `revision` / `proposal_digest` 不一致，提案原始 `choices` / `summary` 没有保存，resolve 没有给 main 留持久通知。

本批在原有字段、状态、U-only 命令和同事务消息基础上修复：

- `application/workflows/lifecycle.py`：保存 choices 的独立副本及 summary；缺少内容的已有记录默认 null，不编写迁移或猜测旧选项。
- `bootstrap/container.py`：修复现有列表投影，返回选中 project_id、decision_id、kind、subject_ref、revision、proposal_digest、choices、summary、status、decision、reason；继续由原 entity metadata 添加 UTC created_at / updated_at。
- `api/app.py` 与 `cli/app.py`：决定列表复用 U/B 认证；CLI decision list 显式发送私下读取的 control token。多项目先由现有 daemon 路由选中独立容器，再校验该项目凭据。
- `application/handlers.py`：成功 U resolve 后，同 UoW 向此时任命的 main 创建一条 `user_decision.resolved` 消息，由既有消息持久化/outbox 路径投递。无 main 时只保存答复供查询。没有自动 begin、释放或恢复 Task/Attempt。
- `platform/shared_checkpoint.py`：choices / summary 加入原有共享投影白名单，继续使用原脱敏函数。
- `protocol/openapi.json` 与打包副本：重新生成决定列表认证头契约。没有更改已有 propose/resolve 命令 Schema 或 principal。
- 用户手册 6.1、项目模块字段表和 entrypoint spec 同步。

### 公共协议漂移复核 — 2026-09-29

独立复核发现 UserDecision 的 canonical schema 与实际 typed tool/CLI 请求还有两处不一致：propose 的 `proposal_digest` 在运行时是可省略并由 daemon 计算，却被 registry/schema 列为必填；resolve 的实际 payload 含 `decision_id`，schema 却因 URI 中也有 `{id}` 而禁止该字段，并错误要求可选的 `reason`。这会让相同操作在 MCP、HTTP 和 CLI 入口得到不同的前置校验。

已按现有运行时语义修正 command catalog、canonical schemas、Python/bridge registry 镜像和 OpenAPI 生成输入：propose 的 digest 与初始 `expected_revisions` 均可选（daemon 分别计算 digest、默认版本 1），resolve 需要 `decision_id`、`choice`、`expected_revisions`、`proposal_digest`，`reason` 可选。新增 valid fixtures 和 protocol regression 验证 registry、schema、runtime `PAYLOAD_FIELDS` 及打包副本一致；没有增加字段、权限或迁移。bridge 的 `decision__propose` 已有同样的可选形状，resolve 仍是用户 CLI/HTTP 命令，不额外注册 Agent 工具。

resolve 通知：sender=`user_control`，recipient=当前 main，subject=`decision/<decision_id>`，summary=`User decision resolved: approved|rejected`。

```json
{
  "decision_id": "<decision>",
  "kind": "<proposed kind>",
  "subject_ref": "<proposal subject>",
  "revision": 7,
  "proposal_digest": "sha256:<exact proposal digest>",
  "status": "resolved",
  "decision": "approved",
  "reason": "<user supplied reason>",
  "related_task_id": "<task id or null>"
}
```

消息正文仅在原收件箱权限内读取；outbox 存消息引用与摘要，没有复制正文。原始提案仍可经认证决定列表读取。当前支持答复 `approved` / `rejected`，本次没有扩大为自定义选项执行器。

## 验证

`uv run pytest -q tests/integration/test_user_decisions.py`：10 项通过。最初两项测试错误地查询 outbox 不存在的 payload_json 列；改为核对真实 payload_digest、target_ref、kind 与同 event_seq 后通过，没有因此改变运行时表结构。

协议漂移补丁的 `tests/protocol/test_user_decision_contract.py`、协议 codegen 回归、A6 集成和生命周期测试通过；Ruff、mypy、OpenAPI 重新生成和文档校验通过。随后复核到 bridge/runtime 同样允许省略初始 `expected_revisions`，因此一并同步为可选并覆盖默认版本 1；resolve 仍要求显式版本。具体组合回归命令及最新结果由主会话追加，避免把源码回归写成现场 A6 通过。

新增回归覆盖真实 loopback HTTP + CLI list/resolve、提案正文和 UTC 时间、未答时间推进与只读不变、同 SQLite 重建、当前 main 换任后精确收信、approved/rejected 两条路径、原主 Agent 无收件权限、审计可见决定但不泄漏私信、重复命令与重启后重放无第二条通知、通知创建后故障整笔回滚、错误 principal/digest/revision/choice 拒绝、多项目路由及交叉凭据拒绝。相关任务由 owner 明确 block，未答时无关任务完成，答复后原任务仍 blocked。

`tests/unit/test_lifecycle.py` 新增调用方修改提案对象后已保存正文不变的回归。

以下组合回归通过：

```text
uv run pytest -q tests/integration/test_user_decisions.py tests/integration/test_execution_begin.py tests/integration/test_m1_runtime_flow.py tests/unit/test_lifecycle.py tests/unit/test_checkpoint_materialization.py tests/unit/test_trace_audit.py tests/protocol
```

Ruff（6 个已触及源码文件和 2 个测试文件）、mypy（同 6 个源码文件）均通过。`python tools/docs/validate_docs.py` 通过。`git diff --check` 对本批相关已跟踪文件通过。OpenAPI 已用 `uv run python tools/codegen/generate_openapi.py` 重新生成。测试仍有项目原有 FastAPI on_event 弃用提示。

## 尚需现场完成

原 daemon 需加载当前修复。main 提出真实待答项、相关 Worker 自行保存并挂起、无关任务继续、用户以实际版本/digest 答复后，验证 daemon 唤醒原 main 会话，main 判断并通知原 Worker 恢复。自动化证明的是 SQLite/API/CLI/outbox 路径；不证明真实用户已答复或原 Desktop 已恢复，也不修改 A6 未完成结论。
