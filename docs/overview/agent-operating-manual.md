# Agent 操作手册：字段、拒绝与边界

**读者**：通过 MCP 桥接入的主 Agent（以及任何 worker）。本文件按小节查阅，不按顺序通读。
**位置**：`docs/overview/agent-operating-manual.md`（本机 checkout 下即 `<Tsunagou checkout>/docs/overview/agent-operating-manual.md`）。
**它回答什么**：某个工具**必填哪些字段**、每个**值从哪里来**、被拒之后**下一步做什么**，以及**为什么不能绕开桥**。
**它不回答什么**：每个区域有哪些命令 —— 那是[命令目录](../implementation/command-catalog.md)；CLI/HTTP 用法与示例 —— 那是[操作手册](cli-http-manual.md)。

> 本文件里的字段与拒绝码**逐条对过源码**：`src/tsunagou/application/handlers.py`、
> `src/tsunagou/application/workflows/**`、`src/tsunagou/modules/**` 是**事实源**；
> MCP 工具 schema（`protocol/schemas/commands/**` 生成物）**不是**。两者不一致时以 handlers 为准，
> 本文件在相应位置写明差异。**不要为了查这些事实去读 `src/`** —— 需要改的机制问题请按 §4 上报。

---

## 1. 能力索引：我要做什么 → 用哪个工具

| 我要做什么 | 用哪个工具 | 一句话 |
|---|---|---|
| 建一条任务（草稿） | `task__create` | `execution_scope` 必填；空 `{}` = 不认领任何路径 |
| 让草稿可发布 | `task__ready` | 只改状态，不通知任何人 |
| 把任务放进领取队列 | `task__publish` | **静默**：不发消息、不唤醒 |
| 改未开工任务的标题/目标/验收/契约依赖 | `task__update_plan` | 唯一改 `required_contract_ids` 的入口 |
| 加/去任务阻塞边 | `task__edge_add` / `task__edge_remove` | 只支持 `kind=blocks` |
| **计划并派活**（建/ready/publish/指派/发消息/替代） | `coordination__plan` | main 的默认路径；**默认发 `task.assigned` 并唤醒** |
| 现在谁在这个项目里（拿 `agent_id`） | `context__project_read` | `members[]` 是唯一权威名单 |
| 就接口达成一致 | `contract__propose` → `contract__accept` | `contract_id` 就是 `proposal_id` |
| main 代某个槽位接受契约 | `contract__accept_proxy` | 需要显式理由与代理策略 |
| 在任务上声明契约依赖 | `task__update_plan` 或 `coordination__plan` 行内 | 填**契约 id**，不是标签 |
| 登记根 / 绑定到本机路径 | `root__register` / `root__bind` | 先登记再绑定；路径必须已存在 |
| 登记根下面的 Git 仓库 | `repository__register` | 该根必须已 `bound` |
| 定工作区策略（文件任务的硬门槛） | `workspace__select` | 文件任务 begin 前必须有一次 |
| 从 worker 结果发起本地整合请求 | `workspace__integrate` | main 专属，**从不 push** |
| 开始干活（领活） | `task__begin` | 先读当前 revision；成功才拿到 scope 与 Attempt |
| 记录进展 / 挂起 / 交活 | `task__progress` / `task__block` / `task__submit` | 交活自动收结果、释放占用、通知 main |
| 声明这条活做不下去 | `task__fail` | 带 `reason`，释放占用 |
| 请求扩大范围 | `task__scope_request` → main `task__scope_resolve` | 只有当前 Attempt owner 能提 |
| main 回收孤儿/挂起 Attempt | `task__recover` | 带 `expected_attempt_id` 与 `disposition` |
| main 把一条指派收回自己做 | `coordination__takeover` | 会主动通知原 worker 停手 |
| 读收件箱 / 读一条消息 / 回执 / 记一次呈现 | `inbox__claim` / `inbox__fetch` / `inbox__ack` / `inbox__presented` | ACK ≠ 回应；`presented` 只记账 |
| 发消息 / 履行回应义务 | `message__send` / `message__respond` | 只有少数 kind 会唤醒（见 §2.7） |
| 查唤醒状态 / 宿主 / 显式补位唤醒 | `coordination__wake_status` / `__peer_hosts` / `__wake_candidates` / `__wake` | 操作细节见[唤醒指南](agent-wake-guide.md) |
| 提交认知报告 / 分歧 | `cognition__report` / `discrepancy__*` | 认知报告要带 `task_id` + `attempt_id` |
| 验收结果 | `task__review_accept` / `task__review_request_changes` | 要回引 `result_digest` 与 `slot_id` |
| 向用户要决定 / 提议完工 | `decision__propose` / `project__completion_propose` | 只有用户能 `resolve` / `confirm` |
| 查身份、能力、任务、契约版本、被拒清单 | `context__project_read` | 查多次要读 `since_revision` |

命名规律：MCP 工具名 = 命令名把 `.` 换成 `__`（`task.begin` → `task__begin`）。

---

### 1.1 第一次读就把这些拿到手（`context__project_read`）

**一次读取答完"开工前要知道的事"** —— 不必去读本项目的源码，也不必先被拒一次才知道该填什么：

| 你要的值 | 在哪读 | 说明 |
|---|---|---|
| 已登记根 + **物理身份** | `stable.roots.items[]` 的 `root_id` / `name` / `kind` / `status` / **`physical_identity`** | 它就是 `root.bind` 的 `expected_physical_identity` 要填的那个不透明串（`inode:<dev>:<ino>`）。路径**不存在**的根给 `unresolved:<os>:<normcase 绝对路径>` —— 那个形态**按设计含路径**，因为它是必须原样回填的值；`roots` 行里本身没有 `absolute_path` 字段 |
| 要不要 `repository.register` | `stable.repositories.exists` 与 `items[].repository_id` | `exists: false` 就是"还没登记仓库"，不用去试 |
| 能填进 `required_contract_ids` 的 id | `stable.contracts.accepted[].proposal_id` | **只列已接受的**（门只看 accepted 的契约）。照这里填，就不会再吃一次 `required_contract_not_accepted` |
| 目标确认了吗 | `stable.goal`：`status`（`unset` / `pending` / `resolved`）、`confirmed`、`objective_ref`、`objective` | `confirmed: false` 时不给 `objective` —— **占位句不是目标，别复述它** |
| 这个角色能用哪些工具 | 首次读另给 **`capability_index`**（区域 ／ 工具名 ／ 这个区域是干什么的；按角色过滤，worker 看不到 main 专属工具） | 这就是本手册 §1 那张表的**机器可读版**；只在首次读给一次 |

**差分语义**：`stable` 参与 revision 摘要 ⇒ 带 `since_revision` 且内容没变时只回 `{revision, unchanged}`（两个块都不重发），有变化则整份重发；`capability_index` **只在第一次读**（不带 `since_revision` 的那次）给。
两个块都**不含 token、也不含根的绝对路径**（除了上面那个 `unresolved:` 形态）。

## 2. 必填字段与取值来源

约定：**工具面** = 模型在 `tools/list` 上看到的手写 schema；**handler** = daemon 里真正读的字段。
两者不一致处逐条标注。凡是"值必须从别处取来"的字段，都在"取值来源"里写清怎么取。

### 2.1 `root__register` / `root__bind` / `repository__register`

