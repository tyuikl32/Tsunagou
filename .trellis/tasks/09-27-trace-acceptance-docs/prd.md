# PT7 迁移、整体验收与用户操作指南

- created_at: 2026-09-27T14:39:38Z
- status: planning；parent: persistence-traceability；depends_on: PT6

## 目标

将 PT1–PT6 组成一次可复查的验证，给用户一份真实可执行的迁移/启动/恢复/回滚操作单；只有整体证据齐全才关闭父任务。

## 范围与约束

- 先脱敏 fixture，再临时项目，再由用户单独确认真实项目；规划轮不停止 daemon、不改外部 SQLite、不撤销凭据。
- 每项结果记录 `started_at`、`finished_at`、HEAD、daemon/schema 版本、命令、退出码、actor 和 evidence refs。
- 覆盖 Windows 安装/启停、两 Agent 消息与认知协商、结果审查、用户完成决定、重试/崩溃、secret 扫描、workspace、Git clone 和权限边界。
- 文档明确区分已实现、待实施和诊断性证据；未通过项保持 planning/blocked，不冒充完成。

## 交付与验收

1. 完成分阶段 runbook，含 dry-run、备份、停止写入、迁移、integrity、启动、验证、回滚和恢复命令。
2. 生成不含秘密的验收报告和机器 JSONL，上述八类测试每类有可定位证据。
3. 跑 `python tools/docs/validate_docs.py`、Trellis validate、构建/测试和 `git diff --check`；将文档链接和命令目录同步。
4. 由用户明确授权真实库操作后，才执行 credential revoke/迁移/restore；完成后保留用户可读时间线和责问入口。

## 不做

不以一次成功 demo 替代故障窗口，不自动提交 Git，不为未验证宿主能力或远程攻击防护背书。
