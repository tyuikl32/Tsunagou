# CLI 外壳与已有领域命令的精确映射

本文件细化 T16 的命令行参数，属于工程约定，**没有新增领域权限或业务命令**。当前 `tsunagou` 已实现基础 doctor、project init/bootstrap/complete/history/timings、agent connect/enroll/appoint、task history、audit event、decision、operation、checkpoint create/retry/list/verify 和 recover；其余表项仍是待接入契约。HTTP 和权限仍以[命令目录](command-catalog.md)为准；面向用户的步骤见[简明手册](../overview/cli-http-manual.md)。

## 1. 适用范围

CLI 是用户控制入口，持有 user_control 凭据。用户已授权安装/加入时，Agent 可执行对应 CLI 而不打印凭据；业务执行仍经自己的 bridge/MCP。`agent prepare` 观察真实宿主并只写私有请求，`agent connect` 按该请求签票据、由 bridge 兑换并登记原会话，不以 profile 生成身份。`agent enroll` 保留为低层恢复入口。main 角色仍需用户明确选择，组合接入不创造超级身份。

| CLI | 行为 | 输出 |
| --- | --- | --- |
| `agent prepare --adapter codex --role worker`（或 main） | 核对宿主并写私有请求；不签权限 | prepared、已填写的 connect 命令 |
| `agent connect --adapter codex --request-file PATH --role worker`（或 main） | 已授权 U 接入、bridge 兑换和原会话绑定；将同项目、同 bridge 的旧固定-session MCP 注册迁移为共享路由 | enrolled、project_id/agent_id/role/session/host_binding/source_root/version/connected_at，以及本次 connect_started_at/connect_finished_at/enrolled_at/duration_ms；原会话 MCP 查询后才 ready |
| `agent list [--json]` | 项目成员只读投影 | 角色、会话状态、当前任务及 UTC 最近活动；不读取私信 |

`daemon start/stop/status`是本机进程管理，不伪装成Project领域mutation。其余项目操作走本机HTTP；不要直接读写SQLite绕过同一policy。

## 2. 命令签名

当前公共形式：`tsunagou [--project-root <path>] [--json] <group> <command> ...`。项目上下文由显式根目录、绑定环境或最近祖先的 `.tsunagou/project.json` 确定；冲突报错，不按进程 cwd 猜另一项目。部分查询要求其签名列出的业务 project_id，不能把它当成不存在的全局 `--project` 参数。下表未实施的子命令仍是规划契约，实际可执行项以顶部说明和 CLI `--help` 为准。

| CLI | payload来源 / 对应已定入口 | 成功输出 |
|---|---|---|
| `installation-info [--json]` | 本机用户级安装记录白名单投影；无需 daemon | source_root/commit/source_dirty/runtime 版本、安装起止及 duration_ms；缺失时间为 null，不含接入秘密 |
| `daemon start` | 用户配置+OS启动，绑定127.0.0.1随机端口 | endpoint/instance，不含token |
| `daemon status` / `stop` | 本机实例身份核验；stop 等待确认进程退出 | running/0、stopped/3、unverified/4；重复 stop 为 already_stopped/0；不杀未核实的 PID |
| `web start [--host <addr>] [--port <n>] [--config <path>]` | 托管控制台页面并把页面请求转发给各项目 daemon（补控制令牌）；**只允许回环地址**；端口默认 2812（固定是为了能收藏），被占用时另取空闲端口并在启动行说明；显式 `--port` 或配置里的 `port` 被占用则失败，不静默改 | 启动行与 `.tsunagou-console.local.json` 里的 url/host/port/pid（另带 port_requested、port_fallback）；`web status` 报告在跑的那个 |
| `project init --coordination-root <path> [--name <name>] [--objective <text>]` | `project.initialize`；缺 name 用默认名，缺 objective 写占位文本（目标是用户与主 Agent 确认后才有的事实，见[决策](../decisions/2026-10-01-objective-from-dialogue.md)） | Project与genesis Operation |
| `project bootstrap --coordination-root <path> [--source-root <path>] [--source-ref <ref>] [--host <kind>] [--refresh]` | 项目本地入口物化；不创建Agent/任务，不写秘密 | 受管文件状态、project_id、source reference |