> `expected_physical_identity` 的**正规来源**（三者同值，任取其一）：`root.register` 或 `root.bind` 返回值里的 `physical_identity`、
> 或**第一次 `context__project_read`** 的 `stable.roots.items[].physical_identity`（见 §1.1）。
> **不要**去读 `.tsunagou/local/bindings.json`（那是本机私有数据，项目规则明令不许给 Agent），
> 也**不必**为了这个值去读 Tsunagou 源码 —— 它的形态由实现决定，手册这里说的就是实现。

`root__register`（main 专属）

| 字段 | 工具面 | handler 是否读 | 取值来源 |
|---|---|---|---|
| `name` | 必填 | **读**（`_required_str`） | 你自己起的根名，项目内不得重复（重名报 `duplicate_root_name`） |
| `kind` | **必填** | 读，默认 `"directory"` | `"directory"` 或 `"repository"`；其他值报 `invalid_root_kind` |
| `binding_request` | 必填 | **读**：取其 `absolute_path` 或 `path` | `{"absolute_path": "E:\\path\\to\\dir"}`。缺 `binding_request` 报 `binding_request_required`；里面有对象但没路径报 `absolute_path_required` |
| `repository_id` | **必填（工具面）** | **handler 完全不读** | 字段级事实：`root_register` 只读 `name` / `kind` / `binding_request` / `required`；`repository_id` 被 schema 要求，却被 handler 忽略。仓库的确立走 `root__register` 之后单独调 `repository__register`。这里随 schema 传一个字符串即可，它不产生任何效果 —— 别指望它把根挂到某个仓库下 |
| `reason` | **必填（工具面）** | **不读** | 同上，只为通过 schema 校验 |
| `required` | **必填（工具面）** | 读，默认 `False` | 布尔；表示这个根是硬前提。`/roots` 查询会回显它 |

返回里必须**记下来**：`root_id`、`status`、`physical_identity`。
`root.register` 内部**自己就做了一次绑定**（`register_root` 末尾调 `bind_root`），所以正常的登记不需要再补一次 `root.bind`。路径不存在时不算失败：`status` 会是 `missing`（或该是目录却是文件的 `not_a_directory`），注册照常成功。

`root__bind`（main 专属）：把**已登记**的根绑到本机绝对路径，或换一个路径重绑。

| 字段 | 工具面 | handler | 取值来源 |
|---|---|---|---|
| `root_id` | 必填 | **读** | `root.register` 返回的 `root_id`；项目里没登记过的 id 会在域层以 `KeyError` 失败 |
| `absolute_path` | 必填 | **读** | 本机绝对路径。相对路径会被 `resolve()` 展开 |
| `expected_physical_identity` | **必填（工具面）** | 读，**传了才比** | 见下 |
| `reason` | **必填（工具面）** | **不读** | 只为过 schema |

**`expected_physical_identity` 是什么**：`modules/projects.py` 的 `physical_identity(path)` 返回一个**不暴露路径本身**的稳定串：

- 路径存在（`stat` 成功）→ `inode:<st_dev>:<st_ino>`（例如 `inode:2439577173:16888498603141428`）。
- 路径不存在 → `unresolved:<小写系统名>:<normcase 后的绝对路径>`。

它**不是**哈希、不是你自己能算出来的东西，也**不是路径**。handler 用它做一次比对：
`expected_identity is not None and str(expected) != actual` → `physical_identity_conflict`。
换句话说，**不传 = 不校验**（照绑，`status` 由路径是否真实存在决定）。

**怎么取它**：只有一处正规来源 —— **写路径的返回值**。

1. 调 `root__register`，从返回里读 `physical_identity`；或
2. 调一次 `root__bind`（不带 `expected_physical_identity`），返回里就有 `physical_identity`。

把那个字符串原样存下来；下次要"确认还是同一个目录/同一块盘"时，把它填进 `expected_physical_identity`。
**不要**去读 `.tsunagou/local/bindings.json` 或别的本机私有文件拿它（见 §4）。
**也不要**自己拼 `inode:...`：`st_ino` 是文件系统给的，换个机器/换个挂载点就不同，手拼的值只会换来一句 `physical_identity_conflict`。

`root_binding_required` / `unknown_root_id:*` 的语义：

- `unknown_root_id:<root_id>`：出现在**建任务/发计划的当场**（`task.create` 与 `coordination.plan` 的 handler 会校验 `execution_scope` 里每个 `root_id` 是否在项目 `roots` 里），是"你引用了没登记过的根"。先 `root.register`，再引用。
- `root_binding_required`：由 `repository.register` 抛出，详情里带 `root_id`、`registered`（这个根到底登记过没有）和 `next`。**根登记了但没绑**时就是这个码；先 `root.bind`，再登记仓库。

`repository__register`：必填 `name` + `root_id`（`required` 在工具面上也是必填，handler 不读）。返回 `repository_id` —— 这才是 `workspace.select` 的 `repository_id` 要用的值，也是 `workspace.integrate` 的 `target_repository_id`。它的物理身份由**该根当前的绑定路径**算出，所以顺序是：`root.register` → （必要时 `root.bind`）→ `repository.register`。

### 2.2 `task__create` / `task__ready` / `task__publish` / `task__update_plan`

`task__create`（main 专属）

| 字段 | 工具面 | handler | 取值来源 / 语义 |
|---|---|---|---|
| `title` | 必填 | **读**（`title_required`） | 短标题 |
| `objective` | 必填 | **读**（`objective_required`） | 这条活要达成什么 |
| `execution_scope` | 必填 | 读 | `{"roots":[root_id,...]}` 或 `{"resources":[{kind:"path",root_id,segments,mode}]}`。**空 `{}` = 这个任务不做文件改动**：不准备工作区、不占租约、worker 改的文件不进结果。文件任务必须给出 paths/roots |
| `requires_files` | 可选 | 读 | `true` 且 scope 为空 → `file_task_requires_scope`（建任务当场拒，也防住 `task.publish`） |
| `required_contract_ids` | 可选 | 读 | **契约 id 清单**（见 §2.5）。重复项或空串报 `invalid_required_contract_ids` |
| `blocks` / `parent_task_id` | 可选 | 读 | 阻塞依赖 / 父任务 |

`task__ready` / `task__publish`：`task_id` 必填（`reason` 可选）。工具面 schema 与生成的命令 schema
现在是**同一个字段集**（2026-10-10 起由 `tools/codegen/generate_protocol.py` 强制、并由
`tests/protocol/test_command_surface_contract.py` 钉住）；在那之前两边不一致，照 schema 写会被拒。
`publish` 的机械门槛是 `ready`：状态不合法报 `invalid_transition:<现在>->open`；顺序是 `draft` →（`ready`）→ `open`。声明了 `requires_files` 却仍空着 scope 的任务**不许发布**（`file_task_requires_scope`）。

> **`task.publish` 不通知任何人。** 它只把任务放进领取队列：不发消息、不唤醒宿主。没人动就什么都不会发生，也不会有东西来提醒你。要有人真的开工，用 `coordination.plan`（默认给每行发一条 `task.assigned` 并唤醒指名的 worker），或另行 `message.send`。

`task__update_plan`：`task_id` 必填，其余（`title`、`objective`、`required_contract_ids`、`acceptance`）给了才改。这是**唯一**改已有任务契约依赖的入口（改范围另走 `task.scope.request`）。任务已经有人领活时改不动（`task_plan_not_editable`）。

### 2.3 `coordination__plan`（main 专属，最常用的派活路径）

