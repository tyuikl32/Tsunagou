# 首发交付清单

- [x] Python 后端、协议 registry/schema、生成 Python/TypeScript、OpenAPI 文件存在并可检查。
- [x] 八模块基础服务、task workflow、checkpoint、lifecycle、bridge SDK、四个 adapter 的 diagnostic 代码存在。
- [x] CLI/HTTP、子 Agent 接入、恢复和用户决策文档与当前命令语义一致。
- [x] 单元和集成测试覆盖幂等、旧 epoch、单 owner、pull/ACK、SQLite 回滚和 secret redaction。
- [ ] Codex、OpenCode、DeepSeek Harness 各自 11 项共同基线真实证据；当前 `release_check.py` 明确阻断。ZCode 基线延后，不阻塞首发。
- [ ] Windows 完整发布回归及 macOS/Linux 实际 smoke 记录。
- [ ] A/B/C/D 各至少 5 次、另一宿主复验和公开实验报告。

发布前必须运行：`uv run pytest`、`corepack pnpm -r run check`、`corepack pnpm exec vitest run`、`python tools/docs/validate_docs.py`、`uv run python tools/dev/release_check.py`。最后一项失败时只能交付 diagnostic build，不能宣称三个首发宿主正式支持；ZCode 无论是否存在研究证据都不能被写成首发支持；发布和 push 仍需用户授权。
