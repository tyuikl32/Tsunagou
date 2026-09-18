# CLI 外壳与已有领域命令的精确映射

本文件细化T16的命令行参数，属于工程约定，**没有新增领域权限或业务命令**。`tsunagou`尚未实现；这里是应实现的帮助、参数和映射。HTTP和权限仍以[命令目录](command-catalog.md)为准；面向用户的步骤见[简明手册](../overview/cli-http-manual.md)。

## 1. 适用范围

CLI由用户启动，持有user_control凭据。Agent执行命令经自己的bridge/MCP，不读取CLI控制凭据。`agent enroll`可以组合“用户申请票据”和“目标bridge兑换”，但两个请求仍属于不同principal和不同原子事务；组合不创造超级身份。

`daemon start/stop/status`是本机进程管理，不伪装成Project领域mutation。其余项目操作走本机HTTP；不要直接读写SQLite绕过同一policy。

## 2. 命令签名

公共形式：`tsunagou [--project <project_id>] [--json] <group> <command> ...`。项目命令要求显式`--project`；无参数发现存在多个项目时不猜。init/list/daemon/config/doctor不要求project；JSON模式遇到需选择的对象返回输入错误，不能无限等交互。

| CLI | payload来源 / 对应已定入口 | 成功输出 |
|---|---|---|
| `daemon start` | 用户配置+OS启动，绑定127.0.0.1随机端口 | endpoint/instance，不含token |
| `daemon status` / `stop` | 本机已验证daemon实例；stop优雅收敛 | status/worker收敛摘要 |
| `project init --coordination-root <path> [--name <name>] [--objective <text>]` | `project.initialize`；缺name/objective交互询问，JSON模式要求补齐 | Project与genesis Operation |
| `project list` / `show` | GET项目列表/指定Project | 同query DTO |
| `project confirm-completion <proposal_id> --request-file <json> --expected-revision <n>` | `project.completion.confirm`；proposal_id绑定URI，If-Match绑定已审阅的CompletionProposal revision；文件必须含该版本的proposal_digest、expected_project_revision、expected_revisions | Project completed与强制checkpoint Operation；仅U可调用 |
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
| `checkpoint list` / `show <checkpoint_id>` | GET checkpoint列表/详情 | manifest状态与覆盖水位 |
| `operation list` / `show <id>` | GET P/operations[/{id}] | 原始status、Resolution、effective_outcome |
| `operation resolve <id> --request-file <json> --expected-revision <n>` | `operation.resolve.user` | 追加Resolution |
| `project archive --request-file <json> --expected-revision <n>` | `project.archive.user` | barrier Operation |
| `project reactivate --request-file <json> --expected-revision <n>` | `project.reactivate.user` | Project/Operation，新runtime |
| `project reset-lineage --request-file <json> --expected-revision <n>` | `project.lineage.reset` | Operation；高影响，展示精确目标 |
| `project unregister --request-file <json> --expected-revision <n>` | `project.unregister` | 仅注销，不删除项目文件 |
| `config show --effective --provenance` / `validate` | GET /api/v1/config及本机只读校验 | 脱敏值与来源/校验结果 |
| `doctor` | GET /api/v1/doctor | 诊断，不自动repair或扩大权限 |
| `experiment run <id> --request-file <json>` / `report <id> --request-file <json>` | 已定U实验入口 | Operation |

`adapter kind`固定为codex/opencode/zcode/deepseek；CLI显示DeepSeek Harness避免与模型API混淆。profile用于选择本机安装档案，不作为HostSession身份。attach的目标对话由adapter可信宿主接口/会话选择器绑定，CLI不得接受`--actor`或用显示名猜conversation。

旧概览列出的`agent reprobe/retire`、`authority handoff`、`task publish/recover`、`operation cancel`仅有D/M主体handler，**首发用户CLI不注册同名可执行子命令**。对应行为由自身bridge/current main typed tool完成；在确有用户入口的领域设计确认前，不加`*.user`来凑齐旧命令树。`agent show`/doctor给诊断及正确处理者。main离线时用户可用已有appoint/revoke恢复统筹。

## 3. 请求、环境与输出契约

`--request-file`只包含命令目录payload，不含token、actor、command_id或envelope。不能一会儿接受裸payload、一会儿接受全请求而由CLI猜。CLI用生成DTO验证并提示字段路径；文件内未知字段拒绝。用户可以用非秘密文件准备复杂scope/ceiling，不在命令行拼几十个参数。

每次mutation生成UUIDv7 command_id；支持显式`--command-id <uuidv7>`用于重试同一操作。timeout/network错误自动重试时保留同一ID和规范输入；改choice/payload/revision视为新命令，使用新ID。更新对象要求`--expected-revision`，CLI转为If-Match；交互向导可先读展示再绑定当前版本，不能自动接受后续版本。

`decision resolve`的digest必须与读取的proposal一致，CLI不能“取最新摘要”替换用户提供值；读取时revision已经变化就本地失败提示重新审阅。网络期间又变化由服务器412拒绝。具体动作仍由Server决定如何应用，不由CLI私自写Task/Grant。

`project confirm-completion`同样只提交用户明确审阅的CompletionProposal：命令行中的proposal_id、`--expected-revision`和请求文件中的proposal_digest必须指向同一版本，请求文件还要原样携带该提案冻结的expected_project_revision与expected_revisions。CLI不得从“最新提案”补值，也不得由`decision resolve`、`project archive`或其他成功动作自动触发确认；缺字段返回输入错误，竞争变化由服务器拒绝并要求重新审阅。

CLI从platformdirs私有目录读取control token；不提供`--token`，不把秘密写环境变量、request-file、日志或JSON。T01固定普通运行参数的配置键；本手册不引入未登记的`TSUNAGOU_*`环境开关。endpoint由daemon发现文件读取并核对instance，不能凭过期PID连接别的服务。

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