顶层必填：`objective`（非空字符串）、`assignments`（非空数组）。可选 `auto_wake`（默认 `true`，非布尔报 `auto_wake_boolean_required`）。

**每一行（row）真正必填的字段** —— 工具面 schema（`coordination/plan.schema.json` 的 `items.properties`）与 handler 现在声明同一组：

| 行内字段 | 工具面 | handler | 说明 |
|---|---|---|---|
| `assigned_worker_id` | **未声明** | **必读**（`assigned_worker_id_required`） | 必须是本项目 **active** 的 agent，且不能是 main 自己（否则 `worker_not_member`）。取值来源：`context__project_read` 的 `members[]`（那里有 `agent_id`、`role`、`status`、`session_status`） |
| `title` | **未声明** | **必读**（`title_required`） | 任务标题 |
| `task_objective` | **未声明** | **必读**（`task_objective_required`） | 注意字段名是 `task_objective`，**不是** `objective`（顶层那个 `objective` 是计划的目标，两者不同） |
| `acceptance` | 必填 | **必读**（`acceptance_required`） | 验收怎么判：一条命令加预期输出，或确切步骤与结果。**必须能被人照着核**，这是本行唯一被 schema 承认的必填字段 |
| `execution_scope` | 未声明 | 读，默认 `{}` | 文件任务必须给 paths/roots，否则等于"不做文件改动"。行内给的 `root_id` 会**当场**校验（与 `task.create` 同一套实现）：没登记过报 `unknown_root_id:<id>`，详情带 `registered_root_ids`（本项目现有根）与 `next` —— 计划这一层就拒，不留到 begin |
| `required_contract_ids` | 未声明 | 读 | 契约 id 清单（见 §2.5）。**这一条不会拒**（先计划、再让槽位接受是设计内的顺序），但没结清的契约会写进那一行的 `contracts_pending[]` 与返回的 `next`："这些任务现在还领不了活" + 本项目现有的契约 id 清单 |
| `cross_module` | 可选 | 读 | `true` 且同一行没有 `required_contract_ids` → `cross_module_contract_required`（拒绝，不是警告） |
| `dependencies` | 未声明 | 读 | 阻塞依赖的 task_id 清单；不存在的 id 报 `dependency_task_not_found` |
| `parent_task_id` | 未声明 | 读 | 父任务 |
| `supersedes_task_id` | 可选 | 读 | 替代一条已发布的任务 |
| `workspace` | 未声明 | 读 | 一个 `workspace.select` 的 payload（不含 `task_id`，会补上）；给了就先为这条新任务定工作区策略 |

**一行到底做了什么**（`handlers.py` 的 `coordination_plan`，按顺序）：

1. `tasks.create_task(row.title, row.task_objective, ..., execution_scope=row.execution_scope or {}, required_contract_ids=..., acceptance=row.acceptance, cross_module=row.cross_module)` —— 建任务，状态 `draft`；
2. 行里有 `workspace` → 立刻为这条任务调 `workspace.select`；
3. `tasks.ready(task_id)` —— 变 `ready`；
4. `tasks.publish(task_id)` —— 变 `open`，进领取队列；
5. 行里有 `supersedes_task_id` → `tasks.supersede(旧任务, superseded_by_task_id=新任务)` —— 旧任务记下承接关系并**退出领取队列**（不终端、不改名）；
6. 整批进 `coordination.create_plan(...)` 成为一条 plan，再为每个 assignment 建一条消息；`auto_wake` 为真时发 `kind="task.assigned"`、`summary="有任务可领"`、`subject_ref="task/<task_id>"` —— **`task.assigned` 会唤醒对方宿主**。

返回：`plan_id`、`objective`、`assignments[]`（每项含 `assignment_id`、`task_id`、`assigned_worker_id`、`status`、`message_id`、`acceptance`、`cross_module`、`superseded_task_id`、`contracts_pending`）、`coverage`，以及 `next`（自指契约、替代关系、没结清的契约都在这里说）。**`message_id` 要留着**：唤醒状态就是按它查的。

**计划期就校验的那两件事**（2026-10-10 起）：① `execution_scope` 里的 `root_id` 必须已登记 ——
悬空引用在**计划**这一层就拒（`unknown_root_id`，并列出可用的 root_id），不再等到 `task.begin`
才暴露：那时任务已经建好、派出去、有人认领了，等于让人白跑一趟；② 契约没结清**不拒**，但在
那一行的 `contracts_pending[]` 与 `next` 里说清，并列出本项目现有的契约 id ——
2026-10-08 实测里 main 填了一个自己起的标签，计划照常成功，到 begin 连拒 4 次、最后三个任务被取消重建。

要让 coordinator 静默建任务（不唤醒任何人），传 `auto_wake: false`；要替换已发布的任务，就在**新行**上给 `supersedes_task_id`，不要先 `task.cancel_request` 再新建（两步会让旧任务在看板上永远算"没做完"）。

**顺序：先把计划发出去，再写脚手架。** 2026-10-08 实测里 main 先花约 **40 秒**写 `package.json` / `tsconfig` / `SPEC` 才 `coordination.plan`，而那几个 worker 这段时间**只能空等**（计划没下达，它们没有任务可领）。计划一经下达（`auto_wake` 默认会给每行发 `task.assigned` 并唤醒宿主），worker 就能开工；main 的脚手架完全可以**与 worker 并行**做，或者索性写成一条任务交给 worker。
**唯一不能为省时间而砍掉的**：每一行自己必须带齐 `execution_scope`（碰文件时）与需要时的 `required_contract_ids` —— 否则 worker 领了活也在 `task.begin` 上开不了工，"先发计划"反而变成"先制造一次拒绝"。

**要确认某个 `agent_id` 有效，读 `members`，不要拿提案去试。** `contract.propose` 会**真的**建一份提案（别人可能按 digest 接受，或者你得撤回它），所以用它"探一下 slot 解析"是**有副作用的探测** —— 实测里那一次就留下一条 `contract.propose` + 一条 `contract.withdraw`。要看本项目有哪些 Agent、谁是 main，读 `context__project_read` 的 `members`（宿主层面的事实用 `coordination__peer_hosts`）。真填错了也不贵：`coordination.plan` 会当场用 `worker_not_member` 拒（行里的 `assigned_worker_id` 必须是本项目 **active** 成员且不能是 main 自己），比一次提案便宜得多。

### 2.4 `workspace__select`（main 专属）

什么时候**必须**有它：任务**碰文件**（`execution_scope` 里有 `kind="path"` 的资源，或 `{"roots":[...]}` 这种整体形态）时，`task.begin` 会在 `prepare_begin` 里要求存在一条该任务的策略决定 —— 没有，或决定的 `scope_revision` 与任务当前不符，报 `main_workspace_selection_required`。

| 字段 | 必填 | 说明 |
|---|---|---|
| `task_id` | 必填 | 目标任务 |
| `driver_kind` | 必填 | `shared` / `worktree` / `external`，三选一 |
| `root_binding_refs` | 视策略 | 该任务实际用到的根 id 集合。与任务 scope 解析出的根不一致 → `workspace_policy_roots_mismatch` |
| `repository_id` | `worktree` 需要 | `repository.register` 的返回值；`worktree` 只允许**单个**仓库根，否则 `main_worktree_preparation_required` |
| `external_locator` | `external` 需要 | 外部工作区的位置；缺 → `main_external_preparation_required`（在 begin 时） |
| `hard_constraints` | 可选 | 能力要求集合；`driver_kind` 不满足时报 `driver_does_not_meet_hard_constraints` |
| `reason` / `evidence_refs` | 可选 | 记进决定快照 |

