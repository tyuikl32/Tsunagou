# PT5 实施步骤

1. 补齐 query DTO、CLI help、HTTP route 与统一错误；保持现有命令语义。
2. 验证超过 200 条、边界时间、unknown time、无效/过期 cursor、actor、私信和 artifact 越权。
3. 验证 CLI/HTTP 等价和 JSONL 导出；查询失败不写事件、不推进 revision。
4. 将命令示例与 `docs/overview/cli-http-manual.md`、command catalog 同步。
