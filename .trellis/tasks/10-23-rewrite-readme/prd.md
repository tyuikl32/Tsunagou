# 重写项目 README

## Goal

把根 `README.md` 改成面向实际使用者的项目入口。第一次接触 Tsunagou 的个人开发者应能理解它解决的问题，并完成安装、Agent 接入和第一次协作。

## Background

- Tsunagou 是面向多个独立 Coding Agent 会话的协作后端，持久保存项目、Agent、任务、范围、消息、契约、执行结果和恢复状态。
- 用户决定项目目标、允许哪些新 Agent 加入、重大设计和项目完成；main Agent 负责日常拆分、派发、验收和 Git 写操作；worker 只在自己的 Attempt 和 scope 内工作。
- 根 README 当前混合安装入口、历史测试计数、已知失败、实测修复进度和开发文档导航，缺少一条连续的首次使用路径。
- 详细材料已存在于 `docs/overview/agent-quick-start.md`、`docs/overview/user-guide.md`、`docs/overview/subagent-guide.md`、`docs/overview/cli-http-manual.md` 和实施文档，README 应提炼并链接，不复制整份手册。

## Requirements

- 首要读者是准备实际使用 Tsunagou 的个人开发者。正文按“解决的问题 → 工作方式 → 快速开始 → 首次协作 → 跨机器 → 使用边界 → 详细手册”排列。
- 开头直接说明多个 Coding Agent 缺少共享任务事实、范围、决定和恢复状态的问题，以及 Tsunagou 保存这些事实的作用。
- 用完成接入所需的最少内容解释 project、daemon、Web 控制台、main Agent、worker 和 bridge 的关系。
- 默认安装入口是让目标业务项目中的 Agent 从 GitHub 安装 Tsunagou、为当前项目完成 bootstrap，并报告控制台地址。提供一段可直接复制给 Agent 的指令。
- 手动克隆和 `tools/install/install.py` 作为备用安装入口，只写使用者必须知道的运行前提和命令。
- 安装后的主入口是本机 Web 控制台。CLI 只用于启动、状态检查、诊断和高级操作，并链接完整命令手册。
- 快速开始必须区分用户动作与 Agent 动作，并连续覆盖：打开控制台、创建或选择项目、由用户选择并接入一个 main 和一个 worker、在各自原对话中完成接入、读取项目上下文确认 ready。
- 首次使用必须走完最小协作闭环：用户与 main 确认项目目标，main 创建并分派任务，worker 执行并提交，main 验收，用户在控制台查看任务、结果和待决事项。
- 跨机器只说明主机运行 daemon/控制台、远端通过邀请接入、两端协议版本必须一致，并链接完整虚拟机步骤。
- 明确用户保留项目目标、新增 Agent、重大设计和项目完成决定；main 负责普通调度与 Git 写操作；worker 只处理自己的 Attempt 和 scope；Full Access 不扩大 Tsunagou 权限范围。
- 语言简洁、直接，不使用类比、比喻、营销套话或机械化总结。

## Acceptance Criteria

- [x] 读者在前两屏内能回答：项目解决什么问题、它保存哪些协作事实、它不负责什么。
- [x] README 包含一条从 Agent 主导安装到 main/worker ready 的连续单机路径，命令与当前 installer、CLI 和控制台行为一致。
- [x] README 包含可观察的首次协作闭环：目标已确认、任务已分派、worker 已提交、main 已验收、控制台可查看结果。
- [x] README 准确说明用户、main、worker 和 Tsunagou 的权限边界。
- [x] README 的跨机器部分保持简短，并链接到完整操作步骤。
- [x] README 不包含历史计划、测试数量、失败清单、发布门禁、FX 状态、实现进度或内部实现结构。
- [x] README 不包含开发状态、开发验证命令或贡献者构建流程。
- [x] 所有本地相对链接存在，`python tools/docs/validate_docs.py` 通过。
- [x] 文风简洁、直接，无类比、比喻、营销套话和大段内部实现细节。

## Out of Scope

- 重写 `USER_MANUAL.md` 或 `docs/` 下的详细手册。
- 修改产品代码、协议、CLI 行为或接入流程。
- 修复当前缺失的 `.tsunagou/agent-context.md`。
- 说明测试门禁、FX 任务、实现进度、发布状态、源码构建或贡献流程。