三种 driver 的**能力**（`modules/workspaces.py` 的 `drivers`）：

| driver | 能力 | 含义 |
|---|---|---|
| `shared` | `multi_root`、`dirty_baseline`、`original_directory` | 就在原目录上干；允许多根、允许基线是脏的。最省事，隔离最弱 |
| `worktree` | `single_repository`、`clean_baseline` | Git worktree 隔离：必须**单仓库**、基线必须**干净**（`worktree_baseline_not_clean`），由 main 先准备好物理路径 |
| `external` | `externally_prepared`、`multi_root` | 工作区在 Tsunagou 之外准备好（含远端自己那份副本）。主机**不扫**它：没有基线、没有清单，只有"那台机器自报" |

选择时机：任务必须**停着**（`draft`/`ready`/`open`/`blocked`/`changes_requested`）；已 `claimed`/`running`/`submitted`/`completed` 等状态报 `workspace_selection_requires_stopped_task`。任务 scope 变了（`scope_revision` 前进）之后要**重新选一次**，否则 begin 报 `main_workspace_selection_required` 或 `workspace_policy_changed_reclaim_required`。

**交付根没有 git 时怎么办**：`worktree` 直接不可用（它要仓库、要 HEAD、要干净状态），硬约束里带 `single_repository`/`clean_baseline` 会让它在候选里消失。这时用 `shared`（多根、脏基线都允许）—— 这也是默认该选的：`shared` 不要求 `repository_id`，不需要 CI 之外的任何 git 事实。`external` 只在文件真的在别处（远端已声明副本）时用。**不要**因为"想要隔离"就硬填 `worktree`：它会在 `main_worktree_preparation_required` 或 `worktree_baseline_not_clean` 上停住。

### 2.5 `contract__propose` / `contract__accept` / `task.update_plan`：契约的门到底看什么

| 事实 | 说明 |
|---|---|
| 要填的 id 从哪来 | **第一次 `context__project_read`** 的 `stable.contracts.accepted[].proposal_id`（见 §1.1）；或 `contract.propose` 返回值里的 `proposal_id` / `contract_id`（同一个值） |
| `contract_id` 就是 id | 调用方给的 `contract_id`（非空、无控制字符、≤128 字符）在未被占用时**成为该提案的 `proposal_id`**；已被占用报 `contract_id_taken`。省略则由系统发 UUID。返回值同时回显 `proposal_id` 与 `contract_id` —— **同一个值**，回引它 |
| `required_contract_ids` 填的是**这个 id** | `task.begin` 按 id 在契约库里查。填一个自己起的语义标签（例如 `library-api-v1`）永远查不到，会得到 `required_contract_not_accepted:<你填的值>`，详情里带 `task_id`、`status: "missing"` 和 `existing_contract_ids`（本项目现有契约 id 清单）—— 照着改用其中一个即可 |
| 语义名只是 `subject_ref` | 契约提案上的 `subject_ref` / `contract_kind` / `input_refs` 都是**描述性**的，不参与查找 |
| **接口文本可以是一份文档，门只看契约对象** | 这是两回事，**不是竞争关系**：接口的**文字**完全可以写在 `docs/API.md` 这样的文件里（把它列进契约的 `input_refs`，让人读得到），但**闸门只看契约对象本身**。任务必须在 `required_contract_ids` 里写**那个对象的 id** —— 一份"冻结文档"不会自动成为契约：没有 `contract.propose` 就没有契约，`task.begin` 就会拒。别得出"文档已经冻结，等于契约已经谈妥"这个结论 |
| 门只在任务**声明了依赖**时触发 | 没写 `required_contract_ids` 的任务不会被契约拦（`_require_contract_alignment` 对无契约的任务直接放行）。所以"我声明了依赖"才是让系统替你检查的前提 |
| 门在两处 | `task.begin`（能不能开工）与 `task.submit`（能不能交活）问的是同一个问题，所以"能开工"和"能交活"不会各说一套。契约没人接受 / 还有在谈的修订 → `contract_not_accepted`；你**声明读过**的版本与在册版本不符 → `contract_revision_conflict`（这条拒绝不关任何东西：Attempt、租约、文件都还在，读完当前版本、把活对齐后再交一次即可） |
| 自指形状会当场说出来 | 任务要求的契约里有一个槽位归**这个任务的执行者**自己时，`coordination.plan` 的 `next` 会点出来（否则它领活时等契约 accepted，而契约等它接受），main 可以用 `contract.accept_proxy` 代接受 |
| `cross_module` 没有契约 = 拒绝 | 行里声明 `cross_module: true` 却没有 `required_contract_ids` → `cross_module_contract_required`。理由：最贵的语义冲突（读者端调 `/requests`，后端只服务 `/api/applications`）**不重叠任何文件**，只靠文件重叠强制契约拦不住 |
| `contract__accept` 必填 | `proposal_id`、`participant_slot`、`proposal_digest`。`proposal_digest` 必须是**你读到的那一版的 digest** —— 只接受 digest 不回引是不行的；`contract.reject` 同理（`proposal_id`、`proposal_digest`、`reason`） |
| 想确认某个 `agent_id` 有效：**看 `members`，不要用提案探测** | 提案是有副作用的对象（见 §2.3 末段）：别人可能按 digest 接受它，或者你得撤回。填错的代价本来很小 —— `coordination.plan` 会当场用 `worker_not_member` 拒 |

### 2.6 任务执行面：`task__begin` / `submit` / `block` / `progress` / `fail` / `recover` / `scope_request`

