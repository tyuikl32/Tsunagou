# 本地 Git Anchor 的发现与验证

> 核对日期：2026-09-17。
> 状态：第 159 题已确认选项 A；作为 D82 的本地 anchor 发现基线。

## 目标

用户负责创建 Git commit，调度中心负责判断某个不可变 checkpoint 是否真的被该 commit tree 完整承载。验证只读取 commit object/tree，不依赖当前工作树，因此可以与后续 SQLite 协作并行；验证成功覆盖的是指定 checkpoint，不会把更新的未提交状态一起算入。

[git fsck](https://git-scm.com/docs/git-fsck)区分由 refs 可达的对象、仅由 reflog 保留的对象和 unreachable/dangling 对象。因此“object database 中存在 commit”不足以作为稳定本地覆盖证据。[git for-each-ref](https://git-scm.com/docs/git-for-each-ref)支持按包含某个 commit 的 refs 查询，[git cat-file](https://git-scm.com/docs/git-cat-file)可批量读取对象信息和内容，适合不 checkout 的确定性校验。

## 选项

| 选项 | 发现方式 | 优点 | 代价 |
|---|---|---|---|
| A（推荐） | 混合：后台/状态查询自动发现，另提供显式 verify 命令；两条路径调用同一个只读验证器 | 普通用户 commit 后无需登记；自动发现延迟或异常时可立即验证；生命周期门禁可强制刷新 | 需要去重扫描和 Git 变更检测；状态可能在短暂延迟后更新 |
| B | 仅显式：用户每次 commit 后执行 anchor register/verify | 行为完全可预测；后台最简单 | 容易忘记，项目会长期误显示 unanchored/lagging；自动化流程多一步 |
| C | 仅后台：daemon 持续监测 refs 并自动登记 | 交互步骤最少 | 文件 watcher 可能漏事件；用户无法要求一次确定性刷新，脚本等待语义变差 |

## 选项 A 的触发方式

统一的 `LocalCoverageVerifier` 由以下入口触发：

- 项目打开/恢复后执行一次；
- 新 checkpoint 完成物化后登记一个带 debounce 的低优先级 scan job；
- Git common directory 的 refs/HEAD 变化只作为唤醒提示，watcher 事件不承担正确性；
- `project status`/`doctor` 可返回缓存证据，并用参数要求刷新后返回；
- replica 切换、lineage transition、本机最后副本清理等依赖证据的操作必须同步刷新；
- `tsunagou project durability verify --local [--commit <oid>]` 提供显式、可等待的同一验证路径。

后台 job 合并重复请求，按 Git common-dir fingerprint 使用单一 `concurrency_key`。没有 refs/checkpoint 摘要变化时直接复用上次结果，不重复逐文件 hash。

## 哪些 ref 可形成 local anchor

首版 eligible refs allowlist：

- `refs/heads/*`：本地分支；
- `refs/tags/*`：轻量或 annotated tag 最终 peel 到的 commit。

以下均不能单独形成 local anchor：

- detached `HEAD`、reflog 和仅按 OID 可读取但不可达的 commit；
- `refs/remotes/*`：它只代表本机上次 fetch 的记录，publication 仍需 `ls-remote` 在线证据；
- `refs/stash/*`、`refs/bisect/*`、`refs/replace/*`、Git notes、worktree pseudo-ref 和未知命名空间；
- index、工作树文件、未跟踪文件或暂存区 tree。

显式 `--commit` 可以验证任意 commit 内容用于诊断，但只有它被至少一个 eligible ref 包含时才提升 coverage。否则返回 `valid_but_not_durably_referenced` 与包含它的非合格 ref 列表。

## 验证算法

1. 在进程启动时核对 Git executable/version；命令通过参数数组执行，关闭交互提示并设置有界超时。
2. 枚举 eligible refs 及 peeled commit OID，保存 refs snapshot hash；相同 OID 只读取一次。
3. 从每个候选 commit tree 读取 `.tsunagou` checkpoint catalog/manifest，不 checkout、不运行 hooks。
4. 校验 shared format、project/lineage、schema bundle、checkpoint ID/hash、父 checkpoint hash与 catalog 一致性。
5. 按 manifest 从同一 commit tree 批量读取全部共享文件，校验 mode、size 和原始字节 SHA-256；拒绝 symlink、submodule 或越界路径替代普通受管文件。
6. 验证 `.tsunagou/local/`、secret/temp patterns 未出现在 tree 中；出现时不给 anchor，并产生高优先级诊断。
7. 在 lineage checkpoint DAG 中选择被 eligible ref 覆盖的最高 checkpoint；与 SQLite 最新 sealed checkpoint 比较，得出 `current` 或 `lagging`。
8. 在 SQLite 事务中写 immutable evidence、更新派生 coverage 和审计事件；相同 commit/checkpoint/verifier version 幂等，不重复发事件。

如果 refs 在步骤 2 与提交 evidence 前变化，重新读取 refs snapshot；不一致则丢弃本轮派生状态并有限重试。commit/tree 对象本身不可变，但“是否仍由 eligible ref 可达”会改变。

## 降级与历史证据

- 后续 branch reset/tag delete 使 anchor 不再被任何 eligible ref 覆盖时，当前 coverage 可从 current/lagging 降为 none；旧 evidence 作为审计事实保留。
- 本地 Git 暂时不可用时标为 unavailable，并展示 last_verified evidence；不能把 unavailable 转成 none。
- lineage 不匹配的合法 checkpoint 作为 `foreign_lineage_detected` 诊断，不参与当前 coverage。
- 验证发现分叉时进入既定 diverged 规则；后台验证器不自动 checkout、merge、reset、创建 tag 或 ref。
- 大量历史 refs 的扫描有 budget；首版优先当前 branch/ref tips 和上次有效 refs。超过预算返回 partial/unavailable，不基于部分结果宣称 none。

## 接口语义

显式 verify 返回一个 Operation 或同步小结果，至少包含：

- `refs_snapshot_hash`、`verified_at`、`verifier_version`；
- `coverage_status`、`latest_anchored_checkpoint_id/hash`；
- `anchor_commit_id`、eligible ref names；
- 最新本机 checkpoint 与落后数量/关系；
- issues、scan completeness 和是否写入新 evidence。

默认人类输出可以建议用户 commit；JSON/REST/MCP 必须使用稳定字段，不把具体 shell 命令作为唯一修复信息。

## 后续待细化

- checkpoint catalog 的路径、结构和如何避免每个 ref 扫描完整历史。
- watcher/轮询间隔、scan budget、缓存键与 Git 进程超时默认值。
- verify endpoint、Operation 阈值、CLI `--refresh/--wait` 的精确约定。
- SHA-1/SHA-256 Git object format 的测试矩阵；领域 checkpoint hash 始终独立使用 SHA-256。
