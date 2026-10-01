# D186：项目目标由对话产生、由用户确认，不由建项目时填

日期：2026-10-01。来源：用户判断——按设计，项目信息应当是用户与主 Agent 对话、主 Agent 确认下来、再开展分工的；因此"项目目标"应当由主 Agent 在对话结束后总结。但控制台的建项目向导提供目标输入，两者并存。

## 背景：并存的两句话与三处问题

核查（2026-10-01）确认当时是**两种来源并存、互不可见**，不是同一字段的冲突：

- 用户在建项目时填的那句：经 `project.initialize`（U 级、MCP 不发布）写进项目本体 `.tsunagou/project.json` 的 `objective`，并进入机器级索引；控制台主视图按它显示。
- 主 Agent 自己说的那句：写在 `coordination.plan.objective`（M 级）和逐条 `task.objective` 里。计划是**可选**命令，且 `/coordination` 出口没有任何控制台视图在读。

由此有三处具体问题：

1. **没有修改路径**：`Project.objective` 全仓库没有 setter；`ProjectRegistry.initialize` 只在项目不存在时才写（对已有项目重跑 `project init` 也不更新）；`project.configure` 只收 `policy_patch`。主 Agent 永远无法把"我们其实要做的是 X"写回项目目标。
2. **两个副本可能不一致**：登记已存在路径时 `.tsunagou/project.json` 是权威、机器级索引只是缓存，两边都可能各存一份目标。
3. `shared_checkpoint.COLLECTION_FIELDS` 里**没有 coordination 这一组**，`plan` 表又在 Git 忽略的 `.tsunagou/local/state.sqlite3` —— 计划连同它的目标不随存档/克隆走；即"这个项目当初要做什么"在共享历史里只由项目本体那句承担。

另一处事实：`plan.objective` 是**必填**（schema `minLength: 1` + `create_plan` 再校验一次），但今天没有任何判定在读它——完工走 `expected_project_revision`（比 `policy_revision`）加一个不做校验的自由字符串 `objective_ref`。必填是过去"目标要可引用、可验收"那套设计的遗留锚点（见 `docs/history/2026-09-18-source/project_completion_protocol.md` 的 `objective_revision` / `objective_results`），读者已经换人，锚就悬空了。

## 决定

1. **目标不由建项目时收集**：控制台向导第 1 步只问名字；中间层在调用方没给 objective 时写固定占位文本，而不是"等于项目名"。占位是真写进项目本体的（schema 是 `minLength: 1`，空值会被协议拒掉），不是界面兜底。
2. **占位文本只有一处措辞**：`PENDING_OBJECTIVE = "待主 Agent 与用户确认"` 定义在 `src/tsunagou/modules/projects.py`，控制台 `create()` 与 CLI `project init --objective` 的默认值共用。安装器不再自己造措辞：没给 `--project-objective` 就不传 `--objective`，让 `project init` 去填。
3. **目标由主 Agent 提出、用户确认**：复用现成的 `user_decision.propose`，`kind` 用保留值 `project.objective`，目标文字写在 `summary`（命令里唯一的自由文本位），`choices` 给可选项。用户答过（`status=resolved`）之后，它才是项目目标。**这不新增命令、字段或权限**：`kind` 本来就是自由字符串，`project.objective` 只是约定。
4. **界面显示的次序**：主视图那句目标取**最后一条** `kind=project.objective` 且 `status=resolved` 的决定的 `summary`；没有就回落到项目记录里那句（即占位）。已答的决定不能被撤回、只能再提一条，所以"最后一条"就是最新那版理解。
5. **计划的抬头不算项目目标**：`coordination.plan.objective` 是"这一批任务要干什么"，主 Agent 换个阶段就会变；把它当项目目标显示会让主视图随阶段变窄，且"哪一份计划算数"没有可依据的规则。因此界面刻意不读它（daemon 的 `/coordination` 出口仍在，供审计与后续设计使用）。
6. **"确认过"因此可被机械核查**：决定带 `input_digest`、精确 revision 与 `status`，且 `user_decision` 在 `shared_checkpoint` 的 `lifecycle.decisions` 采集清单里——目标随之进入共享历史，能追溯、能审计。这是纯流程约定（"主 Agent 讲清楚、用户口头同意后才发计划"）做不到的一件事。
7. **把约定写进 Agent 真正会读的地方**：`application/project_integration.py` 生成的 `.tsunagou/agent-context.md` 与 `AGENTS.md` 片段新增一条边界（目标要经用户确认；不要把占位句当目标复述），`GENERATOR_VERSION` 随之推进到 `project-bootstrap-v3`。

## 未做与边界

- **不动协议**：`project.initialize` 的 `objective` 仍是必填 `minLength: 1`，只是取值变成占位文本；没有新增命令，没有改 schema，没有新 Grant。
- **不加界面控件**：主视图复用它已有的 `.textArea`，没有新增元素或类；占位句由后端写、前端不重复一份措辞。
- **保留值的写法靠约定而非 schema 枚举**：`kind` 是自由字符串，daemon 不会拒绝别的 `kind`。是否把它收紧成枚举，留给以后要不要为 `user_decision` 建种类表时一并决定。
- **`plan.objective` 的必填未动**：它是"计划抬头"，仍按原样保留；要不要让它也参与完工判定，属于 A 方案（给项目目标开回写命令）的范围，本轮不做。
- **项目本体那句仍是占位**：目标是"用户确认过的那条决定"，项目本体字段不会随确认被改写。若以后要让它落进项目本体（存档里也有），需要新命令，见下。

## 影响

- `web/method.md`：向导 `.collect()` 不再含 `objective`；`projectCreate` 的目标由中间层兜底；§12 记两条改动。
- `docs/overview/runtime-walkthrough.md`：删掉"用户只需设定目标"，改为"用户与主 Agent 谈定目标、主 Agent 提交用户确认"。
- `docs/implementation/cli-contract.md`、`docs/implementation/command-catalog.md`、`docs/implementation/runtime-prompts.md`：同步默认值、保留 `kind` 与注入时的占位说明。
- 根文档 `Tsunagou-项目设计解释.md`：记录这次取舍与"为什么不是 A"。