| 工具 | 必须产生的字段 | handler 还会看 / 语义 |
|---|---|---|
| `task__begin` | `task_id`、`expected_task_revision`（整数；不是整数报 `expected_task_revision_required`） | revision 不符报 `task_revision_conflict`；任务状态不是 `open`/`blocked`（且不是自己 running 的 Attempt）报 `task_not_beginable`；依赖没完成报 `task_dependency_pending:<id>`；有未决用户决定报 `user_decision_pending:<decision_id>`。**成功**才返回 `attempt_id`、`execution_scope`、`workspace_id`、`reservation_id` |
| `task__submit` | `task_id`、`attempt_id`、`summary` | 可选 `evidence_refs`、`artifact_refs`、`validation_metadata`（其中只有 `command` 与 `exit_code` 必填；时间戳、`tool`、`tool_version`、`workspace_digest`、输出 digest **给了就校验**，缺字段的拒绝会点名 `missing`）。Attempt 不是自己的/不是 running 报 `attempt_owner_required`、`attempt_not_running`。交活会自动收工作区结果、释放占用、给 main 发 `task.submitted`（带 `result_id` + `result_digest` + 一份**证据摘要**） |
| `task__get` | `task_id` | 读**一条**任务的现状：`status`/`revision`/`acceptance`/`execution_scope`/`required_contract_ids`（以及还没被接受的 `contracts_pending`）/当前 `attempt`/最近一次 `latest_result`，还有 `next`（现在最该做的一件事）。只想知道一条任务时用它，别用 `context__project_read`（那条会返回全部 assignment，随任务数增长） |
| `task__result_get` | `task_id`（`result_id` 可选，缺省取最近一次） | 读一次交付的**可重放证据**：`validation_metadata`（每条 `command`+`exit_code`…）、`changed_paths`/`untracked_summary`、`scope_paths` 与 **`scope_violations`**（声明范围之外的改动）、`environment_digest`/`environment_files`（依赖清单指纹，用来回答"环境被动过没有"）、`patch_artifact_ref`、`evidence_level`。验收前读它，不要自己重跑一遍 |
| `task__block` | `task_id`、`attempt_id`（工具面必填）；`reason_code` 或 `reason` 至少一个 | 先验证 Attempt 归自己（`attempt_owner_required`）；状态不是 `claimed`/`running`/`cancel_requested` 报 `attempt_not_running`。挂起会释放占用 |
| `task__progress` | `task_id`、`attempt_id` | `summary`、`evidence_refs` 可选。是执行命令，需要 `task.execute` 权限 |
| `task__fail` | `task_id`、`attempt_id`、`reason` | Attempt 归自己；终态 Attempt 报 `attempt_not_failible` |
| `task__recover`（main） | `task_id`、`expected_attempt_id`、`disposition` | `disposition` 不合法报 `invalid_recovery_disposition`；Attempt 对不上报 `attempt_id_mismatch` |
| `task__scope_request` | `task_id`、`attempt_id`、`requested_scope`、`reason` | 只有当前 Attempt owner 能提（否则 `attempt_owner_required`）；带了 `expected_revisions` 且不符报 `task_revision_conflict` / `scope_revision_conflict`。返回 `scope_request_id`，等 main 批 |
| `task__scope_resolve`（main） | `scope_request_id`、`choice`（`approve`/`reject`） | 批准时用 `approved_scope`；其他 choice 报 `invalid_scope_choice` |
| `coordination__takeover`（main） | `assignment_id`、`takeover_reason` | 任务已在终态报 `task_not_recoverable`；会 recover 掉原 Attempt 并主动给原 worker 发 `task.taken_over`（接管拦得住对方的命令，拦不住对方的文件写入） |

### 2.7 `inbox.*` 与 `message.*`：只列你必须产出的字段

| 工具 | 必填 | 可选 / 语义 |
|---|---|---|
| `inbox__claim` | 无（`limit` 可选，默认 50） | 领取自己收件箱的**摘要**；正文要 `inbox__fetch`。`unread: true` 只给**没展示过**的那些（已经 `inbox__presented` 过的不会再吐回来；不传就是老的默认行为） |
| `inbox__fetch` | `message_id` | 只有收件人是自己才行（否则 `inbox_access_denied`）；返回全文、`in_reply_to` 和 `response_obligations[]` |
| `inbox__presented` | `message_id` | `evidence_kind`、`evidence_digest` 可选。只记"我呈现过"，**不核证据强度** |
| `inbox__ack` | `message_id` | `reason` 可选。**幂等**：重复 ACK 成功（不必重新 claim）；**ACK 不履行回应义务** —— 有 `response_obligations` 时要另发一条回复并 `message__respond` |
| `message__send` | `recipient_agent_id`、`summary` | `kind`（默认 `message`）、`subject_ref`、`payload`、`priority`、`in_reply_to`、`response_contract`、**`wake`**。回复时把收到的 `message_id` 填进 `in_reply_to`。**要它立刻动就带 `wake: true`**（普通消息默认不唤醒；见下）。返回的 `next` 会直说这条会不会唤醒对方 |
| `message__respond` | `obligation_id`、`response_message_id` | 用**已经发出去的那条回复**的 `message_id` 来履行义务 |

**哪些消息会唤醒对方**（决定"我发了它会不会动"）：唤醒白名单是 `task.assigned`、`task.submitted`、`task.reviewed`、`task.taken_over`、`task.refused`、`contract.proposed`、`contract.revised`、`user_decision.resolved`、`discrepancy.arbitration_requested`、`coordination.stalled`、`coordination.waiting`、`task.resume`（`modules/messaging.py` 的 `WAKE_WORTHY_KINDS`）；**其他 kind 默认不唤醒**。但你有两条路让它立刻动：**①发送时带 `wake: true`**（2026-10-10 起，任何 kind 都可以）②带 `response_contract.required=true`，它会出现在 `coordination__wake_candidates` 里，可以对它显式 `coordination__wake`。`message__send` 的返回 `next` 会直说这条属于哪一种，并且**在你还没发的时候就告诉你下次该怎么发**。细节见[唤醒指南](agent-wake-guide.md)。

### 2.8 其余零星工具（都在桥的工具面上，别靠猜）

| 工具 | 必填 | 语义 |
|---|---|---|
| `task__cancel_ack` | `task_id`、`attempt_id`、`reason` | 收到 `task.cancel_request` 后**停手并确认**；`stop_evidence` 可选。它释放资源、撤销执行授权 |
| `task__self_accept` | `task_id`、`result_id`、`result_digest` | 任务策略允许时自己验收（`reason`、`evidence_refs` 可选）。能不能自验收由任务策略说，不是你自己决定 |
| `discrepancy__create` | `subject_ref`、`report_refs`、`severity`、`summary` | 从既有认知报告里挑出**互相矛盾**的地方，做成一条可见的分歧 |
| `discrepancy__advance` | `discrepancy_id`、`status` | 把分歧推进到澄清/协商阶段 |
| `discrepancy__resolve` | `discrepancy_id`、`kind` | 按共识/驳回/显式覆盖结清分歧（main 权威） |
| `durability__reconcile` | `reason` | 项目完工后重试失败的 checkpoint 物化（main 权威）；`scope_refs` 可选 |
| `project__configure` | `policy_patch`、`reason` | 开/关项目级自动唤醒（`policy_patch.auto_wake_multi_agent`，未配置时视为开启）。**它同时管空闲看门狗**（§6.1） |

---

## 3. 常见拒绝 → 下一步

拒绝**不改变任何状态**（命令自身事务回滚）。**可归因**的拒绝会留一行 `command.<kind>.denied`
（带 `code` 与 `task_id`），main 每回合的 `context__project_read` 会把它聚合成 `coordination.denied`；
同一个任务被同一个 code 拒到第二次时，任务会被标出（`block_reason = refused:<code>`）并且
**main 会收到一条 `task.refused` 消息** —— 照现在这样重试只会再被拒一次。

