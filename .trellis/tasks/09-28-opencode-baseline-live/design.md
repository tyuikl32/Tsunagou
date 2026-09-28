# 设计

## 关键发现

OpenCode v2.0.18 不给 MCP server 传递 session id 环境变量，但通过 MCP 工具调用的 `_meta` 字段传递 `ai.opencode/sessionID`。bridge-server 当前只从环境变量读取 host identity，需要扩展支持 OpenCode 的 `_meta` 传递。

## 架构决策

1. **bridge 修改**：在 `CallToolRequest` 处理中从 `_meta["ai.opencode/sessionID"]` 提取 host identity digest，用于会话隔离和连续性验证
2. **会话模型**：每个 OpenCode session id 对应一个独立的 bridge session（独立 Agent、Session、凭据）
3. **MCP 配置映射**：`agent connect` 生成 bridge_config 后，手动映射到 OpenCode 的 local MCP 配置（`opencode.json` 的 `mcp` 字段）

## 测试环境

- 临时 Git 协调项目（独立目录）
- 真实 daemon（tsunagou daemon start）
- stdio MCP bridge（bridge-server/dist/server.js）
- 真实 OpenCode 会话（opencode run）

## 双 profile 隔离

- main profile: `tsunagou-main`
- worker profile: `tsunagou-worker`
- 各自独立的 bridge-session.json 私有文件

## 数据流

```
opencode run → MCP _meta.sessionID → bridge 提取 digest → 查找/创建 bridge session → HTTP daemon
```
