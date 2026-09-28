# PT7 设计

created_at: 2026-09-27T14:39:38Z

验收分三层：脱敏 fixture 验 schema/秘密/故障，临时项目验两个 Agent/文件/Git/restart，真实项目仅在用户确认后执行 dry-run、备份、迁移和恢复。每层产出 JSONL evidence，字段包括时间、HEAD、版本、命令、退出码、actor、scope 和引用。

整体关闭门必须同时看到 PT1–PT6 的通过记录、secret scan、cursor/权限、Git anchor、clone 权限清理、Windows 操作和文档校验；能力未知或宿主诊断不能写成支持。
