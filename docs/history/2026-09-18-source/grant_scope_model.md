# Grant Scope 与资源选择器

> 核对日期：2026-09-17。
> 状态：第 183 题已确认选项 A；作为 D107 的 Grant Scope 基线。

## 问题

Capability 表示动作种类，Grant scope 必须表示动作可以作用在哪些对象上。首发至少涉及项目、Task/Attempt、Root 下的路径、消息收件关系和 reviewer round。若用自由 JSON/字符串表达式，早期看似省事，但每个 handler 会自行解释；若为每个对象建立独立 ACL 表，则会抵消单表 Grant 的简化。

## 第 183 题：Scope 如何表达

### A（已确认）：按 Grant kind 固定的类型化 Scope，存规范 JSON

- 每种 grant kind 只接受一个确定 schema，不实现任意 selector 列表或表达式语言。
- `agent_base` scope 固定为当前 project membership 与 authenticated self；消息 recipient 等关系由 CommandPolicy predicate 检查，不写进 scope。
- `main_authority` scope 保存允许管理的 root IDs、可委派 root prefixes/capability subset，并绑定 authority epoch；user-only ceiling 仍在独立本机表。
- `task_attempt` scope 保存精确 task/attempt/execution epoch、root/path selectors、resource selectors 和允许使用的 workspace ID；owner 关系仍由 predicate 检查。
- `task_review` scope 保存精确 task、submitted attempt/result 和 review round；没有 root write scope。
- `handoff_transition` scope 保存 source/target authority epoch、原 grant/attempt 引用和只允许收敛的对象集合。
- scope 以版本化 discriminated JSON schema 验证，JCS 规范化后保存 `scope_digest`；常用外键另有列，不能只靠 SQLite JSON 查询保证关系。

优点：只维护少数 schema，handler 无需解释通用布尔语言；适合单表 Grant 和当前固定 kind。代价：新增 grant kind 或 scope 字段需要 schema/migration/兼容更新。

### B（已否决）：通用 ResourceSelector 数组

- 每条 selector 使用 `kind + resource_id/path + actions + constraints`，所有 grant kind 共用；授权器遍历匹配。

优点：扩展新资源类型较灵活。代价：需要定义 selector 组合、交并、否定、祖先关系和性能索引，容易逐步演变为策略语言。

### C（已否决）：每种资源关系使用独立授权表

- `grant_roots`、`grant_tasks`、`grant_paths`、`grant_messages` 等关系表分别表达 scope。

优点：关系和 SQL 查询明确。代价：表与 join 数量增加，Grant kind 的固定结构仍需额外约束；首发迁移和仓储工作最多。

## 选择 A 时的 wire 示例

```json
{
  "scope_type": "task_attempt",
  "scope_version": 1,
  "task_id": "...",
  "attempt_id": "...",
  "execution_epoch": 3,
  "workspace_id": "...",
  "roots": [
    {
      "root_id": "...",
      "path_prefixes": ["src", "tests"]
    }
  ],
  "named_resources": [
    {"resource_type": "service", "resource_id": "test-db"}
  ]
}
```

路径只使用 D87 的 root-relative normalized segments；禁止绝对路径、`..`、未登记 root 或通过 alias 扩大范围。空 `path_prefixes` 的含义必须由 schema 固定为“整个已授权 root”或“无路径”，不得由 handler 猜测。

## 后续待细化

- 五种 scope schema 的完整字段与 JSON Schema `$id`；
- root prefix 的规范表示、包含检查和最大数量/长度；
- main-authority 可委派范围与 task-attempt scope 的 subset 算法；
- scope digest 变化与 grant replacement 的事务流程。

## 第 184 题：Root 内的路径范围如何表示（已确认 A）

