# 项目本地 Agent 约束与快速初始化设计

## 1. 边界

Tsunagou 分成两个持久化层：

1. **共享项目集成层**位于目标协调根的 `.tsunagou/`，随项目保存，不包含秘密。它告诉任何宿主 Agent“这个项目受哪个 Tsunagou 项目约束、规范入口在哪里、如何继续接入”。
2. **daemon runtime 层**仍由一个本机 daemon 管理多个项目。每个项目的 `.tsunagou/local/` 保存 endpoint、control token、SQLite 和 bridge 私有资料；这些只服务本机运行，不进入共享入口。

安装 Tsunagou 的 checkout 是第三个位置。项目集成文件只记录 GitHub source、版本/commit 和可选的本机诊断路径，不能把 source checkout 当作项目运行时真相，也不能复制源码。

## 2. 物化文件模型

```text
<coordination-root>/
├── AGENTS.md                              # 用户正文 + 受管 TSUNAGOU 区块
├── .agents/skills/tsunagou-project/
│   └── SKILL.md                            # 轻量项目入口，不复制完整发行 skill
└── .tsunagou/
    ├── project-integration.json            # 共享、无秘密、版本化
    ├── agent-context.md                    # 生成的人类/Agent说明
    ├── .gitignore                          # 仅追加受管私有规则
    └── local/                              # 本机私有 runtime，默认忽略
        ├── endpoint.json
        ├── control.token
        ├── state.sqlite3
        └── bridges/<conversation>/...
```

`project-integration.json` 使用稳定字段：`schema_version`、`project_id`、`project_root_id`、`source.repository`、`source.ref`、`source.commit`、`source.install_path_hint`、`generated_by`、`managed_files`、`updated_at`。`install_path_hint` 只能是诊断字段，导入项目或换机器时可为空；不能用它解析 daemon 或认证。

`agent-context.md` 和 `AGENTS.md` 共享同一 `generator_version` 与 `content_digest`。Agent 发现 digest 不一致时优先运行 `project bootstrap --refresh` 或请求 main 处理，不自行编辑受管区块。

## 3. 命令与数据流

推荐新增用户命令：

```text
tsunagou project bootstrap \
  --coordination-root <path> \
  [--source-root <tsunagou-checkout>] \
  [--source-ref <tag-or-commit>] \
  [--host codex|opencode|deepseek|generic ...] \
  [--refresh]
```

命令通过现有项目/daemon 选择逻辑读取 `project_id`，校验协调根和项目绑定，生成共享文件，再返回每个目标的 `created|updated|unchanged|conflict`。它不接受或输出 control token、ticket、session token、endpoint secret，不执行 Agent enrollment 和 authority appoint。

`project init` 保持只做项目事实初始化；onboarding skill 在 init 成功后明确调用 bootstrap。安装 skill 负责获取 Tsunagou checkout 和运行依赖，不能猜测用户业务项目；当用户说“在当前项目启用 Tsunagou”时才调用 bootstrap。

## 4. 受管文件更新算法

1. 读取原文件和受管标记；不存在则创建。
2. 对 `AGENTS.md` 只替换 `TSUNAGOU:START/END` 区块；标记缺失但文件非空时以冲突返回，不整文件覆盖。
3. 对项目 skill/context/manifest 使用 canonical JSON/Markdown 生成；相同 digest 返回 `unchanged`。
4. `.gitignore` 只在 `TSUNAGOU:START/END` 区块内追加私有路径；用户已有规则保持原样。
5. 先用由协调根 digest 派生的系统临时锁串行化 bootstrap，再完成所有冲突预检；只有预检全过才写文件。每个文件使用临时文件、fsync（平台可用时）和原子替换，失败不因用户冲突留下半套物化结果。
6. `--refresh` 只能更新受管字段和来源诊断；不能修改 project_id、项目范围或历史协作事实。

## 5. 宿主策略

项目级通用入口是首发硬要求；宿主专属目录只在适配器明确声明可发现且已验证时生成。Codex 首先依赖项目 `AGENTS.md` 和 `.agents/skills`；OpenCode/DeepSeek 使用同一 project context 的等价入口或生成明确的手动加载说明。Hook 仍是可选增强，不能作为项目已经受约束的证明。

## 6. 兼容、迁移和回滚

- 旧项目没有集成文件时，bootstrap 是新增操作，不改变已有 daemon/SQLite 数据。
- 已有旧 `.tsunagou` 目录时，只补缺失文件；检测到非 Tsunagou 同名文件或受管区块冲突即停止并报告。
- 删除项目入口不会删除 daemon 项目、任务、Agent 或 runtime；提供 `project bootstrap --remove-managed` 时只移除带 digest 的受管内容，默认不实现自动删除。
- source checkout 移动只需刷新 `source.install_path_hint`；bridge/daemon 仍通过 endpoint manifest 和项目 ID工作。

## 7. 关键风险

- 某些宿主忽略项目 skill：必须仍能通过 `AGENTS.md` 和 onboarding 文档完成最小流程，并把宿主能力标为 advisory/unknown。
- 用户误把 `.tsunagou/local` 提交：生成器必须稳定写入忽略规则，doctor/验收扫描必须报警。
- 多 Agent 同时 bootstrap：用项目文件锁/原子替换和 digest 幂等，不能生成交叉版本。
- source path 不可移植：只作诊断提示，规范 URL 和项目相对文档路径才是共享真相。
