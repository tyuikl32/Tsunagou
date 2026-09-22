# 独立多项目验收实施计划

1. 扩展 `tools/dev/smoke_standalone.py` 或新增专用 `tools/dev/project_bootstrap_smoke.py`，输出非秘密 JSON。
2. 使用 PowerShell 子进程执行真实 `project init/bootstrap/daemon start/status/stop`；禁止设置源码 `PYTHONPATH` 作为成功条件。
3. 在两个临时 Git 项目上共享一个 daemon，分别 enroll/查询 context，断言不串读。
4. 对已有用户文件、并发写、刷新和 source relocation 注入正反路径。
5. 更新首次人工验收手册，命令必须使用已注册 CLI；附源码位置引用和结果目录。
6. 运行全量 Python/TypeScript/schema/docs 检查并保存证据。

最低验证：`uv run pytest -q`、bridge build/check、`python tools/docs/validate_docs.py`、`git diff --check`。

已执行：全量 Python 测试、bridge check/build、package smoke、standalone smoke、CLI bootstrap 首次/重复/refresh、两个临时项目入口隔离测试。证据均为非秘密摘要；真实宿主 hook 自动注入不作为本次 generic baseline 的通过条件。
