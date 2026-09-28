# 实施计划

## 阶段 1：环境准备

1. 创建临时协调项目目录
2. 启动真实 daemon
3. 构建 bridge-server
4. 运行 `tsunagou agent connect --adapter opencode` 生成 ticket 和 bridge_config（main + worker 两个 profile）

## 阶段 2：代码修复

1. 修复 bridge 的 OpenCode `_meta` session id 提取
2. 修改 `_write_bridge_config` 添加 adapter 标识
3. 运行 bridge-sdk 和 bridge-server 测试

## 阶段 3：MCP 配置映射

1. 将 bridge_config 映射到 OpenCode local MCP 配置
2. 验证 MCP server 启动和工具列表

## 阶段 4：11 项实测

按顺序逐项测试，每项记录：
- 期望结果
- 实际结果
- 负例（如有）
- 脱敏证据引用

## 阶段 5：证据整理

1. 写入 docs/research/evidence/opencode-2026-09-28-live.json
2. 更新 adapter-opencode.md 文档
3. 记录 Git commit 标识

## 验证命令

- `corepack pnpm --filter @tsunagou/bridge-server run check`
- `corepack pnpm exec vitest run packages/bridge-server/tests`
- `python tools/docs/validate_docs.py`
