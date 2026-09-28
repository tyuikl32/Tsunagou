# PT1 实施步骤

1. 读取 backend/database/protocol/command 规范，列出当前字段与缺口。
2. 先更新 schema、SQLite migration、事件写入和 query DTO，再更新 CLI/HTTP 映射；保留旧字段读取兼容。
3. 添加 UTC、unknown、跨时区、actor 隔离、command retry/conflict、超过 200 条游标分页 fixtures。
4. 跑模块测试、协议 fixtures、文档校验和 `git diff --check`；把真实命令和退出码写入本文件。

禁止在 PT1 直接迁移外部项目或生成生产凭据；临时验收项目可生成自己的测试凭据。PT2 依赖本任务验收。

## 当前交付与检查

记录时间：2026-09-27T16:41:06.922Z。实现审计包络、实体时间、实际命令/主体/会话归因、稳定有界分页、私信权限、Schema/Python/TS/OpenAPI，以及 `project history` 的人类/JSON 输出。旧记录未知时间保持 null。

全量 Python 测试、Ruff、mypy 和真实双 bridge 进程烟测已通过，独立 reviewer 又修复了旧 payload 证据引用过滤与非法时区/溢出输入；最终关闭前仍需复核其结果和文档校验。具体命令、退出码、基线提交、工作树文件 digest 和烟测对象 ID 见 [verification.json](research/verification.json)。

PT4 接手事务提交后的物化/错误窗口和 Operation/Job 独立状态审计，PT3 接手 ArtifactRef 的领域授权，PT2 接手凭据交付和旧库秘密清理。上述后续缺口已写入相关任务，不把 PT1 合同层测试冒充整个 PT 计划通过。

## 验收结论

2026-09-27T16:44:11.587Z：PT1 通过并完成。独立 trellis-check 复核修复 3 类问题，最终相关 42 项测试通过；全量 Ruff、mypy、pnpm check、协议/文档校验和生成一致性通过。真实进程烟测在临时项目完成，未修改用户运行项目。PT1 交付为统一审计契约、实体元数据和可读时间线；PT2–PT6 继续补齐具体交付/附件/Operation/Job/传输领域集成，父任务保持进行中。
