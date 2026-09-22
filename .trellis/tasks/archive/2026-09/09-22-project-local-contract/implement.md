# 契约子任务实施计划

1. 为 manifest 建 JSON Schema、canonical serialization、未知字段和秘密字段负例 fixture。
2. 编写三类 Markdown 模板和标记解析/替换器；确保换行、编码和用户正文保持稳定。
3. 写入 generic 项目入口的中文/英文简短说明，所有命令链接到已存在的规范，不创造未注册命令。
4. 更新 `docs/implementation/cli-contract.md` 与 `docs/overview/agent-quick-start.md` 的生成文件契约。
5. 增加单元测试：同输入同 digest、受管区块编辑冲突、同项目 ID 校验、秘密扫描、source path 可空。

验证：`uv run pytest tests/unit -q`、schema fixture 检查、`python tools/docs/validate_docs.py`、`git diff --check`。已实现 `project-integration.schema.json`、canonical digest 和入口模板，相关单元测试通过。
