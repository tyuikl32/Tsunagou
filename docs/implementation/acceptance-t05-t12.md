# T05-T12 实施与验收台账

本台账记录当前实现边界和可复现证据。每个任务的 PRD、实现步骤和 Trellis context 是详细交接入口；本台账不把 mock 行为或文档计划写成真实宿主能力。

| 任务 | 当前实现 | 主要证据 |
|---|---|---|
| T05 项目与根目录 | 完成 | `src/tsunagou/modules/projects.py`、`tests/unit/test_projects.py` |
| T06 身份与授权 | 完成 | `src/tsunagou/modules/authority.py`、`tests/unit/test_authority.py` |
| T07 消息与回应义务 | 完成 | `src/tsunagou/modules/messaging.py`、`tests/unit/test_messaging.py` |
| T08 任务与 Attempt | 完成 | `src/tsunagou/modules/tasks.py`、`tests/unit/test_tasks.py` |
| T09 资源 Lease | 完成 | `src/tsunagou/modules/resources.py`、`tests/unit/test_resources.py` |
| T10 认知协调 | 完成 | `src/tsunagou/modules/cognition.py`、`tests/unit/test_cognition.py` |
| T11 工作空间与 Git 请求 | 完成 | `src/tsunagou/modules/workspaces.py`、`tests/unit/test_workspaces.py` |
| T12 附件与内容寻址 | 完成 | `src/tsunagou/modules/artifacts.py`、`tests/unit/test_artifacts.py` |

## 统一门槛

完成 T12 后执行：

```text
uv run pytest
uv run ruff check src tools tests
uv run mypy src
uv run python tools/dev/check_architecture.py
uv run python tools/codegen/validate_protocol.py
corepack pnpm -r run check
python tools/docs/validate_docs.py
```

本轮实际结果：`44 passed`；Ruff、mypy、架构检查、协议校验、六个 TypeScript workspace 检查和文档校验均退出码 0。

T05 的共享项目记录写入协调仓库 `.tsunagou/project.json`，本机绝对路径只写入 `.tsunagou/local/bindings.json`。T06 的 token 只返回给私有接入调用方，持久状态仅保存哈希；宿主 Full Access 仍不等于系统能够提供 OS 级强制隔离。

T07 的 ACK 不代表呈现，只有带 evidence 的 `present` 才记录呈现；没有 push 时可以用 `sync` 恢复。T08 的 `claim`、`resume`、`start`、`submit`、`review` 是不同状态转换，父任务和 blocks DAG 不互相级联。

T09 的 resource Lease 不是文件锁；外部写入只生成 observation。T10 不执行语义模型推断，自由文本不能单独生成 hard discrepancy；risk acceptance 保留 `unknown` 的有效结果，不显示为 succeeded。

T11 的 Git port 只允许显式只读命令；worktree 创建/移除、commit、merge、push 都由主 Agent 的请求等待执行证据。T12 finalized blob 不自动 GC，recipient-only 引用不能仅凭 hash 或 main 身份读取。
