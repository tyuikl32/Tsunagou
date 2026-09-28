# PT3 实施步骤

1. 修复 content digest，建立 tracked/untracked/同路径改内容/范围外/symlink fixtures。
2. 固化 ArtifactRef owner/domain/scope 校验，禁止外部引用覆盖系统扫描结果和 patch 递归嵌套。
3. 加入 agent_asserted、host_observed、system_verified、user_confirmed 回执与脱敏摘要测试。
4. 用临时项目验证 CLI/HTTP 展示提交者、观察者、工具和弱证据限制；不声称逐行作者。

## 实施记录（2026-09-27T18:08:00.000Z）

- `WorkspaceService` 现在把主 Agent 选择的相对 scope 规范化并保存 `scope_digest`；Git status 使用 NUL 协议，patch 与摘要使用同一 allow-list，拒绝绝对路径、`..`、`.git`、`.tsunagou` 和越界 reparse point。
- 文件证据记录 regular/missing/symlink/link_outside/special/unreadable 类型、内容或链接摘要、大小和模式；patch 使用原子临时文件落盘，禁止将既有 patch 重新递归收入。
- `ResultManifest` 保存 scope、artifact domain/owner、观察摘要和验证回执。Agent 自报等级固定为 `agent_asserted`；daemon 的 `workspace.scan` 单独追加 `system_verified` 回执。
- HTTP artifact 查询必须先认证，并且 hash 必须被当前 workspace result 绑定；读取者只限 user、current main、提交者或 Attempt owner，文件摘要会再次校验。
- 同步更新 `workspace.prepare`/`workspace.result` 命令目录、生成 Schema、Python 包内协议镜像和工作区证据说明。

## 本阶段验证

`tests/unit/test_workspaces.py` 覆盖同路径改内容、scope 外 sentinel、tracked/untracked 私密目录、symlink、scope 拒绝和证据降级；M1 集成流覆盖 artifact 匿名拒绝及 user-control 读取。完成 PT3 前仍须执行全量 Python/Node/协议/文档检查并通过 Trellis check。

## 最终验证 2026-09-27T19:44:32.466Z

全量 Python、Ruff、mypy、TypeScript、协议、文档、架构与任务上下文检查通过；见 `research/verification.json` 和 `research/review-pt3.md`。无实际 daemon 扫描的外部结果已改为 `observed_by=null` / `evidence_subject=agent_assertion`。PT3 完成，提交后文件物化交由 PT4。
