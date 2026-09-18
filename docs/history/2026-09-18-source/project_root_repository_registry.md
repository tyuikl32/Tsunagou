# ProjectRoot 与 Repository Registry

> 核对日期：2026-09-17。
> 状态：第 163 题已确认选项 A；作为 D86 的 Root/Repository Registry 基线。

## 需要分开的对象

- `ProjectRoot` 是权限、资源 URI 和任务影响范围中的逻辑目录。
- `Repository` 是 Git 状态、commit OID、branch/ref 和集成动作的边界。
- `RootBinding` / `RepositoryBinding` 是某个 replica/机器上的实际路径与 Git common directory。

三者不能合成一个“项目路径”：多个 roots 可以位于同一 repository；一个 root 下可能出现显式 submodule/嵌套 repository；有些 roots 可以不是 Git 目录。linked worktree 也有独立工作树顶层，但共享 common directory。

Git 的 [rev-parse](https://git-scm.com/docs/git-rev-parse)分别暴露工作树顶层、common directory 和 superproject 顶层；[repository layout](https://git-scm.com/docs/gitrepository-layout)说明 gitfile/commondir 用于 worktree 与 submodule。实现必须调用这些 Git 原语，不能通过“是否存在 `.git/` 目录”猜测 repository identity。

## 选项

| 选项 | 登记方式 | 优点 | 代价 |
|---|---|---|---|
| A（推荐） | 共享 manifest 显式声明逻辑 roots/repositories，本机显式绑定路径；添加时只做有界探测并给建议，不自动递归注册；允许受限 non-Git root | 权限边界清楚；支持多机路径差异、多 root 同仓库及非 Git 目录；不会意外扫描/扩大范围 | 首次绑定其他仓库需要用户或主 Agent完成配置；未绑定 root 会阻塞相关任务 |
| B | 同样显式登记，但所有可写 root 必须属于已登记 Git repository | Git 基线与恢复模型统一 | 排除生成目录、外部工具目录和尚未建仓库的真实项目；迫使用户额外初始化 Git |
| C | 从 coordination repo 向下及相邻目录递归扫描，自动注册发现的 Git/non-Git roots | 初始配置最少 | 扫描范围、隐私和性能不可控；nested repo、symlink 与目录移动会悄然改变授权面 |

## 选项 A：共享声明

`.tsunagou/project.toml` 中的声明只包含可移植逻辑信息。

### `ProjectRootDeclaration`

- `root_id`：UUIDv7，持久资源身份；`key`：项目内稳定 ASCII slug；`display_name` 可修改。
- `role`：`coordination`、`source`、`dependency_readonly`、`tooling`、`generated`、`artifact` 或 `external`。
- `vcs_expectation`：`git_required`、`git_optional` 或 `non_git`。
- `repository_id`：已知属于某 repository 时填写；non-Git 为 absent。
- portable binding hint：相对 coordination root 的路径，或不含秘密的 logical locator；绝不存本机绝对路径。
- path/capability policy 上限、默认只读/可写、允许的 workspace drivers、follow-links policy。
- `required_on_activate`：新 replica 激活前必须绑定，或仅当任务引用时才要求。
- declaration revision、created/retired metadata；删除采用 retire，已存在的任务/事件仍能解析旧 root ID。

coordination root 是唯一特殊项：必须为 Git repository 顶层并包含 `.tsunagou`，它的 repository role 为 coordination。其他 roots 可以是其中子目录，也可以位于任意用户批准的本机目录。

### `RepositoryDeclaration`

- `repository_id`、稳定 key/display name、role；
- VCS kind（首版正式支持 Git；non-Git root 不伪装成 repository）；
- root IDs、dependency repository IDs 和是否允许写入/发布；
- 预期 object-format/branch/ref policy 可选，但不提交 remote secret URL；
- submodule/superproject relation 只有经显式确认才进入声明。

共享 `repository_id` 跨 clone 保持，指代逻辑 repository slot；它不是 Git common-dir 路径、remote URL 或某个 commit OID。

## 本机绑定

`.tsunagou/local/config.toml` 与 SQLite 保存 replica-scoped binding：

- binding ID、root/repository ID、原始用户选择与规范化绝对路径；
- 文件系统 identity/fingerprint、case-sensitivity、symlink/reparse 解析结果和可用性；
- Git top-level、common-dir、object format、bare/inside-worktree、superproject 信息；
- local trust/ownership 检查、能力与上次验证时间；
- binding revision/status：`unbound`、`validating`、`active`、`missing`、`moved`、`identity_changed`、`conflicted`、`retired`。

路径移动后可以保留 root/repository identity，但必须由用户或主 Agent显式 rebind 并重新验证文件系统 identity、Git common-dir 与权限。复制目录不能自动继承原 binding ID。

## 探测与登记流程

`project root add/bind` 只探测用户明确给出的路径及定位当前 repository 所必需的祖先，不递归遍历兄弟目录或 home：

1. 规范化路径并在已授权上限内验证存在、目录类型、所有权/可访问性和链接边界。
2. 运行 `git rev-parse --path-format=absolute --show-toplevel --git-common-dir`、inside/bare/superproject/object-format 探测。
3. 与已有 repository bindings 按 common-dir fingerprint 去重；同仓库的新 root 关联现有 repository，不新建 Git identity。
4. 检测当前路径本身是否为 submodule/linked worktree；返回分类建议和潜在边界冲突。
5. 展示将新增/复用的 root/repository、权限上限和本机路径；经相应 authority 命令后写入 shared declaration/local binding。

可提供显式 `project discover --under <approved-root>` 生成候选报告，但它只读、有深度/数量/时间预算、默认跳过 ignored/hidden/vendor 目录，并且永不自动登记或扩大授权。

## 嵌套 Repository 边界

- 已登记 submodule/嵌套 repository 的路径属于最具体 repository binding；父 repository 的任务不能把它当普通文件目录跨越。
- 在已登记 root 内检测到未登记 `.git`/gitfile/common-dir 边界时，涉及该路径的写任务以 `unregistered_repository_boundary` 阻塞，并请求主 Agent/用户分类。
- 只读任务可以按 policy 继续，但影响报告必须标记边界未知；状态 vector 不把嵌套对象计入父 repository。
- 系统不自动执行 `submodule init/update`，不修改 `.gitmodules`，也不假设 nested repository 是 submodule。
- linked task worktree 归属原 repository，不创建新的 shared RepositoryDeclaration；只创建 workspace binding。

## Non-Git Root

首版允许显式 `non_git` 或 `git_optional` root：

- 仍使用 `fs://<root_id>/<relative-path>`、权限、ResourceIntent/Lease、文件摘要和审计；
- 没有 commit OID、local anchor、publication、Git worktree driver 或 fast-forward/divergence 语义；
- 变更证据使用受预算的文件 manifest/hash、mtime/size 辅助信息和 Agent report，不能宣称 Git 可恢复；
- 写任务默认只能选择 shared 或用户/主 Agent预置的 external 环境，并如实标记 enforcement strength；
- lineage checkpoint 可引用其逻辑状态摘要，但默认不复制目录内容进 coordination repo。

## Clone 与激活

- 新 clone 自动绑定 coordination root/repository，并为其他 declarations 尝试安全的相对 hint；绝对/外部路径不会自动猜测。
- `required_on_activate=true` 的 root 未绑定或 identity 不匹配时，项目保持可诊断但不开放正常任务；optional root 只阻塞引用它的任务。
- 同一物理路径不能同时绑定到两个互不相关的 writable root identity；合法 parent/child root 重叠需要后续明确授权组合规则。
- 本机绑定不进入 Git checkpoint；共享 checkpoint 只保存 declarations、repository dependency DAG 和未绑定要求。

## 后续待细化

- root/repository declaration 与 binding 的最终字段、TOML/JSON Schema 和 lifecycle commands。
- Windows junction/symlink/case/UNC/volume file-ID 的规范化与 TOCTOU 防护。
- 合法 parent/child roots 的权限交集、最长匹配与资源租约冲突规则。
- non-Git root 的文件 manifest 预算、变更检测和结果提交 schema。
