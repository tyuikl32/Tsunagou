# 最终成果的运行流程

以下是当前 M1 已可运行流程与后续完整产品体验的边界。产品 CLI 名称固定为 `tsunagou`；实际可执行命令见[完整使用说明书](cli-http-manual.md)，完整协议映射见[接口目录](../implementation/command-catalog.md)。

## 1. 建立项目

用户准备一个已存在的 Git 仓库，运行 `tsunagou project init --coordination-root <path>`。后端立即在仓库顶层建立 `.tsunagou/`：可共享的身份、配置和 checkpoint，与忽略提交的本机 SQLite、附件及运行数据分开。

用户可把其他目录、其他仓库注册为 named roots。它们不必在协调仓库下面。物理路径只保存在本机绑定中，共享描述使用 root ID、repo ID 和相对路径。尚未建立 Git commit 不阻止普通协作；未锚定状态会明确显示。

## 2. 接入并任命主 Agent

用户经 CLI 发放一次性接入票据，bridge 从宿主读取可信的 conversation ID，完成身份、能力和协议检查。每个会话获得独立凭据；模型看不到令牌。能力不足的会话停在诊断状态。

用户通过 CLI/HTTP 控制通道任命一个就绪 Agent 为主 Agent。它读取目标、项目 policy 和用户授权上限，向其他 Agent 分发接入或任务协作要求。主权限不能由子 Agent 自己申请成功。

### 用户怎样加入两个子 Agent

用户先执行 `tsunagou project bootstrap --coordination-root <path> --source-root <tsunagou-checkout> --host <kind>`，让项目目录出现 `AGENTS.md`、项目 skill 和 `.tsunagou/agent-context.md`。再在已装 adapter 的宿主中分别打开两个新对话，并对每个对话执行 `tsunagou agent enroll --adapter <kind> --mode attach --installation-id <id> --conversation-id <conversation> --output-dir <path>`，按宿主选择器指定目标会话。CLI/有权限的 main 签发 worker 票据，由目标 bridge 私下兑换；不把票据或 session token 粘贴到模型里。支持 managed_launch 时可由系统启动，不支持时手动打开再 attach。

当前 CLI 没有 `agent list/show`；通过 `/api/v1/projects/{project_id}/agents` 或主 Agent typed tools 查看两个不同 `agent_id` 和各自 HostSession。能力检查通过才 ready；同目录工作不共享身份。用户只需设定目标、任命 main 和必要边界，主 Agent 随后负责普通任务拆分。它创建/发布子任务，子 Agent 各自读取黑板、claim 并准备执行；加入项目本身不自动获得任务 owner 或执行 Grant。

如果ready之前进入degraded，先修复adapter诊断，不能当作可工作成员。完整步骤和不同宿主/会话恢复规则见[子Agent指南](subagent-guide.md)与[CLI/HTTP手册](cli-http-manual.md)。

## 3. 开始协作

主 Agent 创建任务与明确依赖；参与者查询黑板，原子领取符合条件的开放任务。开始前提交理解与假设，检查契约、风险建议、工作空间和所需资源 Lease。所有前置条件满足后进入 running。

例如 API Agent 认为 `status` 是可空字符串，而调用方认为它必填。两者提交报告，创建 Discrepancy，协商出一个 `data_schema` 契约。所有必需参与者接受同一 proposal digest 后，依赖契约的任务解除相关阻塞。

两个子Agent直接对自己的报告、契约接受和结果负责。main可组织讨论，但不能把“收到消息”替换成某个子Agent的接受，也不能仅凭main角色提交别人Attempt。父任务和子任务独立：委派不强制父任务暂停，父终态也不自动取消仍有价值的子任务。

## 4. 遇到阻塞与用户决策

如果问题可由主 Agent 在授权内解决，它直接决定并留证。若改变项目目标、重大设计或需要用户保留的权限，主 Agent 在对话中说明方案，再创建精确版本的 UserDecision。

用户运行 `tsunagou decision list`，从返回对象中取得决定的当前 revision/digest，再用 `tsunagou decision resolve <id> --choice <actual-choice> --expected-revision <n> --digest <digest>` 提交决定。当前 CLI 没有 `decision show`；需要详情时读取 HTTP `/api/v1/decisions` 或由主 Agent typed tools 展示。对话中的“同意”用于讨论，首发不当作系统层的用户凭据。相关 Agent 保存进展并挂起，其他无关任务继续。没有默认“用户回复超时”。

## 5. 提交、审查与 Git 整合

Agent 提交结果 manifest 和验证证据，由指定验收方式处理。需要返工则结束旧 Attempt，新开 Attempt；任务 completed 后不复活，以 follow-up 表示后续工作。

所有 Git 写操作，包括创建/移除 Worktree、commit、merge、push，均由主 Agent 执行。系统记录请求、运行基线和结果，用只读命令核验本机证据。它不会因为主 Agent 离线就自行执行 Git。

## 6. 用户确认完成与恢复

主 Agent 提议项目完成，当前 Attempt 与执行授权先收敛，用户通过专门completion confirm控制接口确认精确 proposal revision/digest（见[手册](cli-http-manual.md)路由表）。Project 立即变为 completed，同时生成必须完成的 checkpoint Operation。checkpoint 失败不撤销用户完成结论，但阻塞需要它的归档、发布或迁移。

daemon 崩溃后恢复 Job、outbox 和会话连接；clone 或回退旧 checkpoint 会建立新的运行身份，回退产生新 lineage。旧运行令牌、Grant 与 Lease 不能恢复使用。用户重新任命主 Agent，主 Agent 显式挑选需要继续的非终态任务。