| code | 什么时候出现 | 下一步 |
|---|---|---|
| `physical_identity_conflict` | `root.bind` 传的 `expected_physical_identity` 与 `physical_identity(absolute_path)` 算出来的不同（`handlers.py:483-484`） | 你手上的值是**别人/别的路径**的。不带 `expected_physical_identity` 重调一次 `root.bind`，把返回里的 `physical_identity` 存下来；要用它做校验就原样回填 |
| `root_binding_required` | `repository.register` 时该根没有有效绑定（详情含 `root_id`、`registered`、`next`）（`handlers.py:507`） | 看 `registered`：`false` → 先 `root.register`；`true` → 先 `root.bind` 到本机绝对路径，再登记仓库 |
| `unknown_root_id:<id>` | `task.create` **或** `coordination.plan` 的 `execution_scope` 引用了项目里**没登记**的根（详情含 `root_id`、`registered_root_ids`、`next`） | 用 `root.register` 登记这个根，或改用 `registered_root_ids` 里的某一个。别指望它"以后就好了"：悬空引用以前会被静默存下，现在**计划这一层**就拒（2026-10-10 起与 `task.create` 同一套校验） |
| `required_contract_not_accepted:<你填的值>` | `task.begin` 时任务声明的契约不存在或未被接受（`task_execution.py:105-110`） | 看详情：`status: "missing"` → 你填的是标签而不是 id，照 `existing_contract_ids` 改用真 id（或先 `contract.propose`）；有 status → 等槽位被接受，或由 main `contract.accept_proxy` 代接受 |
| `contract_not_accepted` | `task.begin` / `task.submit` 时任务依赖的契约未结清或还有在谈的修订（`execution_commands.py:76,315`） | 读当前版本、接受或驳回；不一致就升级给 main。这条不关任何东西 |
| `contract_revision_conflict` | 你声明的契约版本与在册版本不符（`execution_commands.py:100-103`） | 调 `context__project_read` 读回在册版本，让工作对齐当前版本后再交。Attempt 与文件都还在 |
| `contract_id_taken` | `contract.propose` 给的 `contract_id` 已被占用（`handlers.py:1233`、`cognition.py:339`） | 换一个 id，或对既有契约发 `supersedes_id`（替代提案不必自己命名） |
| `contract_id_taken_by_superseded_contract` | 用**被替代者**的 id 命名替代者（`handlers.py:1231`） | 替代提案不要自己起名：承继关系由 `supersedes` 链说明 |
| `cross_module_contract_required` | `coordination.plan` 某行 `cross_module: true` 但没给 `required_contract_ids`（`handlers.py:1407`） | 同一行补上契约 id；先谈接口再开工 |
| `file_task_requires_scope` | `task.create`/`task.publish` 时声明 `requires_files` 却空着 `execution_scope`（`handlers.py:616,653`） | 在 `execution_scope` 里给出 paths 或 roots。`task__update_plan` **不接受** scope 参数，所以给已有任务补范围要走 `task.scope.request` → main `task.scope.resolve`（批准会改 `execution_scope` 并抬 `scope_revision`；已有工作区决定必须**重选**一次，否则 begin 报 `main_workspace_selection_required`） |
| `worker_not_member` | `coordination.plan` 行的 `assigned_worker_id` 不存在、不是 active，或者是 main 自己（`handlers.py:1377`） | 用 `context__project_read` 的 `members[]` 取一个真实 `agent_id`。新 worker 入席是**用户**的决定 |
| `task_not_beginable` | 任务状态不是 `open`/`blocked`，且当前 Attempt 不是自己 running 的（`task_execution.py:98`） | 看任务状态：`draft` 或 `changes_requested` → **一次** `task.publish` 就够（它已隐含 ready，2026-10-10 起）；`submitted` → 等验收；`completed`/`cancelled` → 换一条 |
| `attempt_owner_required` | 用别人的 / 已结束的 Attempt 发进度、挂起、交活、失败（`handlers.py:713,778`；`task_execution.py:96,135`；`tasks.py` 多处） | 只在自己的 Attempt 上操作；要接着干就重新 `task.begin` 拿新 Attempt |
| `task_revision_conflict` | `task.begin` 的 `expected_task_revision` 不是当前 revision（`task_execution.py:92`） | 重读任务当前 revision（`context__project_read`）再 begin。别猜 |
| `main_workspace_selection_required` | 文件任务 begin 时没有该任务的策略决定，或决定的 `scope_revision` 落后（`execution_commands.py:216`） | `workspace.select` 一次（`shared` 最省事）；scope 改了要重选 |
| `workspace_policy_roots_mismatch` | 策略的 `root_binding_refs` 与任务 scope 解析出的根不一致（`execution_commands.py:219`） | 重选一次，`root_binding_refs` 照任务 scope 里的 root_id 填 |
| `workspace_selection_requires_stopped_task` | 任务已在 `claimed`/`running`/`submitted` 等状态时选工作区（`execution_commands.py:378`） | 先 `task.block` 让占用手停手，或等它结束；再选 |
| `main_worktree_preparation_required` / `main_external_preparation_required` | `worktree` 不是单仓库根或缺 `repository_id`；`external` 缺 `external_locator`（`execution_commands.py:220-223`） | 补齐 `repository_id` / `external_locator`，或改用 `shared`。**根没有 git 时 `worktree` 用不了** |
| `worktree_baseline_not_clean` | `worktree` 决定下基线是脏的（`workspaces.py:429`） | 先清干净（commit 或 stash），或改用 `shared` |
| `workspace_policy_changed_reclaim_required` | 任务 scope 变了，已有 workspace 与当前决定/scope 对不上（`execution_commands.py:228`） | 重选工作区策略，让 `scope_revision` 对齐 |
| `driver_does_not_meet_hard_constraints` | `driver_kind` 不满足 `hard_constraints`（`workspaces.py:365`） | 放宽硬约束或换 driver；`worktree` 只满足 `single_repository`+`clean_baseline` |
| `task_plan_not_editable` | 对已被人领活/非可编辑状态的任务 `task.update_plan`（`tasks.py:193`） | 等它停下，或另建任务并在 `coordination.plan` 里用 `supersedes_task_id` |
| `invalid_transition:<现在>-><目标>` | `task.ready`/`task.publish` 顺序不对（`tasks.py:700`） | `draft` → ready → `open`。`changes_requested` 也走 ready |
| `capability_denied` | 当前角色/会话没有这个能力（`handlers.py:298`） | 交给 main 或用户；worker 看不到 main 专属工具是**故意**的（注册表 principal=M），不是缺功能 |
| `unknown_payload_field` | payload 顶层带了该命令不接受的键（`runtime.py:244`，按 `PAYLOAD_FIELDS` 判） | 按工具 schema 重发。工具 schema、命令目录与 `PAYLOAD_FIELDS` 现在是**同一个字段集**（2026-10-10 起有契约测试钉住）—— 若三者仍不一致，那是缺陷，按 §4 上报，不要绕 |
| `project_objective_not_confirmed` | `project.completion.propose.main` / `project.completion.confirm` 时项目**没有**一条已 resolved 的 `kind=project.objective` 用户决定（详情含 `objective_ref`、`next`） | 先与用户把目标谈清楚，用 `user_decision.propose`（`kind=project.objective`、`proposal_ref=<你会复用的引用>`）提出来，等用户确认，再用**同一个引用**提完工。记录里那句 `objective` 在确认前只是占位符，不是目标 |
| `project_objective_ref_mismatch` | 完工提案引用的 `objective_ref` 与已确认目标的 `subject_ref` 不一致（详情含 `confirmed_objective_ref`） | 把 `objective_ref` 改成 `confirmed_objective_ref` —— 它同时就是 `context__project_read` 的 `stable.goal.objective_ref`；或者先与用户谈一个新的目标 |
| `daemon_unreachable` | 桥连不上主机（远端最常见） | 这次调用**没发生**，什么都没变：通道恢复后重试一次。别改走别的路 |

---

## 4. 边界：不要绕开桥

**不要**手写 HTTP 直接打 daemon，**不要**去找或使用 control token、ticket、会话 bearer。具体地说，以下都不属于 Agent 的工作面：

- 对 `/api/v1/commands/**` 手搓请求（含"因为工具 schema 看起来不对，所以自己拼一个"这条理由）；
- 去读 `.tsunagou/local/endpoint.json`、`.tsunagou/local/bindings.json`、`~/.tsunagou/console-enrollments/enrollments.json`、`.tsunagou/local/**`、任何 `*.token` / SQLite / 日志；
- 拆包宿主安装目录（例如 `app.asar`）去找 Tsunagou 的文档或端点；
- 自己签发、复制或粘贴票据与断言一个身份。

