# 路径身份、重叠 Roots 与链接边界

> 核对日期：2026-09-17。
> 状态：第 164 题已确认选项 A；作为 D87 的路径身份与重叠 root 基线。

## 风险模型

字符串前缀不能证明路径位于授权 root 内：`..`、不同大小写、8.3 alias、symlink、junction/mount point、UNC 和目录移动都可能改变目标。微软的 [Naming a File](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)明确要求不要假定大小写敏感，并区分 drive/UNC/Win32 namespace；[Reparse Points](https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points)说明 reparse point 会让文件操作偏离普通行为。[GetFinalPathNameByHandleW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)可以从已打开 handle 获取完全解析后的最终路径，包括跨卷 symlink 目标。

另一个问题是策略别名：若 `repo` root 允许写，而其子目录 `secrets` root 拒绝写，调用者不能通过 `fs://repo/secrets/x` 绕过更具体 root。Lease 也必须让两个 URI 指向同一文件时互相冲突。

## 选项

| 选项 | 重叠与链接规则 | 优点 | 代价 |
|---|---|---|---|
| A（推荐） | 只允许显式 parent/child root 重叠；授权取所有适用 root 策略交集并要求最具体 URI；lease 使用解析后的物理资源键；内部链接可按策略跟随，跨 root 链接必须改用目标 root | 支持 monorepo 子域和严格子目录；防止父 root/路径别名绕过；链接行为可审计 | 解析与 TOCTOU 防护复杂；某些宿主只能达到 observed/advisory |
| B | 任意重叠，始终采用最长路径匹配的单个 root 策略；链接只按最终路径是否落入任一 root 判断 | 实现和使用较简单 | 子 root 可能意外扩大父 root 权限；同一资源的租约/审计身份易分裂 |
| C | 禁止任何 root 重叠，并禁止所有 symlink/junction/reparse traversal | 边界最简单 | Windows 开发环境、monorepo 和工具链常见链接无法使用；用户需要拆分/复制目录 |

## 选项 A：Root 层级

- 重叠 roots 必须在 shared manifest 中声明 `parent_root_id`；物理 binding 验证 child 的最终目录确实位于 parent 内，或是被批准的独立 target binding。
- 两个没有祖先关系的 active roots 不得绑定到重叠/相同物理目录。检测到时标记 `binding_overlap_conflict`，相关写任务阻塞。
- 一个路径若落入多个 root，canonical logical identity 使用最具体 active root。通过 ancestor URI 访问 child 范围返回 `canonical_root_required` 和允许披露的 child root ID。
- 有效权限取 project/user/main-agent/task grant 与所有 ancestor-to-child root policy 的交集；deny 取并集。child 只能收紧，不能扩大 parent 上限。
- root retire 后旧事件/任务仍按原 root ID显示；新请求只能使用当前 canonical root。rebind/层级变化是 revision-protected project command，并触发受影响任务与租约重评。

合法用途包括将整个 monorepo 登记为 source root，再把 `infra/`、`secrets-template/` 或某子团队目录登记为更严格 child root。纯显示别名不创建第二 root；用 display label/alias metadata 解决命名需要。

## Wire Path 与逻辑解析

- 对外资源 URI 保持 `fs://<root_id>/<percent-encoded-relative-path>`；wire path 使用 `/`，不接受 drive、UNC、设备 namespace 或绝对路径片段。
- relative path 必须为 UTF-8、非空合法 segments；拒绝 `.`、`..`、空 segment、NUL、反斜杠混写及平台保留设备名/歧义尾随形式。
- URI percent-decode 恰好一次；解码后再做 segment validation，拒绝编码分隔符造成的路径重分段和非规范重复编码。
- 客户端不提交本机 canonical path。服务端从已验证 binding 构造目标，并返回 canonical root/path/resource key。
- wire 文本保留真实文件名用于展示；授权/冲突匹配依据 binding 探测的文件系统大小写语义。Windows 不确定时采用保守 case-insensitive 冲突键，不能因大小写差异授予额外能力。

## 物理解析

### 已存在目标

