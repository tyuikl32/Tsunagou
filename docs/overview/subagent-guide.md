# 子 Agent 怎样加入项目并协作

子 Agent 是拥有独立宿主对话、身份和任务责任的项目成员。首发验收可使用 Codex、OpenCode 或 DeepSeek Harness，例如主 Agent 用 Codex、两个子 Agent 分别用 OpenCode 与 DeepSeek Harness。ZCode 适配器暂不进入首发验收，但仍保留后续接入方向。它不是共享主Agent凭据的另一个窗口。

Tsunagou 中的“子”主要描述任务委派关系：它独立领取子任务、报告理解、参与契约、提交结果。主Agent统筹任务和Git，用户指导重大方向。宿主自带的临时subagent不会仅因它是“子Agent”自动加入Tsunagou；正式成员仍需adapter提供独立、可恢复的会话身份并通过接入检查。

## 用户如何让子 Agent 加入

以下是首发流程。当前 M1 已有可运行的 CLI、daemon、HTTP 查询和 stdio bridge；用户 CLI 的实际命令范围与环境变量要求见[完整使用说明书](cli-http-manual.md)，尚未注册的领域命令仍由主 Agent typed tools 完成。

1. **先建立调度中心。** 在已有Git仓库初始化项目，得到project_id。用户接入一个会话并任命主Agent，设好项目范围和授权上限。
2. **准备子Agent所在宿主。** 按对应adapter安装指南启用工具入口。打开一个新对话，选择它需要工作的文件夹。这个工作目录可以是项目的其他root/仓库，不必与协调仓库相同。
3. **把该对话接入指定项目。** 用户执行`agent enroll --adapter <kind> --mode attach`，明确选择宿主profile和目标会话。CLI申请一次性worker票据，adapter通过本机私有通道领取并兑换；用户不需要把票据或token贴进模型对话。
   当前 CLI 可同时生成逐会话的非秘密 bridge 启动描述：
   `tsunagou agent enroll --adapter codex --mode attach --installation-id <安装标识> --conversation-id <目标会话标识> --output-dir .tsunagou/bridges/<会话名>`。输出目录中的 `ticket.json` 只供 bridge 私下读取，配置 JSON 只保存 daemon 地址、项目 state 目录、路径和启动参数，不保存 token；bridge 启动时从 state 目录读取当前 endpoint manifest，因此 daemon 重启换端口后不会继续使用旧地址。用户把该 JSON 的 env/command 配置交给对应宿主即可。若不提供 `--output-dir`，CLI仍只写私有临时票据，不生成启动描述。
4. **查看接入结果。** 当前 CLI 没有注册 `agent list/show`；通过 HTTP 的 `/api/v1/projects/{project_id}/agents` 或主 Agent typed tools 查看独立 `agent_id`、宿主、session 状态及能力。`ticket_issued` 只表示票据已签发，只有 bridge 兑换成功并能读取项目上下文才算 ready；degraded 表示保留诊断对象，尚不能领取任务。
5. **让主Agent安排工作。** 主Agent创建并发布子任务，告诉对应子Agent任务引用和目标。子Agent读取黑板，自己claim，报告理解并完成preflight，start后才可执行。
6. **继续使用原对话。** 普通断线或恢复应保持同一Agent，adapter自动校验连续性；新建/clear/fork是另一会话，需要新身份，不能继承旧任务owner。

若宿主已验证支持managed_launch，用户可选择launch方式；没有该能力就按上述步骤手动打开再attach。两种方式都必须独立认证与probe，不因系统帮助启动就减少权限检查。

已经有主Agent时，它也可以在用户给定上限内签发worker接入票据、组织子Agent加入，用户无需每次都调整安全参数。实际打开宿主会话、安装插件或选择目标会话，仍按该宿主能力与用户操作完成；主Agent不能自行任命另一个主Agent或扩大用户上限。

## 三个容易混淆的阶段

| 阶段 | 子Agent拥有什么 | 尚不能做什么 |
|---|---|---|
| 接入ready | 自己的身份、基础协调权限、可见项目状态和自己的inbox | 不自动拥有任务，不接管main职责 |
| 领取claimed | 一个TaskAttempt的唯一owner、明确任务范围 | 尚不能把“领到了”当作running执行许可 |
| preflight通过并start | 当前scope、workspace、资源Lease与执行Grant | 不可越界，不可替他人提交，不可执行main专属Git写操作 |

## 子 Agent 在项目里负责什么

- 读取目标与任务，主动提交自己的理解、假设、不确定性和范围变化。
- 发现接口或数据认知差异后参与协商，接受自己核对过的契约版本；收到消息的ACK不表示赞同。
- 在允许范围内执行自己的任务，报告进展，提交证据与结果；审查别人的工作需要明确reviewer指派。
- 需要更多文件范围时向main提出scope request；main能决定的自行处理，超出用户上限才交用户。
- 等待相关上游决定时保存进度、释放执行资源并挂起；如果还有不相关任务，可以继续。
- 恢复时先查黑板与未决事项，再显式resume/preflight/start；不能沿用旧上下文中的授权。

子Agent没有自己的隐式下属授权。需要再拆分任务时向main建议，由main创建子任务；不因它当前拥有一个Task，就自动获得task.create或agent.enroll。

## 用户、主 Agent 和子 Agent 的分工

| 工作 | 用户 | 主Agent | 子Agent |
|---|---|---|---|
| 目标、重大设计、项目完成 | 指导并最终确认 | 提出方案和证据 | 提供分析/结果 |
| 接入worker | 可直接发起 | 可在上限内组织/签worker票据 | 自己的bridge完成兑换与probe |
| 任命/撤销main、扩大上限 | 通过control决定 | 不能代签 | 不能接管 |
| 创建/发布任务 | 通过已支持U入口创建计划 | 主要统筹者 | 建议并领取合格任务 |
| 执行与提交TaskAttempt | 不冒充owner | 仅执行自己拥有的Attempt | 仅执行自己拥有的Attempt |
| 认知/契约协商 | 必要时定方向 | 组织并处理授权内分歧 | 公开理解并对自己的接受负责 |
| commit/merge/worktree/push | 设边界、必要时批准 | 执行全部Git写动作 | 提供文件/patch/结果证据和请求 |

## 常见情况

**两个子Agent在同一目录。** 它们仍是两个身份；共享目录不等于共享授权。用ResourceIntent/Lease与任务范围协调，必要时main选择Worktree或外部隔离。

**新对话想继续旧任务。** 若不是可验证的原会话resume，不能冒充旧owner。main执行继任，关闭旧Attempt并新建责任，旧Lease/Grant不转移。

**用户还没回答。** 相关Agent正常结束本轮并挂起，系统保留决定与快照；不需要持续向模型发无意义消息，也不自动判失败。

**主Agent离线。** 子Agent可处理仍在权限内、不依赖 main 的工作；需要 main 的 Git、统筹或决定等待。用户通过控制端的 `agent appoint AGENT_ID` 恢复统筹，子Agent不会自动选举自己；当前 CLI 没有 `authority appoint/revoke` 这组命令名。

**宿主处于Full Access。** 子Agent仍须遵守调度中心的任务和scope。系统API会机械拒绝越权请求；无法控制的宿主文件操作可能只有提示/观察约束，不能说成OS沙箱已拦截。
