# 项目初始化与首个 Git 锚点协议

> 核对日期：2026-09-17。
> 状态：第 157 题已确认选项 B；作为 D80 的初始化基线。锚点登记与无锚点操作门禁仍待后续决定。

## 冲突点

初始化必须同时建立 Git 共享层、本机 SQLite、replica identity 和用户级注册，但这些资源不存在共同事务。SQLite 的[原子提交](https://www.sqlite.org/atomiccommit.html)只覆盖数据库事务，不能把工作树文件和用户随后创建的 Git commit 一并纳入。

现有决策还规定调度中心不自动 `git add`、commit 或 push。因此必须明确：`.tsunagou` 已写入磁盘但尚未进入 Git `HEAD` 时，项目是否能签发 Agent 凭据并接受协作写入。

Git 提供了足够的激活验证原语：[git-ls-files](https://git-scm.com/docs/git-ls-files)可以确认文件是否在 index 中，[git-diff-index](https://git-scm.com/docs/git-diff-index)可以比较 `HEAD`、index 与工作树。实现应通过参数数组调用 Git，并结合 `ls-tree`/对象读取验证当前 `HEAD` 中的共享文件字节，而不是解析本地化的人类输出。

## 选项

| 选项 | 首次开放写入的时点 | 优点 | 风险与代价 |
|---|---|---|---|
| A | `project init` 后进入 `awaiting_anchor`；用户提交共享层，显式 `project activate` 验证当前 `HEAD` 后才允许 Agent/任务写入 | 第一条可写历史已有可复制锚点；初始化失败和 clone 恢复语义清楚 | 首次使用多一次用户 commit 和 activate；初始化参数必须能完整表达起始配置 |
| B（已确认） | 初始化文件落盘后立即 active，Git commit 可稍后完成 | 上手最快；可先协作再整理 commit | 初始任务、凭据和 checkpoint 可能只存在单机；系统必须明确显示尚无 Git 恢复锚点 |
| C | 调度中心自动 `git add` 并创建初始化 commit，然后立即 active | 操作步数最少；锚点自动存在 | 违反既定“不自动操作 Git 历史”；可能夹带 staged 文件、触发 hooks/signing 或改变用户分支 |

## 已确认方案 B：运行状态与 Git 持久性分离

初始化成功后，项目聚合立即为 `active`，并单独记录 `git_durability=unanchored`：

- 允许启动 worker、签发 Agent 凭据、创建/领取任务、投递消息、建立 lease、运行副作用 Operation 和生成 checkpoint；
- SQLite 是当前 replica/runtime 的事务权威，共享文件继续由 outbox/materialization 规则同步；
- `unanchored` 明确表示没有任何 checkpoint 被证明存在于 Git commit 中，删除此工作目录可能永久丢失协作状态；
- CLI 人类输出、JSON status、doctor 和未来 Web 工作台必须展示 durability 状态与最新 checkpoint，不能只显示 `active`；
- 系统不因未锚定自动执行 Git 操作，也不把工作树、index、remote URL 或“用户说已经提交”当作恢复证据。

genesis checkpoint 的 `git_anchor` 为空，不包含未来 commit hash，因此没有自引用。后续 anchor 是从 Git commit tree 指向已存在 checkpoint 的外部证据，先进入 SQLite；再由后续 checkpoint 物化该事实。

建议的独立 Git durability 状态为：

- `unanchored`：当前 lineage 从未建立有效 Git anchor；
- `current`：最新封存 checkpoint 已在已验证 commit 中；
- `lagging`：至少有一个有效 anchor，但本机最新 checkpoint 在它之后；
- `diverged`：检测到不能 fast-forward 的共享历史，按照既定规则停止写入；
- `unavailable`：暂时无法读取 Git 元数据，保留上次证据但不新增 anchor。

`active` 与上述状态是正交维度。`active + unanchored/lagging` 可以继续本机协作；`diverged` 仍受既定写入冻结规则约束。

## 可恢复初始化流程

### 预检

- 路径必须解析为 coordination repository 顶层，而非 linked task worktree、bare repo 或子目录。
- `.tsunagou` 不存在时才允许 new init；存在合法 manifest 时转入 `project register`，绝不覆盖。
- 存在无效或半完成目录时返回稳定诊断和 resume/abort 路径，不静默删除。
- 验证写权限、Git 版本/对象格式、路径规范化、大小写碰撞和 `.gitignore` 可更新性。
- 初始化参数必须包含项目显示名、coordination root，以及足以生成 shared roots/policy 上限的输入；秘密和本机绝对映射不进入共享层。

### 文件阶段

1. 生成 `init_operation_id` 和四层初始 identity。
2. 在 repository 根的同卷临时目录生成完整共享树、schema versions、genesis checkpoint 与原始字节 hash manifest。
3. fsync 必要文件后，将临时目录原子 rename 为 `.tsunagou`；目标一旦存在即停止。
4. 通过带 owner/version 标记的受管区块原子更新 `.gitignore`，只忽略 `.tsunagou/local/`、临时文件和秘密。
5. 创建 `local/replica.toml` 与 `state.sqlite3`，在数据库事务中写入 active project、`git_durability=unanchored`、genesis event、outbox 和初始 job。
6. 最后更新用户级项目注册并打开项目 worker；此前任一步崩溃都可由 manifest/operation marker 判定 resume 或 abort，不靠猜测。

多文件系统更新不能宣称绝对原子。正确性来自不可变 operation ID、逐阶段 marker、内容 hash、幂等重试，以及只有完整共享目录与可打开的 SQLite 同时验证后才对外注册项目。注册完成前没有可用项目凭据。

### Git anchor 验证

- anchor 证据必须是 commit object ID 与其中的 tree，不读取工作树文件来替代已提交内容。
- commit 中必须存在一个不可变 checkpoint manifest；manifest 的 project/lineage、schema、父 checkpoint、领域 revisions 和每个共享文件原始 hash 全部验证通过。
- `.tsunagou/local/`、秘密和临时文件不得出现在 commit tree；发现即拒绝 anchor 并报告泄漏风险。
- checkpoint 可以早于当前 SQLite 状态。验证后记录 `latest_anchored_checkpoint_id`；若本机已有后续 checkpoint，则 durability 为 `lagging`，不伪称 current。
- commit 可以不是当前 `HEAD`，但必须属于当前 coordination repository 且 checkpoint lineage 匹配。是否允许非 HEAD/不可达 commit 作为 anchor 留待锚点登记决策。
- 失败只拒绝该 anchor evidence，不回滚已完成的本机协作；返回逐项 machine-readable issue。

## 幂等与冲突

- 相同 `idempotency_key` 和相同初始化摘要重试，返回原 operation/project；同 key 不同摘要返回 idempotency conflict。
- `.tsunagou` 已是有效项目时，`init` 返回 `project_already_initialized` 和 register 指引，不生成新身份。
- project manifest 已落盘但 local DB 缺失时，可从 genesis 恢复同一 project/lineage，但生成新的 replica/runtime；旧未完成 replica 记入 bootstrap audit。
- `.gitignore` 受管区块被用户修改时停止更新并报告冲突；不替换文件其余内容。
- init abort 只存在于项目尚未成功注册、未签发任何凭据的 bootstrap 阶段。一旦 active，使用普通 archive/unregister/cleanup 规则，不能用 abort 抹除已发生的协作历史。

## 预期 CLI 结果

`project init` 的人类输出应给出当前状态与下一项明确动作；JSON 输出至少包含：

- `operation_id`、`project_id`、`lineage_id`、`replica_id`；
- `status: active` 与 `git_durability: unanchored`；
- `shared_paths` 与内容摘要；
- `recommended_action: create_git_anchor` 及当前 checkpoint ID；
- 明确的 durability warning code，供脚本和未来 Web UI 呈现。

锚点登记命令成功返回 commit、checkpoint、checkpoint hash 和新的 durability 状态；失败返回稳定 issue code，例如 `commit_missing`、`checkpoint_missing`、`checkpoint_hash_mismatch`、`local_path_tracked`、`identity_mismatch`、`lineage_mismatch`。

## 后续待细化

- `project.toml`、genesis checkpoint、bootstrap marker 与本机 registry 的完整字段表。
- 初始化命令如何采集多 root 映射和默认 policy；交互与非交互模式的边界。
- init resume/abort/cleanup 的 Operation 状态机与 Windows fsync/rename 故障注入。
- 锚点采用显式登记、写入冻结确认还是后台自动发现，以及 commit reachability 要求。
- `unanchored` 时哪些跨副本、历史切换或破坏性操作必须被门禁。
- 首次 anchor 后对外部 branch switch、reset 和共享层修改的监测策略。