1. 从已打开且已验证的 root directory handle 开始逐段遍历，不先拼完整字符串再相信结果。
2. 检查每一段的文件类型、reparse/link 状态与允许的 follow policy；限制链接深度并检测循环。
3. 获取最终 handle path、volume/文件 identity 与 parent chain，确认仍落在预期 root/repository/binding。
4. 生成 `PhysicalResourceKey`：binding/filesystem identity + object file ID（可用时）+ canonical path fallback。
5. 在执行 I/O 或 Git action 前再次验证 binding revision 和关键 handle identity，降低检查后替换风险。

### 尚不存在目标

- 解析并打开最近存在的 parent，验证其物理身份；对剩余 segments 进行严格词法检查。
- intent/lease 资源键使用 parent physical identity + filesystem-normalized remaining path。
- 创建时使用拒绝意外 link/reparse 替换的 API/flags；创建后立刻读取最终 handle identity并与预期键核对。
- parent 在 preflight 与执行之间改变时返回 `path_identity_changed`，不在新位置继续。

具体 Windows handle API 封装应位于 platform infrastructure；domain/application 只消费解析结果、证据和 enforcement strength。

## Symlink、Junction 与 Reparse Policy

默认 shared policy 为 `follow_links = "within_root"`：

- 最终目标仍在同一 canonical root、没有跨越更严格 child boundary 时允许，并在证据中记录 link chain 摘要。
- 目标落入另一个已登记 root 时，不通过源 URI继续；返回 `cross_root_link`，调用者必须以目标 root URI重新授权、获取 lease 和访问。
- 目标落在所有已登记 roots 外时拒绝 `root_escape`，即使主 Agent宿主 Full Access；若 Agent绕过工具直接访问，只能标为 advisory/observed violation。
- 未知 reparse tag、循环、超深链、断链和无法取得最终 identity 默认拒绝。项目 policy 可以进一步设置 `deny_all`，不能对普通 Agent放宽到任意 root 外目标。
- root binding 本身可以由用户显式选择一个 link/junction 路径，但登记时保存输入路径和最终目标 identity；目标变化使 binding 失效，不静默跟随到新位置。
- UNC/network root 必须显式 binding；不允许从本地 root 的链接首次发现并自动授权网络位置。

## Lease 与别名

- ResourceIntent 接受 logical URI，但获得 lease 前统一解析为 logical canonical identity + `PhysicalResourceKey`。
- 文件、目录、glob/range lease 的冲突索引建立在物理键和祖先区间上；ancestor/child URI、大小写 alias 和允许的内部链接会产生冲突。
- 对尚不存在路径使用 parent+segment key；目标创建后迁移到 file identity 时保持原 lease ID，并检查是否与既有 alias lease 冲突。
- hard link 的现有文件若能取得相同 file ID则视为同一资源。系统无法穷举 root 外所有 hard links，因此发现 link count >1 或 identity 能力不足时降低机械保证并在写任务风险评估中暴露。
- Git index/pathspec 仍使用 repository-relative规范路径；进入 GitActionIntent 前必须从 physical key 反向验证其唯一 repository/path，避免不同 root alias 重复 stage。

## Enforcement Strength

- 调度中心自己的文件读取、manifest/hash 与 workspace 管理使用上述解析器，可达到 gated；真正强隔离仍需 isolated workspace/OS boundary。
- 通过 bridge 提供的受控文件工具可以做 gated；宿主原生 Full Access shell 无法机械拦截，最多 observed/advisory。
- 每次任务 preflight 记录 path-resolution capability、link policy 与实际 strength。任务要求高于宿主能力时不能静默分派，可按既有风险降级规则由主 Agent/用户处理。

## 后续待细化

- Windows handle/file-ID 封装、网络 share、case-sensitive directory 和长路径测试矩阵。
- POSIX `openat`/`O_NOFOLLOW`、macOS normalization/case 行为的兼容实现。
- `PhysicalResourceKey`、link-chain evidence 和 canonicalization error 的完整 schema。
- glob/directory/range lease 的祖先区间索引与并发算法。