安装器的显式 `--project-root` 表示用户已选择业务项目：若 `<root>/.tsunagou/project.json` 不存在，安装器会先调用 `project init`（可用 `--project-name`、`--project-objective` 指定初始化文字；没给 `--project-objective` 时不自己编一句，让 `project init` 写占位），随后调用 `project bootstrap`。不传 `--project-root` 时不会猜测项目或写入业务项目。
| `project list` / `show` | GET项目列表/指定Project | 同query DTO |
| `project complete <proposal_id> --expected-project-revision <n> --digest <digest>` | `project.completion.confirm`；proposal_id与digest绑定已审阅的CompletionProposal，project revision必须匹配 | Project completed与强制checkpoint Operation；仅U可调用 |
| `root register --request-file <json>` | `root.register.user`；文件是catalog的业务payload | RootRegistration |
| `root bind <root_id> --request-file <json> --expected-revision <n>` | `root.bind.user` | RootBinding/Operation |
| `root list` | GET P/roots | RootPage，敏感字段脱敏 |
| `agent enroll --adapter <kind> [--profile <name>] --mode attach` | U签发worker ticket；所选宿主bridge执行`agent.enroll` | 非秘密EnrollmentReceipt与ready/degraded |
| `agent enroll --adapter <kind> [--profile <name>] --mode launch` | 同上，额外要求managed_launch=supported；不是首发共同基线必需 | 启动/接入进度和receipt |
| `agent list` / `show <agent_id>` | GET P/agents[/{id}] | 状态、角色、session与能力摘要 |
| `authority show` | GET P/authority | current main、authority epoch与revision |
| `authority appoint <agent_id> --request-file <json> --expected-revision <n>` | `authority.appoint`；文件含expected_authority_epoch、ceiling_template、reason；CLI加入agent_id | Authority |
| `authority revoke --request-file <json> --expected-revision <n>` | `authority.revoke` | Authority unassigned |
| `task create --request-file <json>` | `task.create.user` | draft Task；不自动ready/publish/claim |
| `task list` / `show <task_id>` | GET P/tasks[/{id}] | TaskPage/Task |
| `decision list` / `show <decision_id>` | GET P/decisions[/{id}] | 精确proposal摘要与版本 |
| `decision resolve <id> --choice <choice> --expected-revision <n> --digest <digest> [--reason <text>]` | `user_decision.resolve`；先读该版本decision绑定的expected_revisions并原样提交 | Decision与关联结果 |
| `checkpoint create --request-file <json>` | `checkpoint.create.user`；reason、minimum_event_seq? | Operation |
| `checkpoint list <project_id> [--verify]` | GET `/api/v1/projects/{project_id}/checkpoints` | manifest状态与覆盖水位；`--verify` 实际校验文件摘要 |
| `checkpoint verify <checkpoint_id>` | GET `/api/v1/checkpoints/{checkpoint_id}/verify` | manifest、文件摘要和本地 Git anchor |
| `project history <project_id> [--from] [--to] [--actor] [--subject] [--limit] [--cursor] [--json] [--export]` | GET project history 或 history/export | AuditPage 或脱敏导出，不写状态 |
| `project timings <project_id> [--task-id <task_id>] [--json]` | 认证 GET project history 全部分页，以及 attempts/results；按精确 Attempt/Result ID 只读组合 | ProjectTimings：开始、提交、审查的 UTC 时间、来源、实际可见事件数和流程经过时间；无 payload/evidence/私信引用 |
| `project diagnostics <project_id> [--message-id] [--task-id] [--from] [--to] [--json]` | GET project diagnostics | callback、wake、presentation、turn 的脱敏诊断证据及发生/记录/观测时间；过滤不提高权限，不写 domain event |
| `task history <task_id> [--project-id] [--from] [--to] [--actor] [--limit] [--cursor] [--json]` | GET task history | 任务及其可见关联实体的 AuditPage |
| `audit event <event_id> [--project-id] [--include-evidence] [--json]` | GET single audit event | 因果、证据、变更详情；越权拒绝 |
| `project restore --coordination-root <clone> --checkpoint-digest <digest>` | 本地只读 `preview`；加 `--confirm-plan-digest <preview.plan_digest>` 才导入 | 仅 clean clone；检查本地 Git 可达 heads/tags 的完整 manifest/tree；不覆盖既有数据库、凭据、bridge 或 root binding；恢复后 authority unassigned、根 unbound、非终态任务需 recovery review |
| `operation list` / `show <id>` | GET P/operations[/{id}] | 原始status、Resolution、effective_outcome |
| `operation resolve <id> --request-file <json> --expected-revision <n>` | `operation.resolve.user` | 追加Resolution |
| `project archive --request-file <json> --expected-revision <n>` | `project.archive.user` | barrier Operation |
| `project reactivate --request-file <json> --expected-revision <n>` | `project.reactivate.user` | Project/Operation，新runtime |
| `project reset-lineage --request-file <json> --expected-revision <n>` | `project.lineage.reset` | Operation；高影响，展示精确目标 |
| `project unregister --request-file <json> --expected-revision <n>` | `project.unregister` | 仅注销，不删除项目文件 |
| `config show --effective --provenance` / `validate` | GET /api/v1/config及本机只读校验 | 脱敏值与来源/校验结果 |
| `doctor` | GET /api/v1/doctor | 诊断，不自动repair或扩大权限 |
| `experiment run <id> --request-file <json>` / `report <id> --request-file <json>` | 已定U实验入口 | Operation |

