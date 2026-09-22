# 项目本地 Agent 约束与快速初始化

## Goal

修复“daemon 已经登记项目，但业务项目目录没有任何 Agent 可发现约束”的断层。用户在一个新的 Git 项目中执行一次初始化/安装流程后，项目必须出现可被支持宿主读取的 Tsunagou 项目入口：角色边界、任务领取规则、主 Agent 的 Git 责任、Full Access 的限制、黑板/收件箱优先级、恢复规则和源码/版本引用。一个本机 daemon 仍可同时管理多个项目；项目入口只保存该项目的轻量集成描述，不复制 Tsunagou 源码、daemon 数据库或凭据。

## 已确认事实

- `tools/install/install.py` 目前只安装 Python/Node 依赖和两个 Tsunagou skill；默认目标是 Tsunagou checkout 或用户 skill 目录，不是用户选定的业务项目。
- 当前 `project init` 会建立 `.tsunagou/` 运行状态，但不会向项目写入 `AGENTS.md`、项目 skill、hook 或项目级 Agent 指令。
- 接入 skill 已明确：skill 是操作向导，bridge/daemon 才是身份和权限边界，hook 只是可选便利层。
- 业务项目可能已有 `AGENTS.md` 或宿主配置，初始化不得覆盖用户内容；必须使用带版本标记的受管区块并提供检查/刷新。
- 项目可以包含多个目录和 Git 仓库；协调根只是其中一个根，daemon 的项目注册和 `.tsunagou/` 归协调根所有。

## Requirements

### R1. 项目本地共享入口

初始化在协调根写入以下可提交、无秘密的文件或受管区块：

- `.tsunagou/project-integration.json`：集成 schema/version、project_id、初始化时的 Tsunagou source URL、安装目录提示、源码版本/commit（若可得）、生成器版本和受管文件清单。绝不写 token、endpoint、session 或绝对路径作为唯一真相。
- `.tsunagou/agent-context.md`：面向 Agent 的项目边界、主/worker/user 职责、当前项目入口、daemon 多项目说明和“先读黑板/收件箱再行动”的最小规则；正文必须引用可访问的 Tsunagou 源码/规范位置，并把本机绝对路径标为诊断提示而非可移植依赖。
- `.agents/skills/tsunagou-project/SKILL.md`：平台无关的项目 skill 入口，要求 Agent 读取 `.tsunagou/agent-context.md`，再调用 onboarding skill/bridge；不复制完整 Tsunagou skill 源码。
- `AGENTS.md` 中的 `<!-- TSUNAGOU:START --> ... <!-- TSUNAGOU:END -->` 受管区块；不存在时创建，存在时只插入/更新该区块。区块内容必须与 `agent-context.md` 保持同一生成版本。

可选宿主 hook 或平台专属入口只能在能力已验证且用户明确启用时生成；未验证能力不得伪造为已安装或 enforced。

### R2. 快速初始化命令

- 提供幂等的 `project bootstrap`（或等价明确命令）作为项目本地入口物化动作；`project init` 保持创建 Project 的原语义，并由 onboarding 流程在 init 后调用 bootstrap。
- 命令必须接受协调根、Tsunagou source/install 引用和目标宿主选择；默认只写共享入口，不启动宿主、不创建 Agent、不任命 main、不发布任务。
- 已有受管文件且内容未变时返回 `unchanged`；受管区块被用户修改时拒绝静默覆盖，提供 diff/`--force-managed` 明确刷新路径。
- 初始化/刷新必须可在 daemon 管理的多个项目上分别执行，不能把项目配置写入全局单例或让一个项目读取另一个项目的 `.tsunagou`。

### R3. 安全和边界

- `.tsunagou/local/`、`control.token`、bridge session、ticket、endpoint 和 SQLite runtime 不得进入共享项目入口；生成/更新 `.gitignore` 只能添加带标记的私有规则，不删除用户规则。
- 受管说明必须明确：Full Access 不等于 Tsunagou scope；子 Agent 不能接管 main；主 Agent 负责 Git 写操作；任务必须 claim/preflight/start 后才能执行；ACK 不等于接受；项目完成需用户确认。
- 生成器不得在项目目录复制源码、注入秘密、修改用户 Git 配置、自动创建 worktree，或声称宿主 hook/工具门禁已生效。

### R4. 文档与来源引用

- 用户文档必须给出从 GitHub 安装、选择业务项目、初始化 daemon/project、生成项目入口、接入主 Agent/worker 的连续命令。
- 项目入口至少引用 Tsunagou GitHub URL、安装 checkout 的实际路径（若已知）和规范文档相对路径；路径变化后 `project bootstrap --refresh` 能更新诊断引用，不改变项目身份。
- 文档明确区分：安装 Tsunagou 源码、初始化项目、启动 daemon、bridge enrollment、任命 main、创建/发布任务。

## Out of Scope

- 不在本任务实现远程/多租户认证、OS 级 Full Access 沙箱、动态修改 IDE 机械权限或通用模型注入框架。
- 不把 daemon 的 SQLite、运行日志、ticket、token 或 bridge session 复制进业务项目。
- 不自动创建或发布任务；项目 bootstrap 只建立约束和接入入口。
- 不在未有真实宿主证据时承诺 hook 自动执行；宿主专属支持由独立适配器验收覆盖。

## Acceptance Criteria

- [x] 在全新临时 Git 项目运行一次 documented bootstrap 后，`AGENTS.md`、`.tsunagou/project-integration.json`、`.tsunagou/agent-context.md` 和 `.agents/skills/tsunagou-project/SKILL.md` 均存在，内容包含项目 ID、daemon/source 引用和主从边界，且无秘密。
- [x] 在已有自定义 `AGENTS.md`、已有 `.agents/skills`、已有 `.gitignore` 的项目重复运行，用户内容字节级保留，受管区块只更新自身，第二次运行结果为 `unchanged`。
- [x] `project bootstrap` 不要求源码目录作为 Python import 路径；两个项目的入口文件各自绑定各自的 project integration，不使用全局项目文件。一个 daemon 同时加载多个 project runtime 仍以原运行时任务的实际证据为准，本任务不伪造该能力。
- [x] 源码 checkout 移动或版本升级后刷新只更新来源诊断/生成版本，不改变 project_id、scope、Agent 身份、任务和持久协作事实。
- [x] bridge 接入后的主 Agent 和 worker 能从项目本地入口找到同一套 onboarding 规则；worker 不会因读取入口获得 main 权限，main 也不会因入口绕过 user-only 操作。
- [x] 私有运行数据不会被写入共享入口或日志；文档提供 Windows PowerShell 的从安装到首次接入的可复制命令，且每条命令对应真实 CLI/API。
- [x] Python/Schema/CLI/TypeScript（如改动）测试、`python tools/docs/validate_docs.py`、`git diff --check` 和独立临时项目 smoke 全部通过。

## Implementation Status

父任务已进入 `in_progress`。generic 项目入口、CLI bootstrap、安装器可选联动和自动化验收已实现；宿主专属 hook/工具门禁和 daemon 真正多项目 runtime 不在本次代码改动中宣称完成，仍需各自的实测/运行时任务验收。
