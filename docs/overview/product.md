# 项目目的、问题与交付范围

当前交付优先级（2026-09-20）：先完成[独立运行最小成品M1](../standalone/README.md)，以真实协作和重启恢复验收。下文描述完整目标，不表示所有功能已经实现；当前八模块进度见[代码差距表](../standalone/status-and-gaps.md)。

多个 Coding Agent 可以同时写代码，却常常没有一致的“我们在做什么”：一个把字段当成可空，另一个把它当成必填；一个认为任务还在讨论，另一个已经开始合并。会话结束后，这些分歧、承诺和进度又容易丢失。Tsunagou 提供一个持久的协调中心，把任务事实与 Agent 主动公开的理解放在一起。

首要价值是**认知协作闭环**：至少两个 Agent 公开不同理解，系统根据显式报告或确定性规则建立分歧，参与者形成并接受同一份契约，随后继续完成任务。多 Agent 的数量本身不是价值证明。

## 首次交付

- 个人在同一台机器上使用，多项目由一个本机 daemon 托管；Windows 为首要验收平台，接口与路径模型兼顾 macOS/Linux。
- 完整 Python 后端、HTTP API、CLI、共享 MCP 服务、持久化和四种桥接代码：Codex、OpenCode、ZCode、DeepSeek Harness。首发正式验收覆盖 Codex、OpenCode、DeepSeek Harness；ZCode 适配器保留但正式共同基线和发布验收延后。主动唤醒、工具门禁和进程托管依真实宿主能力增强。
- 项目可包含多个文件夹、多个 Git 仓库。用户选定一个已存在的 Git 仓库作为协调仓库，`.tsunagou/` 是项目协调数据的中心位置。
- 八大模块处理项目与权限、Agent 接入、任务、认知协商、资源、工作空间、持久化、观测与评估。
- 后续 Web 工作台可接入同一公共 API；本次不开发 Web UI。
- 用户可以直接告诉正在目标业务项目中工作的 Agent“在这个项目里从 GitHub 安装 Tsunagou”；安装 skill 会保存当前 Git 根，克隆独立源码 checkout，安装锁定的 Python/Node 依赖，构建 stdio bridge，并把该项目显式传给 installer。项目未初始化时 installer 自动执行一次 `project init`，随后执行 `project bootstrap`；不指定项目根时仍保持 source/skill-only 安装。
- 项目 bootstrap 在项目内生成无秘密的 `AGENTS.md` 受管区块、项目 skill、Agent context 和来源 manifest；这些入口引用 Tsunagou checkout/规范，但不复制源码。`.tsunagou/local`、token、ticket、session 和 SQLite 仍是本机私有 runtime，daemon 启动和 Agent enrollment 仍由 onboarding 继续完成。

## 系统解决什么，Agent 负责什么

| 问题 | 系统提供的机制 | 人或 Agent 的判断 |
|---|---|---|
| 任务重复领取、旧连接继续操作 | 原子 claim、版本检查、会话与 epoch 隔离 | 主 Agent 拆分任务与选择协作者 |
| 接口理解不一致 | 认知报告、分歧对象、契约版本和接受记录 | LLM 解释差异、协商内容 |
| 改同一资源造成冲突 | ResourceIntent、Lease、已知范围冲突提示 | 选择隔离级别、处置真实冲突 |
| 用户暂时不回复 | 持久化待决事项、黑板、依赖阻塞与恢复 | 无关任务继续；相关 Agent 正常结束本轮并挂起 |
| 断线、换人、进程崩溃 | 收件箱、幂等命令、Operation、checkpoint、继任协议 | 对不确定结果做证据判断 |
| 主子 Agent 权责混淆 | 独立会话令牌、五类 Grant、固定 user-only 命令 | 用户任命主 Agent、设定上限与重大决策 |
| Git 变更不可追溯 | manifest、checkpoint、只读锚点验证 | 主 Agent 执行所有 Git 写操作与整合 |

## 产品边界

不实现通用自治 Agent 框架，不调用模型供应商代替宿主推理，不推断隐藏思维，不承诺天然理解所有语义分歧。不内建代码审查、部署或完整 IDE；这些由 Agent 与外部工具完成。

Full Access 宿主中的文件和命令行为，可能只能通过自然语言约束和事后观察协调。后端能严格约束的是自身 API、主体身份、授权范围和持久事实；不能把逻辑权限说成操作系统沙箱。首发不防御同一 OS 用户主动读取凭据或直接篡改数据库的恶意行为，也不提供远程、多租户认证体系。

项目特色在于把协作协议、认知协商、持久收件箱和可恢复状态放在同一后端，同时把业务判断交给主 Agent、把用户保留给真正需要指导的节点。

## 子 Agent 是怎样的项目成员

子Agent拥有独立宿主对话、身份与TaskAttempt：读取黑板、公开理解、领取任务、申请资源、参与契约并提交自己的结果。它不仅是main接收输出的临时执行器，也可以发现范围遗漏、指出认知冲突、挂起相关工作并在之后恢复。

用户通过adapter把多个会话接入同一project；worker票据和独立session由系统/bridge管理，不需要把秘密粘贴给模型。ready代表可以协调，claim代表领到任务，start才代表可以在当前范围执行。用户任命main后，普通委派和协商尽量由main与子Agent自行完成。

消息发送会先持久化到 daemon 收件箱，连接中的 Agent 在下一次 `inbox__claim`/黑板读取时可见。A2A `message/send` 还可携带标准 `taskPushNotificationConfig`，让 daemon 在提交后向宿主 adapter 的 HTTP receiver 发异步通知；这证明的是 callback 投递，不等于 generic stdio bridge 已能反向启动或唤醒休眠 Codex 对话。阶段 A 先通过 Tsunagou-managed app-server 验证真实唤醒，阶段 B 再允许用户显式提供已有 Codex thread 和公开 Unix socket 进行 attach。官方 listener 已实测能够恢复一个由 Codex Desktop 创建的既有 thread，并由 Tsunagou A2A 产生 `thread_resumed`/`turn_started`；运行中的 Desktop stdio 进程仍不提供自动 discovery，缺少显式 endpoint 时继续保持 pull-first，不丢消息。

具体接入步骤、主子职责与恢复情形见[子Agent指南](subagent-guide.md)，操作命令见[简明手册](cli-http-manual.md)。

十分钟演示路径、当前宿主 gate 和实验限制见[本机演示](demo.md)。