**为什么**（不是仪式，是机制）：

1. **身份**只有一个来源：桥把会话凭据放在传输层里（不进任何命令 payload、不进提示词），daemon 按 bearer + session + connection epoch 判定主体。绕过桥 = 没有可信主体，daemon 只会报认证失败；能"成功"的那种绕法，等于在用一个不属于你的身份。
2. **范围与版本**在桥这一侧才闭合：`task.begin` 交回来的 Attempt、`execution_scope`、`scope_revision`、租约与工作区都挂在这次认证调用上；`expected_revisions` 里"你读过哪一版契约"也是桥按本会话真实读过的内容自动填的（`declareContracts`）。绕过去就没有这些。
3. **审计与拒绝账**：每次结构化拒绝都会落 `command.<kind>.denied`，main 的 `context__project_read` 会把它聚合成 `coordination.denied`。绕开桥的动作**不进这条账** —— 出了事没人能看见，你自己也拿不到"下一步做什么"。
4. 本机私有数据（control token、ticket、bridge session、SQLite、日志）是**用户和本机**的，不是 Agent 的输入。用户明确规定的边界不因为宿主是 Full Access 而变小：Full Access 不等于 Tsunagou scope。

**工具的形状看着不对时怎么办**（而不是绕）：

1. 先读拒绝里的 `next` / `next_steps` 与详情字段（`task_id`、`status`、`existing_contract_ids`、`registered`、`holders`…）—— 它们就是为这一步准备的；
2. 记住**工具 schema 现在与运行时的字段集是同一个**（2026-10-10 起：生成器从 `PAYLOAD_FIELDS` 与命令目录对齐，`tests/protocol/test_command_surface_contract.py` 逐条比对 schema / 目录 / 白名单 / handler）。所以**两边不一致就是缺陷本身**，不是"照 handler 写就行"：按 §4 上报。MCP 不会拿工具 schema 校验参数（`CallToolRequestParamsSchema` 里 `arguments` 就是自由对象），daemon 也不按工具 schema 拒 —— 它只按 `PAYLOAD_FIELDS`（顶层键）和 handler 自己校验；
3. 确实机制不对（例如某条命令需要的值在工具面上根本拿不到），**按"谁有权回答"上报**（2026-10-10 修正：单机模式下"上报 main"常常是自问自答，因为 main 就是链条顶端）：
   - **实现缺陷 / 文档与实现不一致** → 写一条 `cognition__report`（claims 里写清"缺什么、在哪一步缺的、影响哪条任务"），并在给用户的结论里点名它。**不要**绕桥把这一次对付过去。
   - **需要设计或权限决定**（改协议字段、改授权边界、跨机器、验收口径）→ 交给 main，由它用 `user_decision.propose` 提请**用户**决定；main 自己不能替用户答。
   - **我卡在某条任务上**（缺前置、缺决定）→ `task.block`（写 `reason_code`/`reason`），把它变成可见状态，而不是静默停手。

---

## 5. 跨进程与工具面：两条"看起来像你的错"的假象

### 5.1 `Error: unknown tool "mcp__tsunagou__…"`（纯文本那句）

那是**宿主**的工具目录没就绪时发的，**这次调用根本没到达桥** —— 桥既看不见、也无法回答它。
它不是"你把工具名拼错了"，而是"工具面当时不在"：会话比桥先起来、宿主正在重载配置、
或者这个 profile 里没装 Tsunagou 的 provider。**读作"重试一次"**：

- **读命令**（`context__project_read`、`inbox__claim`、各种查询）直接再调一次即可，8 秒后的同样调用通常就成功（实测 2026-10-10 15:49:20）；
- **写命令**：如果你自己会重试，**把 `command_id` 一起传**。桥接受调用方给的 `command_id`，daemon 按它去重（同一个 `command_id` + 同样的参数 → 返回第一次的结果，不会执行两遍；参数不同则报 `idempotency_conflict`）。这样"瞬断后重试"不会变成"同一条活干两次"。

桥**自己**答的那种长得不一样：它是 JSON（`{"error":"unknown_tool","code":"unknown_tool","next_steps":[…]}`），
说明工具面当时是通的、名字确实不在目录里。两种要分得开，因为处置正好相反。

**事后怎么查清是哪一种**：项目私有目录里的生命周期时间线
`<项目>/.tsunagou/local/bridge-lifecycle.ndjson`（桥每次启动/接上 stdio/回答 `tools/list`/
答自己的 `unknown_tool` 都追加一行，含时刻、pid、角色、工具数）。宿主那句不会在里面留痕；
如果那个时刻桥正在回答 `tools/list` 且数量正常，就说明问题在宿主侧的目录刷新。这个文件超过
256 KiB 会被清空重写，所以它只回答"最近一次"，不当作长期账本。

### 5.2 跨进程的 JSON 一律 UTF-8（2026-10-10 起）

规则只有一条：**两端都显式写出来**，不依赖区域编码。

- 父进程读子进程输出时一律 `encoding="utf-8", errors="replace"`（Windows 上只写 `text=True` 就是用 GBK 解，
  子进程按 UTF-8 打的中文会炸掉读线程、`stdout` 直接变成 `None`，症状是 `json.loads(None)` 报 `TypeError`）；
- CLI / daemon 入口先把 `stdout`/`stderr` 钉成 UTF-8 再打印（`PYTHONIOENCODING=utf-8` 传给子进程）。

**例外**：读的是**二进制内容**（例如 checkpoint blob）时保持字节、绝不加 `errors="replace"`。

这条修好之前，中文根名、契约 `subject_ref`、用户确认的目标都"理论上合法、实际上踩雷" ——
平台侧甚至因此把快照文本限制成 ASCII。**那个限制已经取消**：调用方给的原样值就按原样存、原样读回。

---

## 6. 静默、唤醒与看门狗

### 6.1 空闲看门狗会替你造一条消息（2026-10-10 起）

DSH 上的唤醒**永远由某个 Agent 显式调用**才会发生（`coordination__wake`），所以"没人动 ⇒ 没人叫"
正好闭在最需要它的那一步。daemon 里现在有一个**空闲看门狗**，它只做一件事：**在确定没人能再动的时候，
给 main 发一条自解释的消息**（投递走既有的自动通道，不是新机制）。

它叫的三种情形（消息种类就是判据的名字）：

| 消息 `kind` | 收件人 | 什么时候 | 它会说什么 |
|---|---|---|---|
| `coordination.stalled` | main | 没有任何会话在活动、没有在跑的 Attempt、没有可领的任务、没有已交付待验收的结果、没有待确认的完工提案、**没有未决的用户决定**，且安静够久 | "协作停住了：N 分钟没有任何事件……检查一下是不是都停了，然后接手、让 worker 继续，或者提请完工" |
| `coordination.waiting` | main | main 手上有活（有待验收的结果或未读消息），而其他人都停了 | "有活等你处理……验收、发布或回复之后这条协作才会继续动" |
| `task.resume` | **那个 worker 自己** | 它有**没提交、也没结束**的尝试，而它自己（以及整个项目）都安静够久 | "你的任务 X 还没提交，而这条会话已经安静了 N 分钟……继续做完，或者明确 `task.submit` / `task.block`" |

