# Agent 快速接入 Tsunagou

控制台已准备接入时，在目标 Codex Desktop 对话中说 **“请接入 Tsunagou”** 即可。项目、昵称和主/子 Agent 身份取自前端的选择，不需要重复输入。已有授权下，Agent 处理普通接入步骤；需要用户执行时，只提供一条可直接运行的命令。

以下 Codex 自动接入代码已通过真实 daemon/MCP 进程测试；原 Desktop 会话的完整协作验收仍由 FX3/FX6 收口。测试客户端返回成功不等于该原会话已经 ready。

## 安装与项目入口

发行版源码只安装一份。安装器优先使用显式 `--source-root`，否则复用已登记安装、当前源码 checkout，首次安装才使用默认目录。安装结果含实际 source、commit、Python/bridge 版本和用户 CLI launcher；当前终端 PATH 未更新时直接使用返回的 launcher 完整路径。

指定业务项目和宿主后，安装器执行缺失的 project init 和 project bootstrap。Codex 项目得到：

- `AGENTS.md` 中的 Tsunagou 管理区块；
- `.tsunagou/agent-context.md`、project-integration.json、root binding 和源码引用；
- `.agents/skills/tsunagou-project/SKILL.md`；
- `.codex/config.toml` 中共享 MCP 的配置，保留用户其他配置。

不要复制 Tsunagou 源码到业务仓库。未选择的宿主不会被写入配置。已有项目不重新初始化；生成规则更新用 bootstrap --refresh。

