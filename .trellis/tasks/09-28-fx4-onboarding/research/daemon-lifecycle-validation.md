# FX4 Windows daemon 生命周期修复与实测

记录时间：2026-09-28T13:36:42.452Z（最后一组实际进程检查完成时间）。
范围：O2 的本地进程启动、停止和状态查询。本记录不证明 Desktop 重启验收完成。

## 起因与结论

协调者报告：此前真实项目 daemon 在 MCP 重载附近消失，没有正常 shutdown 或 traceback；消失原因尚未查明。此次没有停止、重启或杀死真实项目 `D:\Tsunagou-fx-live-20260928` 的 daemon。对当时 PID 103604 只执行了 Windows 只读 Job 查询；`in_job=true` 本身不能证明它继承了会随 Desktop 关闭的 Job。

已复现一个独立缺陷：原 `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` 只隔离控制台，不阻止继承允许脱离但会随宿主关闭的 Job。把旧 flags 注入真实 CLI 后，CLI 返回 started，随后测试父 Job 关闭，HTTP daemon 的实际 PID 随之退出。新增 `CREATE_BREAKAWAY_FROM_JOB` 后，在相同允许脱离的 Job 下，父进程和 Job 确实终止，原 PID/runtime/project 的 HTTP health 仍正常。没有创建 Windows 服务、计划任务或绕过宿主强制限制。

## 代码变化

- [CLI daemon 代码](../../../../src/tsunagou/cli/app.py)：Windows 启动加入系统支持的 Job breakaway flag；标准输入仍为 DEVNULL，输出仍写 daemon.log，保持无窗口。直接禁止 breakaway 的 Job 返回 `daemon_launch_failed` / `os_error=5`，给出从独立终端启动的下一步；不静默重试依赖宿主的旧 flags。
- `daemon stop` 继续核对 HTTP runtime/PID/project/source；taskkill 非零且进程仍活着时返回 `daemon_stop_failed`，成功发出停止命令后也等待 OS 确认退出。超过五秒仍活着返回 `daemon_stop_timeout`，不会假报 stopped。
- 保留 endpoint/daemon registry 后，重复 stop 在旧 PID 已由 OS 确认为退出时返回 already_stopped；HTTP 不可达但 PID 还活着或无法验证时返回 daemon_identity_unverified，不杀未知进程。
- `daemon status` 区分 running、stopped 和 unverified；HTTP 不可达但 PID 活着不再谎报 stopped。stopped 的退出码仍为 3，unverified 为 4。
- [停止和状态单测](../../../../tests/unit/test_daemon_stop.py)覆盖不可达但存活、旧 PID 退出、错 runtime、taskkill 失败、退出等待超时及 status 区分；[Job 实测](../../../../tests/integration/test_daemon_lifecycle.py)使用临时 Git 项目、真实 CLI/uvicorn、测试自身拥有的 Job 和真实 HTTP。既有 unrelated-service 测试明确模拟其假 PID 存活，保留身份防护的语义。

## 精确实测记录

最后 Job 组开始 `2026-09-28T13:36:30.274Z`，结束 `2026-09-28T13:36:42.452Z`，墙钟 `12.178305` 秒；pytest 退出码 0，4 条断言通过。**其中 nested_denied 是已知系统限制的观察，并非 O2 通过。**

| 场景 | CLI 调用区间（UTC） | 实际 service PID | 父进程/Job 退出后观察 |
| --- | --- | --- | --- |
| legacy：注入原 flags | 13:36:31.597–13:36:33.268 | 94736 | 原 CLI 报 started；关闭 Job 后 PID 已退出，复现缺陷 |
| detached：新 flags，Job 允许脱离 | 13:36:33.839–13:36:35.483 | 94780 | 同 PID 的 health 可用，runtime_id 与 project_id 保持一致；测试随后自行 stop，再 stop 得 already_stopped，endpoint/registry 仍在 |
| denied：当前 Job 禁止脱离 | 13:36:39.587–13:36:39.640 | 未创建 | CLI exit 1，daemon_launch_failed，Windows error 5；没有 endpoint |
| nested_denied：内层允许、外层禁止 | 13:36:40.151–13:36:41.827 | 103884 | Windows 允许部分脱离，CLI 能启动；外层关闭后 PID 仍退出，说明不能保证此宿主策略下的独立性 |

正向 detached 场景：service started_at=`2026-09-28T13:36:34.748Z`，runtime_id=`61cfcc9e-7676-4948-a493-f2737147767b`，project_id=`04a11515-884c-4b77-9f5a-3128dc6848c9`。这些均为测试临时项目；不包含凭据、原 Desktop thread 或消息正文。

组合回归于 `2026-09-28T13:34:57.000Z` 观察到结束，起始时间未单独记录，故不推算总耗时：

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_daemon_stop.py tests/unit/test_cli.py tests/unit/test_onboarding_request.py tests/integration/test_daemon_lifecycle.py tests/integration/test_multi_project_daemon.py tests/integration/test_onboarding_connect.py -q
```

24 passed、exit 0；包括既有多项目共享 daemon 重启，以及两项接入测试。Ruff 检查所改 CLI 和相关测试通过；mypy 检查 cli/app.py 通过。上述是此次范围的回归结果，不代表 FX4 O1–O8 全部完成。

## 未完成的真实宿主验收与限制

1. 尚未在本子任务中退出真实 Codex Desktop，再验证同一 daemon/原会话消息闭环。协调者继续执行该实测；不要把测试 Job 模拟成真实 Desktop 重启。
2. 对于禁止完整 breakaway 的嵌套外层 Job，Windows 可以只脱离内层，且不会直接返回 access denied。该场景仍不满足“宿主退出后继续运行”。必须从允许独立运行的用户终端启动，不能用 WMI、计划任务、替代宿主进程等方法绕过限制。本次没有添加自动判断所有 Job 层级的复杂机制。
3. 不能使用 `IsProcessInJob(..., NULL)` 为真就拒绝启动：CPython Windows venv redirector 自身会给 Python 子进程创建 flags=`0x3000`（kill-on-close + silent breakaway）的 Job。实测此 Job 与 breakaway 后剩余的外层 flags=`0x0` 均存在，因此“有 Job”不是宿主退出必死的充分证据。此次试验中的过强 membership 检查已撤销；Linux/macOS 未在这台机器上执行。

## 调试过程保留

首次新增 unit/integration 文件同名导致 pytest collection import mismatch，已将 unit 文件改名为 test_daemon_stop.py。中间版本曾以“service 属于任意 Job”拒绝健康启动，正向 Job 实测失败后根据 venv redirector 源码与实际 flags 撤回。最后专用 basetemp 收集首次因指定目录的父目录不存在而出现四个 fixture setup error；改用独立系统临时目录后完成上表检查。没有把这些失败计为通过。

## 外部依据

- [Microsoft：Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)：子进程默认继承 Job；最后句柄关闭时是否杀进程由 Job 策略控制。
- [Microsoft：Process Creation Flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)：process group、no window 和 breakaway 分别控制不同属性；breakaway 尊重既有 Job 的许可。
- [Microsoft：Nested Jobs](https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs)：允许从内层退出不意味着能离开禁止脱离的外层。
- [CPython 3.13 Windows venv launcher 源码](https://github.com/python/cpython/blob/3.13/PC/venvlauncher.c)：launch 创建自己的 Job、设置 kill-on-close/silent-breakaway，并把真正 Python 进程加入该 Job；说明 launcher PID 与服务 PID 必须区别处理。
