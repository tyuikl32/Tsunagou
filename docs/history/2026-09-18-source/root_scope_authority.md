# Root 范围的授权与管理权

> 核对日期：2026-09-17。
> 状态：第 165 题已确认选项 A；作为 D88 的 root 范围授权基线。

## 三层范围

1. **用户本机上限**：用户允许当前 daemon 与当前主 Agent管理哪些物理目录，或明确授予 Full Access。它是 local security input，不进入 Git。
2. **项目逻辑范围**：共享 manifest 中当前有效的 ProjectRoot declarations。它说明项目使用哪些逻辑资源，不等于任一机器已授权或已绑定。
3. **执行授权范围**：主 Agent对普通 Agent、session、TaskAttempt 和 Git action 发放的 capabilities/path selectors。它只能在前两层交集中继续收窄。

任一层缺失都不能由另一层代替。clone 带来的 root declaration 不能替用户在新机器上批准目录；宿主 Full Access 也不能自动扩展项目逻辑范围。

## 选项

| 选项 | Root 管理权 | 优点 | 代价 |
|---|---|---|---|
| A（推荐） | 用户设置本机/主 Agent上限；当前主 Agent在上限内可自主 add/bind/rebind/收窄/retire 普通 roots，并向普通 Agent分配子范围；扩大上限和高敏 identity 变更仍由用户决定 | 主 Agent能实际管理多目录项目；用户保留物理边界；与 authority epoch 和能力交集一致 | 需要精确区分普通变更与高敏变更，并在 Full Access 宿主如实标注逻辑约束 |
| B | 只有用户能新增、绑定、移动或 retire 任何 root；主 Agent只能为任务选择已有 roots | 控制简单、权限最保守 | 多仓库项目的日常路径变化频繁打断用户；主 Agent名义上管理项目却不能维护范围 |
| C | 主 Agent只要宿主 Full Access 就能登记任意物理目录并扩大项目范围 | 自动化最高 | 把用户的宿主访问能力误当成项目授权；一个错误请求可扫描或修改无关目录 |

## 选项 A：用户上限

### `LocalAccessCeiling`

用户级 daemon registry 保存每个项目/replica 的本机上限：

- `ceiling_revision`、project/replica、issuer user principal、created/updated time；
- coordinator ceiling 与 main-agent ceiling 分开表示，最终能力取交集；
- allow roots 使用已验证物理目录 identity + canonical path hint，deny selectors 优先；
- capability 上限区分 read/list/stat/hash、write/create/delete、Git local、Git remote、process/tool 等；
- `full_access=true` 必须是显式用户动作，不能由空 allowlist、通配符解析失败或主 Agent声明推导；
- 可选 expiry 与 reason；收窄/撤销立即生效，扩大只能由用户完成。

上限属于本机，不物化到 `.tsunagou`。共享 project policy 可以进一步禁止某类 root/操作，但不能要求本机扩大访问。

### 收窄与撤销

用户收窄 ceiling 时，核心先写新 revision 并阻止新授权，再找出越界 bindings、sessions、attempts、leases、jobs 和 Git intents：

- 未开始工作取消或阻塞；
- running attempt 进入 `permission_revoked`/cancel_requested，按实际宿主能力尝试通知停止；
- lease/token/grant 失效并递增相关 epoch；
- 外部 Full Access 进程可能继续，记录 residual risk，不能宣称已机械停止；
- root declaration 可以留在共享项目中，但本机 binding 变为 `unauthorized`。

用户扩大 ceiling 只提供新的上限，不自动 add root、恢复任务或给普通 Agent发权；仍需显式项目/binding/attempt 命令。

## 主 Agent可自主处理的普通变更

当前主 Agent必须具有 `project.root.manage`，命令绑定最新 `authority_epoch`、ceiling revision 和 project revision。满足全部条件时可：

- 在 ceiling 内添加普通 source/tooling/generated/artifact/external root 与 repository declaration/binding；
- 将 shared portable hint 绑定到一个通过 path/repository/overlap 校验的本机目录；
- 对相同 filesystem/repository identity 的路径移动执行 rebind；
- 将 root policy 收窄为只读、更小 path selectors、更少 workspace drivers 或更低 capability ceiling；
- retire 没有 active task/lease/contract dependency 的 optional root；
- 给普通 Agent/TaskAttempt 发放 root/path/capability 子集，设置期限并随 attempt/session 终止。

所有操作先由核心硬校验 user ceilings、root hierarchy、physical identity、repository registry、active dependencies 和 shared policy，再作为 revision-protected project command 提交。主 Agent提供意图，不能直接编辑 TOML 绕过验证。

## 必须由用户决定的高敏变更

- 扩大 coordinator 或 main-agent `LocalAccessCeiling`，授予/恢复 Full Access；
- 把现有逻辑 root rebind 到不同 filesystem/repository identity，而无法证明只是同一对象移动；
- 更换 coordination repository/root，改变 project/lineage identity，或解除 `.tsunagou` protected boundary；
- 使一个 root 越过 ceiling、deny selector、跨用户 ownership/trust boundary 或进入设备/系统路径；
- 将 read-only dependency 提升为 writable，放宽 project shared maximum，或允许普通 Agent向未登记 root 外逃逸；
- force-retire 仍被 active task/lease/contract 引用的 root；
- 解决两个共享分支对 root identity、用户权限上限或 main-agent authority 的冲突。

用户批准绑定 proposal digest、旧/新 identity、影响对象、ceiling/project revisions 和短有效期。状态变化后必须重提。

## 普通 Agent 的边界

- 普通 Agent不能 add/bind/rebind/retire root，也不能直接改变任何 ceiling。
- 它可以提交 `RootAccessRequest` 或在认知报告中声明缺少路径；request 包含用途、任务、所需 capability/path、期限和理由。
- 主 Agent只能在现有 ceilings/project roots 内批准子授权；需要新物理 root 时先完成主 Agent或用户级 root 流程。
- grant 绑定 agent/session/attempt、root/path selector、capabilities、expiry、issuer、authority epoch 和 policy digest；默认不可转授。
- 宿主工具若无法机械限制 Full Access，bridge 仍只展示授权 roots/tools，并把执行强度记录为 advisory/observed；违规外部写入进入审计和任务风险状态。

## Clone、离线与主 Agent交接

- clone 导入 declarations，但所有非相对安全绑定先为 unbound/unauthorized；用户本机 ceiling 不从 Git 恢复。
- 主 Agent离线时不自动选主，也不允许普通 Agent管理 roots。用户仍可直接管理 ceiling/binding。
- 主 Agent交接递增 authority epoch；旧主 Agent发出的未提交 root commands/grants/approvals 失效。已生效的普通 Agent grant 按项目策略选择立即撤销或由新主 Agent显式 adopt，后续单独细化。
- shared manifest 中的 root policy 变化若超出当前 machine ceiling，不扩大权限；本机保持受限并报告 incompatibility。

## 后续待细化

- `LocalAccessCeiling`、RootAccessRequest、Grant 和 root mutation proposal 的完整 schema。
- 主 Agent交接时既有 grants 的 adopt/revoke 默认规则。
- capability/path selector 语法、deny/allow 合并和 grant TTL 默认值。
- Windows 系统目录、网络 share、不同 owner/repository safe.directory 的高敏分类清单。
