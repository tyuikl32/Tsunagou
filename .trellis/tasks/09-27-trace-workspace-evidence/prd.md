# PT3 工作区差异与验证证据

- created_at: 2026-09-27T14:39:38Z
- status: planning；parent: persistence-traceability；depends_on: PT1

## 目标

记录实际允许 scope 内的内容变化和验证来源，阻止 patch 递归、范围外采集、错误 digest 和“提交者就是逐行作者”的过度断言。

## 范围与约束

- digest 必须基于允许路径的相对路径、内容、类型/模式和必要 Git 状态；同一路径内容变化必须改变 digest。
- 结果绑定 project/lineage/workspace、scope、baseline/result digest、提交 actor、观察时间和工具版本；排除 `.tsunagou/local`、bridge 私密文件、未提升附件和范围外路径。
- `agent_asserted`、`host_observed`、`system_verified`、`user_confirmed` 四级证据不可混用；共享工作区不生成逐行作者证明。
- 外部传入 ArtifactRef 必须重新验证 owner、scope、content digest 和 domain，不得覆盖系统扫描结果。

## 交付与验收

1. 加入 tracked/untracked、同名不同内容、范围外、symlink/异常文件和 patch 重复输入 fixtures。
2. 验证 artifact 查询先做 project/domain/private recipient 授权；不得仅凭 hash 读取。
3. 验证验证回执包含开始/结束时间、命令、退出码、版本 digest、证据等级和安全输出摘要。
4. 生成不含绝对路径和秘密的可审计 result manifest，并把弱证据限制写入 CLI/HTTP。

## 不做

不实现逐行作者追踪、强制容器/Worktree、全量终端录制或新的文件隔离后端。
