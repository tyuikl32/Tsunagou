# FX2 实施与验收记录

状态：completed。2026-09-28T11:49:45.911Z 留档；未提交 Git。当前接口已经实现，旧多步执行命令已删除。

## 实际交付

- ResourceReservation 替代资源 TTL：保存占用者、范围、取得/释放时间和原因。断线、长推理及同库重启均不夺取 owner；后台 Job 超时仍保留。
- task.begin 一次取得 Attempt、基线、占用及授权；task.submit 一次采集成果、提交、释放并撤权。公开 HTTP 使用 /api/v1/commands/task.begin 和 /api/v1/commands/task.submit。
- 扫描/只读 Git/不可变 patch 写盘放在 SQLite 写事务之前；领域状态、授权、事件、outbox 仍在同一 UoW，失败整体回滚。测试用另一 SQLite 连接证明文件采集期间未持有写锁。
- main 的工作区选择归 Task/scope_revision；新 Attempt 采新基线，同 owner 重启恢复同一 Attempt。Git 写操作仍由 main 决定。
- 删除 worker.ready 和 coordination 的重复执行状态；保留定向分派、Task.blocks、明确 required_contract_ids。与当前任务无关的认知报告不形成门禁。
- 用户决策待答只通知运行中的 owner，不擅自停止/释放；owner block 或 main recover 后才释放。独立任务继续执行。
- Worker context 返回 owned tasks 与适合本成员的 open_tasks，包含 revision、scope、依赖和 owner。资源冲突通过 HTTP/MCP 返回真实 blockers。
- Schema、Python/Node 打包协议、生成 registry、Codex adapter、Skill、项目生成规则和用户说明已同步。

## 验收证据

| 条件 | 自动测试/实测 |
| --- | --- |
| E1 | 资源时间推进一年仍可提交；同库真进程重启保留 owner/reservation |
| E2 | 同任务竞争、范围冲突、准备失败、后半事务失败均无部分状态；响应重放无重复采集 |
| E3 | 只选一次策略、新 Attempt 新基线、重启相同 owner 恢复 |
| E4 | 实际文件成果/patch、释放时间/原因、审查 completed；四种退出各撤权 |
| E5 | 无 ready 的分派直接开始；错 worker 拒绝；Worker 自行读 context 开始 |
| E6 | 无关 proposal 不阻塞，显式 required 未接受则拒绝 |
| E7 | main recover 后换 owner 成功、旧 submit 拒绝；旧 Grant 重启后无效 |
| E8 | 真实 HTTP/CLI daemon 生命周期和两个 Node stdio MCP 进程共用相同编排 |

全量 Python 回归：377 passed，3 skipped（Windows 符号链接权限）；日志 test-full.log。最后新增 context 投影后，相关集成/入口测试 31 passed。mypy 69 个源码文件无错误；ruff src/tests 通过；TypeScript 34 tests 通过。Bridge 凭据测试 17 passed，晚到 ticket/隐式 session 重启两项 smoke 通过。架构、协议 99 commands/115 schemas 与文档校验通过；最后文档收尾仍再跑链接检查。

真进程最终报告：[process-probe-final.json](research/process-probe-final.json)，2026-09-28T11:46:15.936Z 至 11:46:22.834Z，总计 6.898 秒。前一轮报告也保留。新临时 Git 项目，daemon 已停止；报告只存脱敏 ID、状态与时间，不含凭据。测试真实执行 Node 文件测试、模拟用户改文件、收发消息与响应义务、双参与者契约和 main 审查。

## 旧测试处置

删除 test_coordination_reliability.py、test_lease_assignment_sync.py、test_submit_lease_reliability.py、test_wake_callback_fence.py：它们针对已退役的 TTL/worker.ready/coordination WakeAttempt。原有并发、owner、回滚性质转入 test_execution_begin.py；真实 hostwake 的回调 fencing 继续由 test_hostwake.py、test_codex_desktop.py 覆盖。不是删掉失败断言冒充通过。

## 仍属后续任务

此处 HTTP/MCP 客户端是测试程序，不是两个真实 Desktop LLM。FX3 原会话唤醒的完整产品闭环仍需 FX4 接入和 FX6 真实协作验收。接入命令、逐会话 bridge 路由、全流程时间线分别属于 FX4/FX5，未据本记录宣称完成。
