# Agent 快速接入 Tsunagou

用户可以直接告诉当前 Agent：“在本项目安装 Tsunagou，并作为主 Agent 加入”，或在另一个对话中说“作为 worker 加入本项目”。已有授权下，Agent 处理普通安装与接入步骤；需要用户执行时，只提供一条已填写实际路径的命令。

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

## 当前会话如何加入

1. Agent 从当前项目或其子目录调用已安装 CLI；在目录外时加全局 `--project-root`。
2. **Agent 在自己的 Codex 会话中**执行 `tsunagou agent prepare --adapter codex --role worker`。用户指定主 Agent 时用 main。此步核对真实会话、保存私有接入请求，不创建 Agent。
3. prepare 返回完整 PowerShell 命令。Agent 已获接入授权就执行；否则把返回命令原样交给用户。命令包含已填好的 request-file 路径，用户不用寻找任何 ID 或 pipe，也不用额外 appoint。
4. connect 启动或验证 daemon，兑换票据、保存会话、绑定原 Desktop 对话并登记共享 MCP。输出 enrolled、project_id、agent_id、role、session、host_binding、source_root、version、connected_at。
5. **原对话自己调用** MCP `context__project_read`。身份、项目、ready session 和 host binding 正确后才报告 ready_worker/ready_main。

profile 只作显示标签。同一 IDE 的不同对话/subagent 由真实会话身份区分；同一对话重复 connect 或 bridge 重启复用原 Agent。共享 MCP 每次按宿主的 thread metadata 选择自己的私有状态；不能用另一会话的 session 文件顶替。

第一次写入 MCP 配置后，若宿主尚未加载工具，使用实际可用的重载入口；没有入口时只说明一次完整退出并重开 Codex 的动作。不要把 Ctrl+R 当作必然重启 MCP 的方法。若重启一次仍失败，读取具体错误后修配置。已经加载的共享 bridge 会在每次请求读取新接入材料，无需每添加一个 worker 都重建全部 MCP。

低层 agent enroll/appoint 保留作诊断入口。正常 Codex 用户无需手动填 conversation_id、agent_id、pipe 或 token。接入 Skill 本身不提供机械权限，hook 仅为可选提醒；身份和执行边界由 daemon/bridge 处理。

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

### 消息与唤醒

message__send 保存消息、投递和 outbox；已绑定可用宿主后由 hostwake 投递到对应会话。普通消息、任务分派与结果通知共用持久消息路径。发送成功、宿主接受请求、实际回合开始和收件确认分别记录，不要求模型再提交一份 worker.ready。

FX3/FX4/FX6 负责原 Codex 会话自动唤醒的产品接入与现场验收；底层 IPC 或 MCP 通过不能替代该验收。资源占用始终与宿主消息投递超时分开。

普通 Task 完成不等于 Project 完成；用户按手册执行 project complete，checkpoint 失败查询 Operation 并按需 retry。


## 断线恢复

Agent 先自行查看 daemon status、doctor、agent list --json。daemon 不可用时 connect 自动启动所选实例；可用时 bridge 复用现有 session，真正失效或宿主代次变化才 reconnect。宿主端点变更时重新 prepare/connect 同一会话，不能通过创建新身份掩盖故障。使用 project history、task history 查询已持久化的时间线。

CLI 结果不能证明 LLM 已开始工作。完整使用方法见 [CLI/HTTP 手册](cli-http-manual.md)，角色边界见 [子 Agent 指南](subagent-guide.md)。