`adapter kind`固定为codex/opencode/zcode/deepseek；CLI显示DeepSeek Harness避免与模型API混淆。首发 release gate 只要求 codex/opencode/deepseek，zcode 保留为 post-release diagnostic adapter。profile用于选择本机安装档案，不作为HostSession身份。attach的目标对话由adapter可信宿主接口/会话选择器绑定，CLI不得接受`--actor`或用显示名猜conversation。

旧概览列出的`agent reprobe/retire`、`authority handoff`、`task publish/recover`、`operation cancel`仅有D/M主体handler，**首发用户CLI不注册同名可执行子命令**。对应行为由自身bridge/current main typed tool完成；在确有用户入口的领域设计确认前，不加`*.user`来凑齐旧命令树。`agent show`/doctor给诊断及正确处理者。main离线时用户可用已有appoint/revoke恢复统筹。

## 3. 请求、环境与输出契约

PT2 已加入离线命令 `daemon migrate-credentials --coordination-root <path> [--dry-run] [--confirm-plan-digest <digest>]`：默认只读预览，显式 digest 才撤销旧权限并清理可见秘密；不能同时传 dry-run 与 confirm。活跃 daemon 锁或过期计划拒绝执行，输出只含安全报告；失败退出 4，输入错误退出 2。中断后重跑原 digest，完成后重新 enrollment/appoint。操作步骤见 [用户手册](../overview/cli-http-manual.md#11-旧库凭据迁移pt2)，数据契约见 [凭据交付](credential-delivery.md)。

`--request-file`只包含命令目录payload，不含token、actor、command_id或envelope。不能一会儿接受裸payload、一会儿接受全请求而由CLI猜。CLI用生成DTO验证并提示字段路径；文件内未知字段拒绝。用户可以用非秘密文件准备复杂scope/ceiling，不在命令行拼几十个参数。

每次mutation生成UUIDv7 command_id；支持显式`--command-id <uuidv7>`用于重试同一操作。timeout/network错误自动重试时保留同一ID和规范输入；改choice/payload/revision视为新命令，使用新ID。更新对象要求`--expected-revision`，CLI转为If-Match；交互向导可先读展示再绑定当前版本，不能自动接受后续版本。

`decision resolve`的digest必须与读取的proposal一致，CLI不能“取最新摘要”替换用户提供值；读取时revision已经变化就本地失败提示重新审阅。网络期间又变化由服务器412拒绝。具体动作仍由Server决定如何应用，不由CLI私自写Task/Grant。

`project complete`只提交用户明确审阅的CompletionProposal：命令行中的proposal_id、`--expected-project-revision`和`--digest`必须指向同一版本。CLI不得从“最新提案”补值，也不得由`decision resolve`、`project archive`或其他成功动作自动触发确认；缺字段返回输入错误，竞争变化由服务器拒绝并要求重新审阅。

CLI从platformdirs私有目录读取control token；不提供`--token`，不把秘密写环境变量、request-file、日志或JSON。T01固定普通运行参数的配置键；本手册不引入未登记的`TSUNAGOU_*`环境开关。endpoint由daemon发现文件读取并核对instance，不能凭过期PID连接别的服务。

PT5 的只读查询从本项目 `.tsunagou/local/control.token` 读取已有控制凭据，通过 daemon 查询。`project history` 支持 `--from/--to/--actor/--subject/--limit/--cursor` 和脱敏 `--export`；`task history` 展开任务关联实体；`audit event` 查询单条责任记录；`checkpoint list/verify` 验证本地持久化。根级或命令级 `--json` 输出同一投影，查询不写 SQLite，拒绝无凭据、过期游标和变更过滤条件的游标；未知历史时间显示 `unknown_time`。未来全局凭据目录迁移不改变这一只读权限模型。

FX5 的 `project timings` 复用这些读取边界，不新增后台路由或领域命令。JSON 为 `{project_id, items}`；每项含 attempt_id、task_id、owner_agent_id、state、started_at/submitted_at/reviewed_at、对应的 started_source/submitted_source/reviewed_source、begin_events/submit_events、review_action，以及 work_elapsed/review_wait_elapsed。source 分别为 `task_begin_event`、`task_submit_event` 或 `result_created_at`、`task_review_event`，无法确定时为 null。elapsed 含 `elapsed_ms` 和 `clock_status`（ok/unknown/clock_inconsistent）；反向时钟保留事实时间但不返回成功耗时。

开始和审查仅用可见事件的 occurred_at；提交优先用可见 submit 事件，否则用唯一匹配公开 Result 的 created_at。这是服务器记录的提交时间，不是 COMMIT/fsync 完成瞬间。显式私信 evidence 仍可隐藏整条 submit 事件，此时 `submit_events=0` 与非空 `submitted_at` 可以同时成立。多个 Result、多个阶段事件或提交来源时间冲突保持 null/unknown；不使用 Attempt.ended_at、实体 updated_at 或当前时间补值。审查只沿明确 Attempt/Result 引用关联，不猜同一 Task 的最近 Attempt。history 页使用既有固定水位，三个查询间不宣称跨请求原子快照；活跃任务可能只返回已读取到的阶段，重新查询可补齐。权限错误退出 3，输入错误退出 2，分页或响应校验失败退出 5，均不输出部分汇总或原始响应。

`--json`输出生成DTO/Problem，日志只在stderr。`--wait <seconds>`仅对返回Operation的命令有效；超时退出6，打印operation_id和最近状态，不取消业务操作。没有wait则202受理退出0，用户后续show。普通操作的退出码沿用catalog的0/2/3/4/5/6。

## 4. 验证与错误矩阵

| 输入或结果 | CLI行为 |
|---|---|
| 未选project且不是全局命令 | 退出2，提示显式--project，不猜最近项目 |
| request-file包含token/actor或未知字段 | 退出2，指出字段名，不回显秘密值 |
| enroll attach多个对话未明确绑定 | 用户选择可信宿主句柄或返回输入错误，不按cwd合并 |
| launch增强不支持 | 说明改用attach，不能仍显示已启动 |
| enrollment receipt是degraded | 如实显示接入记录已建立但未就绪，不宣称baseline通过 |
| decision版本/digest变化 | 退出4，重新show/review；不重试最新批准 |
| completion proposal的ID/revision/digest或expected revisions缺失、过期、不一致 | 输入缺失退出2；服务端冲突退出4，重新审阅精确提案；不自动确认最新版本 |
| 401/403 | 退出3，恢复凭据或用正确主体，不换token冒用 |
| 202 + Operation pending | 退出0；--wait超时退出6，业务仍继续 |
| Agent-only保留动作用CLI调用 | 退出2/帮助中无该命令；不读取Agent token执行 |

## 5. 正常、降级与拒绝案例

正常：用户attach两个独立会话，两个bridge各自兑换worker ticket，均ready；用户只任命其中一个main，另一个保持普通成员，随后自己claim子任务。

降级：ZCode所选版本无法证明resume的ID连续性，产生degraded诊断。CLI可以show原因，用户修好host配置后由其bridge reprobe；不能点击“仍然信任”绕baseline。

拒绝：用户在终端尝试`task submit --actor workerA`，该用户CLI不存在此执行入口；task.submit必须workerA当前session/Attempt授权。改用main token同样不能代替workerA提交。

## 6. 必需验证

T16对表中每个CLI入口建立映射fixture：command kind、principal、目标URI、payload、If-Match、退出码；用户help不出现尚无U策略的保留命令。对decision竞争更新、enroll秘密交付、Operation等待超时、JSON模式缺输入和stale endpoint做集成断言。所有示例以command registry/Schema校验，不以字符串快照替代语义检查。

## 7. 常见错误与正确做法

错误：CLI读main的token调用task.publish，以为“反正都是用户电脑”。正确：现有main tool执行该领域动作；用户CLI只调用已注册U命令。

错误：为了让例子简单省略revision、把票据复制给模型。正确：CLI维护必要envelope和If-Match，票据经本机私有交付给所选bridge，模型只看到非秘密接入结果。
