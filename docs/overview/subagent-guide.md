# 子 Agent 怎样加入项目并协作

子 Agent 是拥有独立宿主对话、身份和任务责任的项目成员。首发验收可使用 Codex、OpenCode 或 DeepSeek Harness，例如主 Agent 用 Codex、两个子 Agent 分别用 OpenCode 与 DeepSeek Harness。ZCode 适配器暂不进入首发验收，但仍保留后续接入方向。它不是共享主Agent凭据的另一个窗口。

Tsunagou 中的“子”主要描述任务委派关系：它独立领取子任务、报告理解、参与契约、提交结果。主Agent统筹任务和Git，用户指导重大方向。宿主自带的临时subagent不会仅因它是“子Agent”自动加入Tsunagou；正式成员仍需adapter提供独立、可恢复的会话身份并通过接入检查。

## 用户如何让子 Agent 加入

以下是首发流程。当前 M1 已有可运行的 CLI、daemon、HTTP 查询和 stdio bridge；用户 CLI 的实际命令范围与环境变量要求见[完整使用说明书](cli-http-manual.md)，尚未注册的领域命令仍由主 Agent typed tools 完成。

1. **先建立调度中心。** 在用户选择的 Git 仓库初始化项目，得到 project_id；指定一个会话作为 main，并设好项目范围和授权上限。
2. **准备子Agent所在宿主。** 按对应adapter安装指南启用工具入口。打开一个新对话，选择它需要工作的文件夹。这个工作目录可以是项目的其他root/仓库，不必与协调仓库相同。
3. **把该对话接入指定项目。** 告诉当前 Agent“作为 worker 加入本项目”。Agent 在自己会话中执行 `agent prepare --adapter codex --role worker`，再按已有授权运行返回的完整 connect 命令；确需用户时，只交付这一条已填好路径的命令。真实宿主对话决定身份，profile 只是标签；不让用户查 ID、pipe 或复制 token。connect 会把本项目早期固定-session MCP 配置迁移为共享路由配置，不影响其他项目或正在运行的 bridge。主 Agent 同理，但 main 角色必须是用户的明确选择。
4. **查看接入结果。** connect 输出 enrolled 后，原对话自己调用 bridge 的 `context__project_read`，确认 project_id、独立 agent_id、ready session 和宿主绑定。另一客户端的 HTTP 查询或 headless bootstrap 成功不能代替原会话 ready。没有 Desktop 刷新按钮时，先直接查询；若该旧对话仍运行固定-session bridge，则新开对话再查询，只有它仍未加载共享 MCP 才完整重开 Codex 一次。无需重新接入。可用 `agent list --json` 查看成员、任务和最近活动。
5. **让主Agent安排工作。** 主 Agent 创建任务、确定 scope 和文件任务的工作区策略并发布。子 Agent 读黑板及任务 revision，调用 `task.begin`，成功后按返回的 Attempt/scope 工作；完成后 `task.submit` 自动采集结果。
6. **继续使用原对话。** 普通重连保留原 Agent；新对话、fork、subagent 都有独立身份。静默或同库重启不改变任务 owner。原 owner 再 begin 恢复；owner block 或 main recover 后，后来加入且符合定向分派约束的 Worker 可以 begin。

若宿主已验证支持managed_launch，用户可选择launch方式；没有该能力就按上述步骤手动打开再attach。两种方式都必须独立认证与probe，不因系统帮助启动就减少权限检查。

已经有主Agent时，它也可以在用户给定上限内签发worker接入票据、组织子Agent加入，用户无需每次都调整安全参数。实际打开宿主会话、安装插件或选择目标会话，仍按该宿主能力与用户操作完成；主Agent不能自行任命另一个主Agent或扩大用户上限。

## 三个容易混淆的阶段

| 阶段 | 子Agent拥有什么 | 尚不能做什么 |
|---|---|---|
| 接入ready | 自己的身份、基础协调权限、可见项目状态和自己的inbox | 不自动拥有任务，不接管main职责 |
| begin 成功 | 唯一 running Attempt、当前 scope 与执行 Grant | 文件任务同时返回工作区与资源占用；不可越界或替他人提交 |
| submit 成功 | 不可变 Result，状态 submitted，执行权已释放 | 等待 main 审查；不等于项目完成 |

## 子 Agent 在项目里负责什么

- 读取目标与任务，主动提交自己的理解、假设、不确定性和范围变化。
- 发现接口或数据认知差异后参与协商，接受自己核对过的契约版本；收到消息的ACK不表示赞同。
- 在允许范围内执行自己的任务，报告进展，提交证据与结果；审查别人的工作需要明确reviewer指派。
- 需要更多文件范围时向main提出scope request；main能决定的自行处理，超出用户上限才交用户。
- 等待相关上游决定时保存进度、释放执行资源并挂起；如果还有不相关任务，可以继续。
- 恢复时先查黑板、未决事项和当前任务版本，再 `task.begin`；不能沿用旧执行 Grant。

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

**两个子Agent在同一目录。** 它们是两个身份；main 用 task scope、资源占用和合适的共享/Worktree/外部隔离策略协调。

**新对话想继续旧任务。** 不能拿相同 cwd 冒充旧 owner。main 显式 recover 后，新 Worker begin 创建新 Attempt；旧 Grant 不转移。

**用户还没回答。** 相关Agent正常结束本轮并挂起，系统保留决定与快照；不需要持续向模型发无意义消息，也不自动判失败。

**主Agent离线。** 子Agent可处理仍在权限内、不依赖 main 的工作；需要 main 的 Git、统筹或决定等待。原会话恢复沿用身份；确需更换 main 时由用户指定新会话并选择 --role main，按当前 authority 状态处理原任命。子Agent不会自动选举自己。

**宿主处于Full Access。** 子Agent仍须遵守调度中心的任务和scope。系统API会机械拒绝越权请求；无法控制的宿主文件操作可能只有提示/观察约束，不能说成OS沙箱已拦截。
