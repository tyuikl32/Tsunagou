# FX4 私有文件锁与安装器回归验证

记录时间：2026-09-28T13:17:08.000Z。执行环境：Windows，Python 3.13.13、Node v24.19.0、uv 0.9.26。本轮属于开发验证，不是 Tsunagou Worker 接入或原 Desktop A2A 唤醒证据。

## 已核验的行为

- Windows Python 与 Node 都使用规范化路径完整 SHA-256 的命名管道名；Python 用首实例独占标记，Node 使用 libuv 的管道监听。实际进程竞争验证两端使用的是同一个互斥边界。
- Node 子进程持锁时，另一个 Node 调用等待后返回 busy，独立 Python 调用也返回 `credential_private_lock_busy:retry_pending_request`；终止持锁 Node 进程后，两种语言均可重新取得该锁。
- Python 子进程持锁时，Node 调用返回 busy；直接终止持锁解释器后，Node 可以取得该锁。测试没有只终止 uv 父进程，也没有通过删除锁文件或猜测 PID 回收锁。
- Python CLI 写入新票据和 Node 凭据恢复后的票据清理互斥。旧 Node 清理不能删除刚由 Python 替换的新票据。
- Python 回归测试保持不相关 TCP listener 占用旧散列端口，新命名管道锁仍可取得；异常退出临界区后锁可再次取得且不留下票据/PID 文件。

## 本轮修改

1. `packages/bridge-server/scripts/test-credential-handoff.mjs`：补 Node 持锁到 Python 拒绝和重新取得的逆向断言，补 Python 持锁进程终止后 Node 恢复测试；全部 uv 调用使用 `run --no-sync`。原票据竞争测试缺少此参数，可能修改共享开发环境，本轮已修复。
2. `tests/unit/test_install.py`：新增安装流程参数回归，覆盖 Python 安装、项目 init、bootstrap、版本验证。安装必须使用 `sync --locked --inexact`，随后三项调用必须全部使用 `run --no-sync`，避免保留开发依赖后又由后续步骤移除。
3. `src/tsunagou/platform/private_file_lock.py`：Linux `AF_UNIX` 改为明确的平台分支，解决 Ruff B009，同时让 Windows mypy 不读取 Windows 类型桩未声明的属性；互斥协议未改变。
4. `tools/install/install.py`：安装记录字典显式注解为 `dict[str, Any]`，修复包含字符串和布尔值时的 mypy 推断错误。

本轮没有改变 `private-file-lock.ts` 或 `test_private_file_lock.py` 的既有实现，只实际验证了它们；也没有执行真实安装器或 `uv sync`，没有修改依赖版本。安装器回归验证调用契约，不能替代主会话后续实装前后的开发依赖保留核对。

## 实际命令与结果

按顺序执行 build、凭据测试及 smoke、Python 单测；静态检查在测试结束后运行。

| 命令 | 结果 |
| --- | --- |
| `corepack pnpm --filter @tsunagou/bridge-server run build` | exit 0 |
| `node --test packages/bridge-server/scripts/test-credential-handoff.mjs` | 18 passed，0 skipped，20514.7211 ms |
| `node packages/bridge-server/scripts/smoke-late-ticket.mjs` | passed，late_ticket_recovery=true |
| `node packages/bridge-server/scripts/smoke-late-ticket.mjs --implicit-session` | passed，implicit_session_restart=true |
| `.\.venv\Scripts\python.exe -m pytest tests/unit/test_private_file_lock.py tests/unit/test_install.py -q` | 8 passed，exit 0；平台分支/类型注解修复后再跑一次仍通过 |
| `.\.venv\Scripts\python.exe -m ruff check src/tsunagou/platform/private_file_lock.py tests/unit/test_private_file_lock.py tests/unit/test_install.py tools/install/install.py` | 初次 B009；明确平台分支后通过 |
| `.\.venv\Scripts\python.exe -m mypy src/tsunagou/platform/private_file_lock.py tools/install/install.py` | 初次安装记录类型推断失败；注解修复后 2 files passed |
| `corepack pnpm --filter @tsunagou/bridge-server run check` | exit 0 |
| `node --test --test-name-pattern='owned private lock\|Python CLI ticket replacement' packages/bridge-server/scripts/test-credential-handoff.mjs` | Python 平台分支修改后的定向复测，3 passed，16660.6471 ms |
| `git diff --check -- src/tsunagou/platform/private_file_lock.py packages/bridge-server/src/private-file-lock.ts packages/bridge-server/scripts/test-credential-handoff.mjs tests/unit/test_private_file_lock.py tests/unit/test_install.py tools/install/install.py` | exit 0；仅 Git 的既有 LF/CRLF 提示 |
| `.\.venv\Scripts\python.exe tools/docs/validate_docs.py` | PASS，358 Markdown 文件、938 本地链接，48 份历史源未修改 |

没有采集单项测试开始/结束 UTC 时间，不倒填；上述耗时取 Node 测试实际输出。

## 平台与验收边界

- 本轮实测限 Windows。Linux 抽象 Unix socket 实现没有在本轮 Linux 环境运行，不能据此宣布跨平台实测完成。
- macOS 等其他平台仍保留 fail-busy TCP 回退，旧散列端口被不相关 listener 占用时仍可能阻塞。没有用 Windows 通过结果掩盖此限制。
- 有界等待仅用于短暂凭据文件临界区，不是任务租约，不释放业务资源或更改任务 owner。
- 未触及 CLI 路由、daemon、共享 MCP 路由、真实会话或全局安装配置；FX4 O1–O8 和 FX3/FX6 原会话实测仍由主会话按完整任务验收。
