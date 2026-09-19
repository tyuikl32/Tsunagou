# T23 执行步骤与交接

## 开始前

- [x] 检查依赖 T15, T16, T17, T22 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认 Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；当前任务为 in_progress，分支为 `elysia`。

## 实施步骤

- [x] 实现 validation 列出的核心故障子集，使用真实临时 SQLite、持久 inbox 和 loopback
- [x] 覆盖消息恢复、单 owner、旧 epoch、崩溃回滚和未知发布 gate
- [x] 校验命令 registry/OpenAPI/架构与生成物公共门槛
- [ ] 记录 Windows 完整基准和 macOS/Linux 实际支持范围（待对应环境运行）

## 检查

- [x] 无消息丢失/双 owner/旧 epoch 授权复活
- [x] 崩溃恢复不伪造成功和不盲重不可验证动作
- [ ] 所有工程阻断项通过，失败有最小复现
- [x] mock adapter 通过不冒称真宿主已完成
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 `python tools/docs/validate_docs.py` 和本任务 `task.py validate`，更新规范与上下文。

## 2026-09-19 首次真实验收

- [x] Python 3.13.15 环境完成同步；pytest 66 passed、1 skipped，Ruff、mypy（40 files）、协议校验（106 policies / 111 schemas）通过。
- [x] 修复 pnpm 12 构建审批占位值，仅允许 `esbuild@0.28.2`；冻结安装通过。
- [x] 修复根 TypeScript 检查指向不存在 `tsconfig.json` 的问题；6 个 workspace 检查、Vitest 19 tests、生成物零差异通过。
- [x] CLI `--version`、doctor、三个 enroll 外壳、临时 Git 项目初始化和 loopback HTTP health 通过。
- [x] Codex `0.155.0-alpha.9` 无模型探针证明初始化和同目录双 thread 隔离；空 thread resume/fork 返回 `-32600`，不得据此提升 ready。
- [ ] OpenCode `1.18.31` 本轮 npm 获取/启动超时，未形成新证据；DeepSeek Harness 未在本轮重跑。
- [ ] `release_check.py` 仍按设计返回 1：Codex 缺 11 项、OpenCode/DeepSeek 各缺 10 项真实共同基线；T23 不完成、不归档。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在 Trellis journal 记录本轮结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
