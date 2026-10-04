# 实施进度

## 2026-10-03

- 用户明确批准已确认方案实施及创建 Trellis 任务；首次安装允许重载原对话一次。
- 源码目录没有 `.tsunagou/agent-context.md`，未进行产品项目登记或将开发子代理登记为项目成员。
- 产品代码修改前执行本机 OpenCode 2.0.18 宿主预检。CLI 确认支持 `mcp add --global`，但安装包插件 API 与上游 dev 文档不同，正在进行隔离探针验证。
- 使用 `uv sync --extra dev --frozen` 补齐已锁定开发依赖，没有改动依赖清单。
- 修改前基线：相关 Python 单元测试 183 项通过（console_join、enrollment_store、host_registration_opencode、console_enrollment、agent_pending、onboarding_request、host_registration_deepseek）；DSH provider Node 测试含子项 14 项通过。
- 未修改产品代码，未提交 Git。真实宿主预检尚未完成，不能报告本功能可用。

## 前置门禁通过，开始实现

真实 OpenCode 2.0.18 + 本地可控模型响应验证：用户级目录插件执行、ctx.sessionID 与原生 MCP 元数据一致、reload 后同 ID。详见 research/opencode-v2-preflight.md。原始临时探针已移动到系统临时目录，仓库只保留精简研究。

宿主薄工具/安装模块与后端 CLI/路由/回执分工实施；产品级完整接入验收待执行，不能用宿主接口预检替代。

## 实现及完整隔离验收

- 用户级 prepare、无参数宿主工具、OpenCode join、私有路由、控制台申请和精确到达回执已实现，沿用现有状态和页面。
- 真实 OpenCode 2.0.18、实际 CLI/daemon/bridge/控制台服务通过 12 项隔离检查；包含中文无关目录、第二会话隔离、重复接入、helper 等待、原生 MCP 到达和重载身份保持。仅模型为本地可控夹具，没有人工浏览器验收声明。详见 research/opencode-live-acceptance.md 及 docs/acceptance/opencode-original-chat-2026-10-03.md。
- 首次重载后 MCP 存在短暂加载时间；等待连接完成后通过，没有新增兼容层。
- 原始探针及完整运行目录已安全移至系统临时目录，仓库只保留脱敏证据。临时服务已停止，未修改真实用户全局配置或既有项目。
- 相关单元测试 139 项、DSH 回归 30 项、daemon/bridge 集成 8 项、bridge 回执 10 项通过；新宿主安装 8 项、插件 Node 3 项、既有 OpenCode adapter 4 项通过。独立复核相关 Python 107 项及全部 7 个修改 Python 源文件 Ruff/mypy 通过，根工作区 TypeScript check 通过。上述集合有重叠，不相加作为总数。
- 独立复核发现并修复 CLI 类型参数问题；旧绑定跨项目漏检使用现有项目索引补充只读检查，后续回归单独记录。
- 没有 Git 提交。保留任务记录和工作树供用户审阅；不自动执行归档提交。

## 最终复核

- 已补充索引项目的只读旧绑定保护及两项回归；相关单元和真实 daemon/bridge 集成共 25 项通过，Ruff/mypy 通过。未登记或已移动旧项目的检测边界已同步用户指南。
- 最终文档校验通过：418 Markdown、1081 本地链接；保留 Windows CRLF 语义的 diff whitespace 检查通过。
- 实施与约定验收完成，任务标记完成但不执行 Git 提交或自动归档提交。