**它不会在你正干活的时候打扰你**：只要还有**任何一个会话在活动**（判据是已认证会话调用 ——
桥每 30 秒一次便宜读取），前两种就完全不叫。这比"看事件间隔"更准：agent 在本地写代码、跑构建时
本来就不发 Tsunagou 命令。它也**不会**在球在用户手上时叫（未决决定、待确认完工）。
同一个判定在冷却期内只叫一次；叫够 3 次还没人动，它会停下来并**提一条 `coordination.stalled`
的用户决定**（控制台"待用户决定"那一节），交给用户。

### 6.1.1 「我任务没提交，但我在等别人」——这不是停在中途

**回合边界是硬事实**：在 DSH 里，**只用文字回复就等于回合结束**，会话随即变成空闲
（`running` / `idle` / `unloaded`，宿主自己的词表）。所以"我说完一段总结"在宿主看来就是"我停手了"，
没有人会再叫你 —— `task.resume` 这条消息就是为这个存在的（2026-10-10 实测：一个 Agent 做完一部分、
输出总结，然后空闲了半天）。

**如果你是在等人，先说清楚**，否则看门狗有权把你当成停在中途：

| 你的处境 | 该做什么 |
|---|---|
| 做不下去了（缺前置、缺决定、缺权限） | `task.block`（这条尝试就此结束，看门狗不会再管它），把 `reason` 写清 |
| 等一个你**问出去**的答复 | 什么都不用做 —— 消息还挂着未结清的回应义务时，看门狗把你判为"在等"，不催你；但整条协作也跟着停住的话，它会把这件事交给 main |
| 等 main 或别的 Agent 先做完 | 一样：回一条消息把球踢出去（`message__send`），或者直接 `task.block`。**别人正在推进时它也不会叫你** |
| 只是本地在写代码/跑构建 | 什么都不用做 —— 你自己和整个项目都没事件时它才叫，且叫完有 30 分钟冷却 |

**你要知道的两条**：①看门狗叫 worker 的那一条**只针对"有任务且没提交"**；一条已经 `task.submit`
的尝试它永远不管（交活之后等你验收是 main 的事）；②**它叫了你，你就得动**：
`context__project_read` 的 `coordination` 那一块与收件箱都会显示它。
每次判定都会落一条 `coordination.idle_watchdog` 事件，里面写着当时的各项判据值 ——
"为什么叫"事后可查。

### 6.2 唤醒的投递时机是宿主的属性，不是你的选择

`coordination__wake_status` 与 `coordination__wake` 的返回都带 `delivery`：`requested`（今天恒为
`null` —— 命令只收 `message_id`）、`declared`（宿主声明的能力）、`used`（**这次实际用的**时机）、
`source`（这个说法从哪来）。取值只有五个：

| 取值 | 含义 |
|---|---|
| `step` | 在当前回合的**下一个步骤边界**读取；回合继续，在飞的步骤不被取消（DSH 插件 `wake_mode=steer`） |
| `turn_boundary` | 在下一个回合边界读取（DSH `queue`、OpenCode `delivery='queue'`） |
| `idle_only` | 只在会话空闲时投递；忙时什么都不发（Codex Desktop 原会话，已实现的行为） |
| `none` | 这个宿主**没有唤醒路径**：消息留在收件箱，等对方自己来取（Claude Code、ZCode、任意远端） |
| `unknown` | 读不到任何能说明时机的证据。这是**诚实的答案**，不是失败 |

请求的时机无法兑现、或实际投递比声明更晚时，返回里一定有 `degraded: true` + `degraded_from` +
`reason` —— **绝不静默降级**。`none` / `unknown` 都不允许被读成"已经叫醒"。

**跨机器的拒绝理由是写实的**：`cross_machine_unsupported` = 它在另一台机器上，本机没有可核实的本地
宿主路由、也没有入向通道 ⇒ **消息留在本机收件箱里，需要对方自己来取**；提示它自己来读，不要重试唤醒、
也不要换别的入口绕过。`host_identity_unverified` 只用于"本机接入、但路由核实不了"。自报机器名**不给**
本地访问权；已核实的本地路由优先于机器名。

**DSH Desktop 现在也有自动唤醒通道**（2026-10-10）：daemon 会在**本机已核实**的绑定上直接投递提醒，
不必人工点。没有绑定、或绑定未核实，仍只会得到 `host_binding_not_found` —— 那表示"**这条自动通道**
不可用"，不等于"DSH 不能唤醒"。失败不改插件配置，只把该绑定标成 `degraded`，一次核实过的成功唤醒会
把它恢复。

**各宿主的能力（2026-10-10 逐宿主只读核实）**：Codex → Codex 有自动通道、时机 `unknown`（仓库内没有
忙时观测）；Codex Desktop 原会话有自动通道、时机 `idle_only`；DSH Desktop 有自动通道、时机 = 插件的
`wake_mode`（`queue → turn_boundary`、`steer → step`）；OpenCode 无自动通道、脚本固定 `turn_boundary`；
Claude Code / ZCode / 任意远端 `none`。

---

## 7. 去哪读更多

| 要什么 | 读哪一节 |
|---|---|
| 每个区域有哪些命令、权限记号 `M/W/U/T`、URI | [命令目录](../implementation/command-catalog.md)：`权限记号`、`项目、授权与用户决定`、`Agent、会话与 Authority`、`任务、Attempt 与验收`、`Main 协调计划与 Worker 唤醒`、`认知与契约`、`资源与工作空间`、`消息、附件与持久操作`、`查询目录`、`CLI 映射与退出码` |
| CLI 怎么敲、HTTP 长什么样、错误怎么读、旧库迁移 | [操作手册](cli-http-manual.md)：`## 5. 一个任务的运行流程`、`### 5.1 契约名、发布与派活的如实语义（2026-10-08）`、`## 7. 当前 HTTP API`、`## 8. HTTP/CLI 错误的处理方式`、`## 10. 安全和清理`、`## 11. 旧库凭据迁移（PT2）` |
| 唤醒谁、能不能唤醒、状态怎么读 | [按需提醒与同机宿主唤醒补位](agent-wake-guide.md)：`## 先选通道`、`## 如何理解状态`、`## 失败时自行核实并收口` |
| 失败时间线、按 Attempt 看耗时、可选 OTel | [查询失败时间线与技术追踪](diagnostics-and-tracing.md)：`## 查询与导出`、`## 按 Attempt 查看流程经过时间` |
| 第一次接入、身份与项目选择 | [Agent 快速接入](agent-quick-start.md)；[子 Agent 加入与协作](subagent-guide.md) |
| 术语、状态、跨模块字段 | [数据模型](../implementation/data-model.md) |
| 文档全局约定与规范优先级 | [文档导航与规范优先级](../README.md) |

**本手册自己在哪里**：`docs/overview/agent-operating-manual.md`。
MCP 工具的 `instructions` 与每会话首次提醒给的都是**绝对路径** —— 由桥从自己的安装位置解析
（`packages/bridge-server/src/reminders.ts` 的 `operatingManualPath()`；远端 Worker 解析各自那份副本），
所以不必再猜、也不必去宿主的安装目录里翻。`instructions` 本身很短（只留"手册在哪、它回答什么"），
"在哪读上下文""唤醒指引"这类**每会话听一次就够**的内容都在**每会话首次读取**那条通道里交付。
本机 checkout 位置见 `.tsunagou/agent-context.md` 的「项目标识」一节（`本机 source path 仅为诊断提示`）。
