# Git 远端操作的执行边界

> 核对日期：2026-09-17。
> 状态：第 160 题选择 C，用户随后澄清为“主 Agent 控制 Git”。D83 因此规定 daemon 不访问 remote，当前主 Agent 负责执行并报告。下文选项 A 的 daemon 联网细节仅保留为被否决方案研究记录。

## 为什么这是权限决策

`git ls-remote`虽然不修改仓库，却会连接外部地址、读取 Git 配置、调用传输程序和凭据 helper。Git 的[凭据文档](https://git-scm.com/docs/gitcredentials)说明 helper 是可执行的外部程序，有些 OAuth helper 会打开浏览器；[Git 环境变量文档](https://git-scm.com/docs/git#Documentation/git.txt-codeGITTERMINALPROMPTcode)只保证 `GIT_TERMINAL_PROMPT=false` 时不在终端询问，并不自动禁止所有 askpass/helper 交互。

因此 daemon 是否主动做远端验证，会影响网络隐私、凭据行为、代理/SSH 环境和后台可靠性。它应由明确策略决定，而不是普通 polling 实现细节。

## 选项

| 选项 | 联网时机 | 优点 | 代价 |
|---|---|---|---|
| A（已否决） | daemon 不周期性联网；仅显式 remote verify，或用户发起且声明需要新鲜发布证据的高影响操作中执行 | 无意外后台联网；证据需要时仍可自动完成；失败不会干扰普通协作 | 仍让核心接触 remote/credential helper，不符合主 Agent控制 Git 的边界 |
| B | 为配置了 target 的活动项目每 15 分钟后台核验，并保留显式刷新 | 发布状态较新；用户操作少 | daemon 持续访问网络和 credential helper；离线/代理问题产生噪声与资源消耗 |
| C（已确认并澄清） | daemon 永不访问远端；Git 远端操作由当前主 Agent 在其 Full Access 宿主中执行并报告 | 核心不持有 Git 凭据；Git 决策集中到项目管理者；适配不同宿主工作流 | 报告强度受宿主能力影响；旧主 Agent 失联时必须 reconcile 不确定结果 |

## 已确认方案 C 的边界

- daemon 的 Git 命令 allowlist 只包含本地 repository/object/ref/worktree 只读检查；所有修改 Git 或访问 remote 的命令均不在核心应用端口中。
- REST/MCP 不暴露任意 shell 或 remote URL 工具。调度中心向主 Agent 发出语义化 `GitActionRequest`，例如创建 checkpoint commit、发布指定 ref、核验 checkpoint 是否已发布或处理历史分歧。
- 当前主 Agent 绑定 `authority_epoch` 和 Git capability，在宿主提供的 Full Access 环境中执行 add/commit/merge/rebase/fetch/pull/push/远端查询；具体命令、凭据和交互由宿主与主 Agent 管理。
- 调度中心不读取 Git PAT/SSH key/OAuth，不调用 credential helper。主 Agent 返回结构化结果和有限证据；核心可独立验证本地 commit/checkpoint 部分，远端部分的 provenance 为 `main_agent_reported`。
- 主 Agent 报告必须区分 attempted、succeeded、rejected、conflicted、authentication_required、outcome_unknown，并给出 before/after OID/ref。没有报告或宿主中断不能推断失败或成功。
- 用户仍可在系统外手动操作 Git；其后由用户或主 Agent触发 reconcile。任何文案和 API 字段都不得使用无来源的 `published=true`。

## 被否决方案 A 的触发规则（研究记录）

允许启动在线验证的入口只有：

- 用户或具备 `project.durability.verify_remote` capability 的主 Agent 显式调用 remote verify；普通执行 Agent无权触发任意网络目标。
- 用户发起 replica 跨机器切换准备、本机最后副本清理、需要 publication policy 的 archive/reset/fork 等高影响 Operation；命令契约必须在提交前说明会联网。
- 未来 Web 工作台的“刷新远端状态”动作，与 CLI/MCP 调用同一个应用命令。

以下行为不触发网络：普通 `project status`、项目打开、checkpoint 生成、local anchor 自动发现、Agent attach、任务状态转换和后台保留清理。它们只返回缓存 publication evidence、`verified_at` 和 freshness。

高影响 Operation 若已有满足其策略的新鲜 evidence，可复用而不联网。建议首版默认 freshness window 为 5 分钟；项目共享 policy 可以要求更短，local/user config 只能收紧。超时不等于未发布，Operation 进入 `evidence_unavailable`/等待决策，而不是制造否定结论。

## 目标约束

- 客户端不能提交任意 URL。命令只引用已经登记并授权的 `publication_target_id`。
- target 本机绑定至少包含 Git remote name、完整 ref（如 `refs/heads/main`）和脱敏 URL fingerprint；remote/ref 解析结果在命令开始时快照化。
- 使用 remote name 让现有 Git config/credential helper 工作，但在运行前通过 `git remote get-url`/`ls-remote --get-url`解析并核对允许的协议与 fingerprint，防止配置在审批后被替换。
- 首版接受系统 Git 已支持的本地文件、SSH 和 HTTPS transport，但是否允许每类协议由用户/项目 policy 控制；不接受 `ext::` 或未知 remote helper 作为正式发布证据。
- Agent payload、事件、日志和共享文件不得包含含凭据 URL；只记录 target ID、protocol class、host hash/fingerprint、ref 和结果代码。

## 非交互执行

daemon 调用 Git 时：

- 设置 `GIT_TERMINAL_PROMPT=0`，stdin 关闭，使用参数数组并限制总运行时间、stdout/stderr 大小和子进程树生命周期；
- 不传入用户/Agent提供的 `GIT_SSH_COMMAND`、upload-pack、config override 或 helper 名称；
- 不禁用用户现有 credential helper，因为它可能无交互地从系统凭据库返回凭据；但 daemon 不提供 askpass UI，任何需要交互的 helper 都应快速失败并映射为 `authentication_required`/`interaction_required`；
- 不把 token 放进命令行、环境、remote URL、日志或 Operation payload；
- 验证只运行 `ls-remote --exit-code --refs <remote> <full-ref>` 和本地只读对象/祖先检查，不 fetch、pull、push、写 ref 或调用 hooks。

SSH 首次主机信任、OAuth 登录或缺失凭据由用户在自己的 Git 工作流中完成；daemon 返回稳定修复原因，不代理登录页面。

## 结论分类

一次验证必须区分：

- `published_exact`：远端 ref tip 等于 local anchor commit；
- `published_contains`：远端 tip 对象已在本地，且 local anchor 是其祖先；
- `remote_object_missing_locally`：在线拿到 tip OID，但本地没有对象，无法判断祖先；
- `remote_diverged`：双方对象齐全且不能证明 anchor 是 tip 祖先；
- `ref_missing`：成功连接远端，但指定完整 ref 不存在；
- `authentication_required`、`interaction_required`、`transport_denied`、`timeout`、`network_unavailable`、`remote_error`；
- `target_changed`：执行前解析出的 remote/ref fingerprint 与获批快照不一致。

只有前两种提升 publication coverage。`remote_object_missing_locally` 不自动 fetch；返回需要用户显式 fetch 的结构化 prerequisite。网络/认证失败把当前状态标为 unavailable/stale，不能覆盖为 unpublished。

## Operation 与审计

- 显式验证通常是可等待的持久 Operation，以 target 为 `concurrency_key` 合并并发请求；短时间命中 fresh evidence 时可立即完成。
- evidence 记录 command/request hash、target snapshot、observed tip、anchor/checkpoint、verification method、Git version、started/verified_at、duration 和分类结果。
- stderr 默认只保留经分类后的 machine code 与受限诊断摘要；原始远端文本可能含主机名、用户名或路径，不进入普通日志。
- 用户取消只终止本次 Git 子进程；已有 evidence 不回滚。daemon 崩溃后该 attempt 可安全重试，因为验证没有远端副作用。

## 后续待细化

- publication target 是只支持一个 primary，还是首版支持多个 target/mirror 与组合策略。
- target 本机配置 schema、protocol allowlist 和 URL fingerprint 规范化规则。
- 5 分钟 freshness 默认值及各生命周期 Operation 的证据要求。
- Git credential helper/SSH/OAuth 在 Windows 上的故障分类 spike 与子进程树终止测试。