配置文件只有在 Codex 信任项目时加载；全局 MCP 登记和项目配置使用同一个服务名 tsunagou。[Codex 配置说明](https://learn.chatgpt.com/docs/config-file/config-basic)、[MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

## 从控制台接入当前 Codex 对话

1. 在前端选择项目和主/子 Agent，点击准备接入。目标 Codex 与前端应位于同一机器、同一 OS 用户；该用户跨项目只有一个有效的 Codex 待接入申请。
2. 在要接入的原对话中说“请接入 Tsunagou”。接入 Skill 使用已安装的 launcher 执行 `tsunagou agent join`，无需项目参数或角色参数，也不依赖对话的当前工作目录。
3. CLI 读取前端申请、核验真实聊天身份、认领并完成接入。同一聊天重试复用身份；另一个聊天不能领取同一申请。没有申请、申请已取消或已过期时明确失败，Agent 不另建项目或退回 worker。
4. **原对话自己调用** MCP `context__project_read`，核对返回的项目、Agent、角色、ready session 和 host binding。控制台核对本次绑定和原会话回执后才显示成功；CLI 辅助进程的查询不能完成这一步。

接入失败后由同一聊天重试 `agent join`。尚未认领的申请可在前端取消；已经开始接入时取消会被拒绝，并保留当前绑定。若首次安装后尚未加载 Skill/MCP，按下文加载说明处理；“一句话接入”不代表安装前置条件可以省略。

刷新前端会自动找回当前申请的等待和取消入口，并标明原项目及角色；不会推进已经丢失的旧向导，也不会切换当前项目。同项目和角色重复准备沿用原申请与昵称；不同选择会说明已有申请，需先处理它。

从旧版本升级本功能时，已经运行的旧 bridge 进程也需要重载一次，才能生成原聊天回执。此后同版本共享 bridge 接收新会话路由无需再次重启。

## 不知道自己该接哪个项目时

一句“请接入 Tsunagou”传到聊天里时，它手上只有宿主给的两样东西：**自己的会话标识**和**工作目录**。协调根推不出来 —— 项目可以协调好几个文件夹，控制台也把项目建在自己的根下，所以工作目录常常只是业务代码目录，不是协调仓库。

用户点接入的那一下已经把答案记在机器上了（每个 OS 用户同时只有一条待接入申请），任何宿主都能读：

```powershell
tsunagou agent pending --adapter <本宿主的 adapter，例如 deepseek>
```

- 有申请：返回 `project_root`、`project_id`、`role`、`nickname`（**没有凭据**），照它接入即可；
- `status: none`：现在没有人等这个宿主接入 —— 如实报告，请用户先在控制台为目标项目准备接入。**不要**从机器上的项目清单里自己挑一个，也**不要**为了让接入有个去处而 `project init`。

DeepSeek Harness 的 `tsunagou_connect` 先读取本宿主仍处于 pending 的控制台申请，项目以申请为准；没有申请才按聊天工作目录及父目录发现项目。显式 `--project-root` 或 `TSUNAGOU_PROJECT_ROOT` 与申请冲突会报项目不匹配。OpenCode 的既有连接路径仍在**工作目录推不出项目**时才用记录。

## 手动指定项目和角色的接入

没有使用前端接入申请、且用户明确指定项目和角色时，保留以下入口。不要在控制台 `join` 失败后自动改走这条流程。

1. Agent 从当前项目或其子目录调用已安装 CLI；在目录外时加全局 `--project-root`。
2. **Agent 在自己的 Codex 会话中**执行 `tsunagou agent prepare --adapter codex --role worker`。用户指定主 Agent 时用 main。此步核对真实会话、保存私有接入请求，不创建 Agent。
3. prepare 返回完整 PowerShell 命令。Agent 已获接入授权就执行；否则把返回命令原样交给用户。命令包含已填好的 request-file 路径，用户不用寻找任何 ID 或 pipe，也不用额外 appoint。
4. connect 启动或验证 daemon，兑换票据、保存会话、绑定原 Desktop 对话并登记共享 MCP。输出 enrolled、project_id、agent_id、role、session、host_binding、source_root、version、connected_at。
5. **原对话自己调用** MCP `context__project_read`。身份、项目、ready session 和 host binding 正确后才报告 ready_worker/ready_main。

profile 只作显示标签。同一 IDE 的不同对话/subagent 由真实会话身份区分；同一对话重复 connect 或 bridge 重启复用原 Agent。共享 MCP 每次按宿主的 thread metadata 选择自己的私有状态；不能用另一会话的 session 文件顶替。

第一次写入 MCP 配置后，若宿主尚未加载工具，使用实际可用的重载入口；没有入口时只说明一次完整退出并重开 Codex 的动作。不要把 Ctrl+R 当作必然重启 MCP 的方法。若重启一次仍失败，读取具体错误后修配置。已经加载的共享 bridge 会在每次请求读取新接入材料，无需每添加一个 worker 都重建全部 MCP。

低层 agent enroll/appoint 保留作诊断入口。正常 Codex 用户无需手动填 conversation_id、agent_id、pipe 或 token。接入 Skill 本身不提供机械权限，hook 仅为可选提醒；身份和执行边界由 daemon/bridge 处理。

## DeepSeek Harness Desktop 接入

在正常打开的 Desktop 项目聊天中要求接入即可。Agent 优先调用宿主本地工具 `tsunagou_connect`；首次尚无此工具时，使用已安装 CLI 执行 `agent prepare --adapter deepseek`，把已有身份插件注册到实际 Desktop profile。此准备步骤不创建 Agent、不启动 daemon。优先使用宿主热重载，必要时完整重启一次并回到原聊天，不要求用户另开终端执行接入命令。

那条聊天的工作目录**不必**是协调仓库：控制台点接入时写下的待接入记录就是项目与角色的来源（`agent pending --adapter deepseek` 可核对）。即使 cwd 属于另一项目，DSH 也优先接入控制台选定的项目；无申请时才按 cwd 手动接入。所以顺序是：先在控制台为目标项目点一次接入，再去那条聊天里说“接入 Tsunagou”。

`tsunagou_connect` 从本次调用的宿主上下文取得真实聊天和工作目录，再调用固定的已安装 CLI；不接受模型填写的身份、凭据、任意命令或目录。不指定角色时保留已有角色，新登记默认为 worker；main 仍须用户明确指定。插件共享入口不保存某个 Agent 的凭据，每个聊天按自身身份选择私有路由。

工具返回 enrolled 后，**同一聊天**再调用 `mcp__tsunagou__context__project_read`，核对项目、自己的 Agent、角色和 ready 状态。CLI/helper 成功、临时 headless 会话成功或插件文件存在都不能替代这一步。Desktop 入口的实际验证状态以[现有验收报告](../acceptance/deepseek-harness-11-baseline-2026-10-01.md)为准；此入口不承诺 Codex 专属自动唤醒。

## OpenCode 接入（当前对话，任意目录）

首次安装运行 `tsunagou agent prepare --adapter opencode`，配置用户级接入工具和无凭据共享 MCP。重载一次并回到**原对话**，等待 MCP 连接完成；安装不创建 Agent、不签票。配置冲突时先解决提示的问题，不覆盖用户其他配置。

1. 在控制台选择项目、角色和 OpenCode，准备接入。此时只保存申请，不指定会话名。
2. 在要加入的当前对话中说“请接入 Tsunagou”，调用无参数的 `tsunagou_connect`。工作目录可以与项目无关；工具读取宿主真实会话 ID，通过已安装 CLI 的 `agent join --adapter opencode` 认领申请。
3. 工具返回 enrolled 后，**同一对话**调用共享 MCP 的 `context__project_read`。控制台核对原会话回执、Agent、项目、角色及 ready 状态后显示已接入。

后续接入只增加私有会话路由，不重复修改 MCP 配置。没有申请时明确提示先在控制台准备；失败由原对话重试。不要手填会话 ID、复制凭据或另建对话替代原对话验证。已有其他项目路由或旧绑定发生冲突时明确报错，不静默创建第二个身份。

旧项目级接入及跨机器邀请保留原流程，不批量迁移已有 Agent。旧绑定检查覆盖当前目标及本机索引中的项目；若旧项目已移出索引或移动后未重新登记，须先处理原绑定。本机 v2.0.18 的插件入口使用目录插件、`setup(api)` 和宿主执行上下文；不可照搬旧版插件示例。真实功能验证状态见[适配器实施说明](../implementation/adapter-opencode.md)。

## 多项目和查询

CLI 自动从子目录发现项目，无需每开一个终端重设环境变量。若选择让新项目复用已有项目的 daemon，在新项目目录运行：

```powershell
tsunagou daemon start --reuse 'D:\Work\ExistingProject'
tsunagou daemon status
tsunagou agent list --json
```

示例目录应由 Agent 换成用户实际选定的路径。--reuse 核对实际进程、源码和项目登记，复用同一端口/PID，但每项目保留独立数据库、Agent 和控制凭据。停止共享 daemon 会停止全部成员项目的服务；stop 输出全部受影响 project_ids，任务和资源所有权不会因此自动转移。从任一成员项目 start 会恢复同一个项目集合。

## 接入成功后的第一轮工作

主 Agent 读取上下文、收件箱和未决事项，报告自己的项目/角色/身份，再处理已获授权的普通工作请求：检查已有任务，发布所需任务或明确回复无需新任务；读到请求不能止步于转述。

1. main 创建目标、scope、依赖及必要契约；文件任务选择工作区策略，再 ready/publish。coordination__plan 可一次创建定向分工和通知，不要求凑足固定 Worker 数量。
2. Worker 读取分派、任务与当前 revision，调用 task__begin。成功后获得 running Attempt、scope，以及必要工作区/资源占用。无需 worker.ready 或资源续租。
3. Worker 在范围内工作；有实际分歧时用认知/契约工具协调。等待上游决定时 task__block 并结束本轮，无关工作可继续。
4. task__submit 自动采集结果、释放占用、撤执行权并通知 main；main 审查并控制 Git 整合。
5. 静默、断线和同库重启不转移 owner。原 owner 新 begin 恢复原 Attempt；main 可明确 recover/takeover，旧 Attempt 此后不能提交。
6. 项目完成、重大设计与越过用户固定边界仍由用户决定。
7. **新增 Agent 是用户决定的事，不是普通调度。** 用户明确允许之前，主 Agent 不得自行邀请、签票或组织新会话加入本项目，也不要替用户挑宿主；需要人手时向用户说明理由并请求允许。已在项目的 Agent 之间的普通委派照旧不需要再问。

### 消息与唤醒

message__send 保存消息、投递和 outbox；已绑定可用宿主后由 hostwake 投递到对应会话。普通消息、任务分派与结果通知共用持久消息路径。发送成功、宿主接受请求、实际回合开始和收件确认分别记录，不要求模型再提交一份 worker.ready。

FX3/FX4/FX6 负责原 Codex 会话自动唤醒的产品接入与现场验收；底层 IPC 或 MCP 通过不能替代该验收。资源占用始终与宿主消息投递超时分开。

普通 Task 完成不等于 Project 完成；用户按手册执行 project complete，checkpoint 失败查询 Operation 并按需 retry。

### 协作提醒 hook

共享 bridge 为 Codex、OpenCode、DeepSeek Harness 提供两个纯提醒 hook。提醒以独立文本附加在原有工具 JSON 之后，不改变业务结果或权限。

- **唤醒提醒（所有 Agent）**：需要唤醒其他 Agent 时，请通过 PowerShell 执行对应宿主的唤醒操作；**发起方和接收方都为 Codex 时**，沿用 Codex 已有的唤醒机制。请确认是否确实需要唤醒，避免重复操作。规则出现在 MCP instructions、项目上下文，以及分派任务、提交结果、审核反馈、发送协作消息等成功操作之后。
- **完工提案提醒（仅当前 main）**：读取上下文、成功接受或自验收任务结果后，提醒 main：如果所有工作已经完成，且合并与验收已通过，请调用 `project__completion_propose` 发起任务完成提案，不要仅在聊天中宣布完成。已有待确认提案时不要重复提交，最终完工由用户确认。是否已经完成全部工作由 main 判断，单个任务完成不代表整体验收通过。

hook 不执行 PowerShell、不发送额外消息、不自动唤醒或续跑 Agent，也不自动发起或确认提案。失败操作保留原有错误指导。提醒不证明某个宿主具备可用的唤醒能力，具体操作仍由 Agent 根据实际宿主处理。

唤醒提醒附有 [各宿主原会话操作指南](agent-wake-guide.md)，包含 OpenCode 命令形状、Codex 已有机制与 DeepSeek Harness 的操作入口及限制。优先读取安装源码中的指南；不要把尚未完整实现或未经当前宿主验证的 Tsunagou 自动唤醒当作前提，也不要陷入反复配置、探测、重绑。消息已入队不等于对方已开始新回合。

失败时 Agent 先自行核对是否认错目标厂商/宿主，再核对原会话和操作入口，依据真实注册与版本信息修正后重试；不要要求用户手动唤醒。仍有真实能力或权限阻塞时向 main 记录证据和未解决状态。

升级共享 bridge 后，运行中的旧 bridge 需重载才能使用新的工具提醒；已有项目通过 `tsunagou project bootstrap --refresh` 更新生成的常驻上下文，用户自写区块仍予保留。


## 断线恢复

Agent 先自行查看 daemon status、doctor、agent list --json。daemon 不可用时 connect 自动启动所选实例；可用时 bridge 复用现有 session，真正失效或宿主代次变化才 reconnect。宿主端点变更时重新 prepare/connect 同一会话，不能通过创建新身份掩盖故障。使用 project history、task history 查询已持久化的时间线。

CLI 结果不能证明 LLM 已开始工作。完整使用方法见 [CLI/HTTP 手册](cli-http-manual.md)，角色边界见 [子 Agent 指南](subagent-guide.md)。


### 本机 DSH 控制台等待恢复

控制台准备后，原 DSH 聊天通过 `tsunagou_connect` 接入。CLI 将实际 Agent ID
关联到这次申请；控制台看到该 Agent 角色正确、会话 ready 后自动确认。
原聊天仍须调用 `context__project_read` 验证自身上下文。控制台确认不是原聊天回执。

若旧的、尚未过期的申请因 baseline 卡住，在原聊天重新调用接入工具即可复用身份并补关联；
无需改 baseline 或手动执行 CLI。已过期申请保持过期，已有 Agent 不会因此被删除。
本次修复不改变 Codex、OpenCode 或跨机器邀请流程。运行中的旧控制台需要在用户安排下
加载更新；DSH 插件的实际加载版本仍须在现场确认，自动化通过不代表原聊天验收完成。
