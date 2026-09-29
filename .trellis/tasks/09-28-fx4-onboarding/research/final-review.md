# FX4 接入审查与局部修复

检查结果确认时间：2026-09-28T13:58:08.000Z。角色：开发过程的 Trellis reviewer，不是运行时 Worker。

本次审查范围：安装来源与配置、宿主环境转发、共享 bridge 的绑定恢复、Windows daemon 生命周期、安装和接入时间戳的公开字段。依据为 FX4 PRD O1–O8、design/implement/check.jsonl 及其引用规范。没有操作真实业务项目、daemon 或用户会话，没有安装依赖或创建提交。其他 Agent 同时负责 FX5、Desktop poll 和消息公开接口，本次没有覆盖这些文件。

## 已修复

1. `packages/bridge-server/src/server.ts` 与 `credential-handoff.ts`：调用方读取旧 session 后决定 forceReconnect，可能在另一恢复操作已成功之后仍触发第二次轮换。改为在已有 session 私有锁内比较目标 host_generation 与最新保存值；真正的认证失败仍可强制恢复。新增重叠恢复和迟到恢复测试：重叠请求复用同一 command_id，后到者保留相同 epoch，不再发送新重连命令。
2. `src/tsunagou/cli/app.py`：不同会话各有 connect.lock，但此前 global Codex MCP 的 get/remove/add/env_vars 更新未互斥。现将整个登记序列放在用户配置目录下的既有 ProjectLock 内，最多等待十秒；不新增锁基础设施。新增两个连接并行登记测试，验证只执行一次 remove/add，另一个得到 unchanged，保留其他用户设置。
3. `src/tsunagou/application/onboarding.py`：合法的 TOML section/数组行末注释或缩进会导致原正则找不到赋值，重复插入 env_vars 并解析失败。匹配现支持这些常见格式；回归覆盖多行数组、注释及重复调用不写入。

规范已同步到 `.trellis/spec/backend/entrypoint-contracts.md`，明确全局配置互斥、动态环境转发、锁内判断宿主代次，以及后台恢复不等于原 Agent 已执行。

## 已验证

以下均实际退出 0；没有把运行时间推算成编码时间。此次检查未单独记录每条命令的开始/结束时间，故这些值为 unknown；上方时间是确认结果的观测时刻。

| 检查 | 命令/范围 | 结果 |
| --- | --- | --- |
| Python 单测 | `.venv\Scripts\python.exe -m pytest tests/unit/test_onboarding_request.py tests/unit/test_onboarding_timing.py tests/unit/test_runtime_context.py tests/unit/test_install.py tests/unit/test_project_integration.py tests/unit/test_cli.py tests/unit/test_daemon_stop.py -q` | 47 passed |
| Python 真实进程 | `.venv\Scripts\python.exe -m pytest tests/integration/test_onboarding_connect.py tests/integration/test_multi_project_daemon.py tests/integration/test_project_bootstrap_cli.py tests/integration/test_daemon_lifecycle.py -q` | 8 passed |
| 凭据恢复 | `node --test packages/bridge-server/scripts/test-credential-handoff.mjs` | 19 passed，实际 harness 报告 21277.059ms |
| 晚到票据 | `node packages/bridge-server/scripts/smoke-late-ticket.mjs`，再带 `--implicit-session` | 两项 passed |
| Bridge 构建 | `corepack pnpm --filter @tsunagou/bridge-server run build` | pass |
| TypeScript | `corepack pnpm -r run check` | 所有 workspace pass |
| Python 类型 | `.venv\Scripts\python.exe -m mypy src/tsunagou/application/onboarding.py src/tsunagou/application/project_integration.py src/tsunagou/cli/app.py` | 3 个源文件 pass |
| Ruff | 同上 Python 源文件及相关接入、计时、项目配置、CLI、daemon-stop 单测 | pass |
| 文档 | `.venv\Scripts\python.exe tools/docs/validate_docs.py` | 365 Markdown、946 本地链接 pass |
| 补丁格式 | `git diff --check` | pass，只有既有换行风格提示 |

真实进程测试覆盖两个会话共用 MCP 的身份隔离、普通读取不重连、宿主变化后每身份只增加一次 epoch、多项目同进程与同库恢复、启动 CLI 退出后的存活。它们使用临时测试项目，不能当作原 Desktop LLM 业务闭环的证据。

## 未修复或不在本次结论内

- Windows 外层嵌套 Job 禁止完整 breakaway 时，仍可能随宿主退出。已有生命周期测试明确记录这一系统限制；其“通过”表示成功观察限制，不表示该环境满足 O2。此次不新增 WMI/计划任务等规避路径，也不修改既有处理；实际宿主退出后的验证由主会话继续。参见 [生命周期记录](daemon-lifecycle-validation.md)。
- O5/O6/O7 与 FX3/FX6 的原会话自动唤醒、主 Agent 回复职责和真实业务任务仍需主会话按实际证据验收。本次没有重载真实宿主或制造跟进消息，不能替代这项验收。最新实测以 [原宿主记录](live-original-host-20260928.md) 为准。
- 其他公共工具的 Schema/handler 一致性属于协调者正在同步的消息接口及后续整体检查；本次没有扩改 command catalog，也没有宣称全部公共接口通过。

本审查没有新增产品设计分歧；上述局部修复不改变用户/main/worker 权限，也不将 FX4 或父任务标为完成。