[Python `pathlib` 文档](https://docs.python.org/3/library/pathlib.html#pathlib.Path.resolve)指出，消除 `..` 和解析符号链接需要实际 filesystem resolution；[Git pathspec](https://git-scm.com/docs/gitglossary#Documentation/gitglossary.txt-aiddefpathspecapathspec)还包含 glob、magic、case 等独立语义。授权 scope 不应直接接受这两类宿主字符串或复用 Git 的匹配语言。

### A（已确认）：仅正向的 root-relative segment prefix

- `path_rules[]` 每项为 `{root_id, access: read|write, path_prefix: string[]}`；segments 已按 wire profile 规范化，不含空段、`.`、`..`、分隔符、盘符、UNC 或绝对路径。
- `path_prefix=[]` 明确表示整个 root；`path_rules=[]` 表示没有文件路径权限，避免空值歧义。
- prefix 覆盖该路径本身及其后代；`write` 同时允许 read，不必重复两条规则。首发没有 exact-file、glob、regex、extension filter 或 deny rule。
- 多条正向规则取并集；与 user/main/project/parent scope 取交集时，仅保留相同 root 中更窄的 prefix。互不包含的 prefixes 交集为空。
- wire matching 先按规范 segments 做逻辑判断；真正访问前仍执行 D87 的本机 binding、case、link/reparse point 和 physical identity 校验。逻辑前缀匹配不声称解决路径逃逸。

优点：算法和测试简单，跨 Windows/macOS/Linux 可重放；能表达多个文件夹范围且不引入匹配语言。代价：不能只授权某类扩展名或用排除规则，需把允许目录拆成多个 prefixes。

### B（已否决）：只授权整个 Root，不支持子目录范围

- scope 只存 `{root_id, access}`，任务获得整个登记 root 的 read/write。

优点：实现最少。代价：多仓库/大目录项目中授权过宽，与用户和主 Agent按文件夹控制范围的既有目标不符。

### C（已否决）：支持 glob/Git pathspec 与 deny 规则

- selector 可包含 `src/**/*.py`、排除项、case 选项或 Git magic，并按 allow/deny 组合。

优点：表达力最强。代价：跨平台语义、规则交集、链接解析、性能和安全审查复杂；容易与 shell/Git 的实际匹配结果不一致。

## 第 185 题：TaskAttempt Grant 的范围从哪里派生（已确认 A）

### A（已确认）：Task 保存版本化 execution scope，Attempt 只取交集快照

- user/current main 在创建或发布 Task 时写入 `execution_scope` 和 `scope_revision`；它包含 path rules、named resource limits、允许的 workspace/driver constraints，不含具体 owner/session。
- claim 只锁定 task 与 owner；preflight 以 task scope、用户 ceiling、project/root policy、current main 可委派 scope和宿主能力的交集生成不可变 `EffectiveAttemptScope` digest，再签发 `task_attempt` grant。
- owner 的 ResourceIntent 可以在 effective scope 内选择实际资源和 Lease，但不能扩大 scope。请求额外路径/资源时发送 `ScopeExpansionRequest` 给 current main。
- current main 可在自身可委派范围内批准。若 attempt 已 running，则先进入 typed blocked、释放受影响 leases、撤销旧 task grant，更新 task scope revision 后显式 resume/preflight 签发新 grant；不能原地扩大 active grant。
- 用户仍可直接修改 ceiling/scope；任何扩大都留下 issuer、reason、old/new digest 和事件。

优点：子 Agent不能通过自己声明 ResourceIntent 扩权；范围在 claim 前可见，preflight 可重放，符合 D101 的“新 grant 替代旧 grant”。代价：发现遗漏路径需要一次主 Agent批准和重新 preflight。

### B（已否决）：由 owner 的 ResourceIntent 在主 Agent上限内动态派生

- Task 只保存粗略 root 集；owner 在 preflight/运行中声明 prefixes，系统只要确认未超过 main scope 就自动扩展 task grant。

优点：工作流顺畅，主 Agent无需逐次处理。代价：普通 Agent可以在宽上限内自行选择任意目录，削弱“主 Agent决定子 Agent边界”的要求；运行中 grant 变更更复杂。

### C（已否决）：Attempt 直接继承 main-authority 的全部可委派范围

- 每个 owner 获得主 Agent可委派的完整 roots/resources，再依靠自然语言和 Lease减少冲突。

优点：实现最少。代价：子 Agent拥有远超任务所需的逻辑权限，Task scope 与最小权限失去意义。

## 第 186 题：Task scope 扩大请求由谁批准（已确认 A）

### A（已确认）：当前主 Agent在自身可委派范围内直接批准，超出范围才交用户

- owner 提交 `ScopeExpansionRequest`，说明新增 root/path/resource、原因、影响和当前 task/attempt/scope revision。
- current main 可在其 `main_authority` grant、用户 ceiling 和 project policy 交集内批准收窄或扩大；不得超过自己的可委派范围，也不能改变用户 ceiling。
- 批准在一个 UoW 中创建新的 task scope revision、记录 old/new digest 和审计事件，并撤销受影响的旧 task grant。running attempt 进入 `blocked(reason=scope_changed)` 或由 owner 主动停止，释放受影响 leases；新 scope 只能在显式 resume/preflight 后生效。
- 超出主 Agent可委派范围、扩大用户 ceiling、加入高敏 root、改变 coordination root 或跨 ownership/trust boundary 的请求必须由用户批准；主 Agent只能转发结构化请求。

优点：日常遗漏路径不需要用户介入，同时保留 D88 的主 Agent委托边界。代价：需要区分主 Agent批准与 user-only expansion 两类结果。

### B（已否决）：所有扩大都要求用户批准

- current main 只能收窄和提交请求，任何新增路径/资源都进入 user-only 队列。

优点：权限责任最集中。代价：本机开发中频繁遗漏路径会阻塞协作，主 Agent的管理职责被削弱。

### C（已否决）：在 main-authority 范围内自动批准

- 只要请求未超过主 Agent上限，系统自动更新 task scope 并重签 grant，不等待主 Agent或用户。

优点：吞吐最高。代价：普通 owner 可借请求逐步探索主 Agent全部范围，缺少主 Agent对任务边界的判断；与 D98 的集中委派不一致。

## 第 187 题：ScopeExpansion 批准的生效与回执（已确认 A）

### A（已确认）：批准提交即生效，用户通知只作审计

- current main 或 user/control 的批准在 UoW 提交后立即产生新 scope revision、旧 grant 撤销和相应 blocker/condition 变化。
- 系统向 task owner、当前主 Agent和 user/control inbox 发送摘要，包含 old/new digest、范围差异、批准者和重新 preflight 要求；收件人是否 fetched/presented/ACK 不影响权限。
- owner 不需要接受新 scope；它可在看到通知后停止、继续或提交澄清。旧 attempt grant 不能在新 revision 下继续写入。

优点：和 D92 单阶段 authority、D80/D92 通知非门禁语义一致；避免主 Agent批准后任务卡在无人确认。代价：主 Agent可能批准了 owner 尚未理解的范围，依靠结构化摘要、审计和用户可撤销修正。

### B（已否决）：owner ACK 后才生效

- 批准先进入 pending；owner 显式确认后才撤销旧 grant、签发新 grant。

优点：执行者明确知情。代价：离线/失联 owner 会阻塞；引入 proposal/accept 变体，与已确认的单阶段授权方向冲突。

### C（已否决）：用户 ACK 后才生效

- 主 Agent批准只作为建议，必须用户确认范围差异。

优点：用户控制最强。代价：把主 Agent日常范围管理降为请求转发，所有普通遗漏路径都增加用户交互。
