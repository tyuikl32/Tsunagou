# FX1 实施顺序与验证

当前已实施，实际验证和范围见 [implementation-progress.md](implementation-progress.md)。以下保留实施顺序；backend database/error/entrypoint 规范已读取。

1. 在 tests/unit/test_cognition.py 加入终态代理接受、缺 agent_id、重复 slot、错误 slot、部分接受及替代失败回归；使用全新状态。
2. 修改 src/tsunagou/modules/cognition.py 与 application/handlers.py 的 _slot、contract handlers；服务直接调用也不能制造非法状态。
3. 在 tests/unit/test_tasks.py 覆盖 open/blocked/submitted/claimed/running 取消矩阵、非 owner 确认；修改 TaskService 与 handler。
4. 同步 docs/implementation/command-catalog.md、protocol/schemas/commands/contract/ 和相关 fixture。用 rg --files protocol 找到现有样例，不重写无关 schema。
5. 生成 registry、Python/TS 和打包协议资源，检查手写约束未丢失。
6. 新增 tests/integration/test_state_integrity.py：经过应用命令入口验证失败无副作用、幂等、持久化重启与 CLI 时间线。
7. FX2 集成后验证取消的资源/Grant 同事务收口。

PowerShell，工作目录 D:\Tsunagou；这些是实施时执行的命令：
```powershell
.\.venv\Scripts\python.exe tools/codegen/generate_protocol.py
.\.venv\Scripts\python.exe tools/codegen/validate_protocol.py
.\.venv\Scripts\python.exe -m pytest tests/unit/test_cognition.py tests/unit/test_tasks.py tests/integration/test_state_integrity.py -q
.\.venv\Scripts\python.exe -m ruff check src/tsunagou/modules/cognition.py src/tsunagou/modules/tasks.py src/tsunagou/application/handlers.py
.\.venv\Scripts\python.exe tools/docs/validate_docs.py
```

完成标准：S1–S6 通过，文档与行为一致；实际失败不能靠兼容分支隐藏。不修改旧数据库，不自动提交 Git。
