# 独立多项目验收设计

## 场景矩阵

| 场景 | 关键断言 |
|---|---|
| 空 Git 项目 | init + bootstrap 创建四类入口，无 secret |
| 已有 AGENTS/skill/gitignore | 用户正文保留，受管块可审计 |
| 重复 bootstrap | 无内容漂移，状态 unchanged |
| 两个项目/一个 daemon | project_id、manifest、context、runtime 完全隔离 |
| source checkout 移动 | refresh 只改诊断引用，任务/Agent不变 |
| 无 source root/源码树外 wheel | generic 入口仍可用，来源 URL/版本可查 |
| 受管区块被编辑 | managed conflict，不能静默覆盖 |

验收脚本只调用公开 CLI/HTTP/MCP，不直接 new module service、不改 SQLite。每个项目使用独立临时目录并在 finally 清理进程和文件。
