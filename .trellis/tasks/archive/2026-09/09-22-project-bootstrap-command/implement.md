# 项目初始化与安装脚本联动实施计划

1. 先合并 `project-local-contract` 的 schema/template API 和 fixtures。
2. 在 `src/tsunagou/application/project_integration.py` 增加 integration service 与文件原子写工具；补 Windows 路径、编码和锁处理。它属于技术组合层，不是第九个业务模块。
3. 在 `src/tsunagou/cli/app.py` 注册 `project bootstrap`，加 JSON/人类输出、冲突码和返回值。
4. 更新 installer/onboarding skills 的顺序与参数；保留现有安装行为兼容。
5. 增加 CLI 集成测试：无 daemon、有 daemon、错误 project root、重复运行、两个项目共享 daemon。
6. 增加 secrets/路径扫描，确认 endpoint/token/session 不出共享文件。

验证命令：

```powershell
uv run pytest tests/unit tests/integration -q
python tools/docs/validate_docs.py
python tools/dev/smoke_standalone.py
git diff --check
```

已实现 `project bootstrap`、`--refresh`、`--force-managed` 和 installer 的显式 `--project-root/--host` 联动。dry-run 会列出 bootstrap 命令而不写项目；真实 CLI smoke 已覆盖首次生成和重复 unchanged。
