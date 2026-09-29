# FX4 实施边界与进度

2026-09-28，in_progress。FX2 已完成；FX3 底层 provider/后台原会话探针已通过，完整接入与本任务联调后验收。

## 核实到的最小行为差距

- CLI 的 root、state、endpoint、control 分别解析；从子目录运行找不到项目，可能沿用另一个项目的环境。
- install.py 无参数时固定选 ~/Tsunagou，没有用户级安装记录和 launcher；Skill 一次写所有宿主。
- connect 以 profile 随机生成会话 ID，总是发新票据，没有真实当前宿主绑定；stdio MCP 进程全局只有一份 session。
- daemon start 只看端口 health，Windows 子进程未断开 stdin/控制台；stop 未核对 PID 对应服务。container 只装配一个项目，所谓多项目复用尚未连接到实际路由。
- bootstrap 的 hosts 只回显，未控制宿主实际配置。context.updated_at 还是 digest，不是时间（实际生成时修正，保留幂等）。

## 修改位置与理由

1. 新增 platform/runtime_context.py：集中解析安装、项目、state、endpoint；CLI 所有普通入口复用。installer 使用同一无外部依赖的安装记录定义，生成绑定运行时的用户入口。
2. cli/app.py：新增全局 --project-root、agent prepare/request-file、agent list；修真实后台启动与目标核对。保留既有私有凭据交付，不另造登录流程。
3. bootstrap/container.py 与 API：传入显式项目运行配置，接入票据到 FX3 binding 在正确身份上完成；多项目复用既有每项目容器/数据库，不共享领域真相。
4. bridge server / credential-handoff：按 MCP 请求宿主身份路由现有私有 session，处理晚到 request/ticket 和 endpoint 更新。
5. 项目生成器、两份随发行源码的 Skill、用户文档同步真实命令及 main 响应职责。新增测试围绕两个 checkout、两个项目、两个同 IDE 会话、同会话重连、子目录、终端退出。

不新增自动业务调度器、不增加认证平台、不迁移旧身份；不改用户 main 任命/重大决策权限。源码不复制到业务项目。分批提交到工作区并记录已验证项；O1–O8 全部完成前不标记任务完成。

## 当前批次

已实现并通过第一批 35 项测试：

- runtime_context 统一 root/state/endpoint，新增全局 --project-root；子目录查找和上下文冲突处理已连接 CLI。
- 安装器按明确来源/登记来源/当前 checkout 选择；新增 --source-root、用户 launcher 和 installation.json，仅复制选定宿主 Skill。launcher 指向安装虚拟环境，源码不复制到项目。当前终端可用返回的完整 launcher 路径。
- daemon 默认启用 auto 宿主投递，stdin 脱离父进程、Windows 隐藏窗口；健康响应包含实际 PID、runtime_id、project_ids、source。start/status/stop 核对服务身份。真实子进程测试证明启动 CLI 结束后后台仍可访问，子目录查询及重复启动复用成功。
- 修正实测发现的 Windows 虚拟环境启动器 PID 与实际服务 PID 不同：记录服务实际 PID。首次失败报告 runtime-process-probe.json 保留；修复后 runtime-process-probe-fixed.json passed，临时 daemon 已停止。
- application/onboarding.py 已实现真实宿主只读核对和私有请求保存，尚未暴露 CLI prepare。票据增加 host_binding，仅 U 可指定，thread 必须匹配票据身份；enroll/rebind 后自动登记 provider，同命令重放不增 binding revision，事件不泄露原 thread/pipe。

下一批：CLI prepare/connect 一次接入、MCP 按 _meta.threadId 逐会话路由、agent list、bootstrap 选定宿主资源、多项目共享 daemon 的实际路由。尚未完成 O1–O8，不能将 ticket_issued 或测试进程代替原 Agent ready。

## 本批收尾验证

全量 Python 400 passed、3 Windows 符号链接权限 skip，65.50 秒；见 test-full-batch.log。随后补的“旧 enrollment 重放不得回滚新 binding epoch/endpoint”与真进程 CLI 路径测试 6 passed。mypy 71 源文件、ruff、TypeScript build/check、架构和协议校验通过。结构化记录在 validation-runtime-batch.json。

已同步 installer Skill、CLI 手册与命令目录。当前旧 connect 的随机 profile 身份和共享 bridge 的单 session 尚待下一批替换；没有宣称它们已修复，也没有让用户执行尚未暴露的 prepare 命令。

## 接入与多项目批次 — 2026-09-28T12:50:42.000Z

本节更新前述“下一批/尚待”状态；FX4 仍 in_progress。

- CLI prepare/connect 已落地：prepare 核对原宿主，私有 request；connect 启动/验证 daemon、兑换 ticket、绑定 provider、登记共享 MCP，输出 enrolled、project/Agent/role/session/host_binding/source/version/UTC connected_at。同会话复用身份；用户不填 ID/pipe。原对话 MCP context 是下一步验证点，不以 headless 查询代替 ready。
- bridge 按宿主 `_meta.threadId` 每请求路由，缺 metadata 的共享进程拒绝；private route 哈希到独立 session。已有 session 普通调用不 reconnect，宿主代次变化/认证失效才重连。同一 MCP 20 次交错上下文调用身份/角色不串用，重启保持 ID/epoch，两个 enroll、零普通 reconnect。
- agent list 已显示每个 Agent 的角色、session_status、current_task_ids、last_activity_at；context 返回自己的 session 与脱敏绑定状态。
- bootstrap 写 Codex 项目 TOML 及选定宿主规则；未选宿主不写，保留用户 TOML/AGENTS；冲突在写入前检查。修正 integration.updated_at 为 RFC3339 毫秒，不变内容保留时间。其他宿主规则可生成，Codex 共享 metadata 接入不能据此泛化为其他宿主已实现。
- 一个 HTTP daemon 接入两个独立项目已真实测试。新增 bootstrap/daemon.py（位置注册/HTTP 路由）与显式 config 容器装配；不修改 process env 来换项目。--reuse 核验实际 source/PID/runtime，原启动项目 U token 登记新 root/state；每项目独立 DB/身份/控制 token。CLI/MCP 自动加项目 header；URL/header 冲突拒绝，多项目无选择拒绝。
- 从项目 B stop 输出 A/B，B start 读取同一私有 daemon-projects.json，恢复两项目并重写各 endpoint；两项目身份不增加。不构建全机项目发现器或服务管理平台。
- Connect 外层 Python 文件锁改用已有 ProjectLock，不把 HTTP/Node 过程嵌套在凭据 socket 互斥里。跨语言 session/ticket 锁保留原实现。
- 更新发行 Skill、快速接入、用户手册、子 Agent 指南、运行流程、CLI 契约、Codex 适配说明及 OpenAPI（项目 header/本机注册入口）。installer 记录 Python/bridge 版本和源码 dirty 标志。所选宿主配置参考官方 https://learn.chatgpt.com/docs/config-file/config-basic 与 https://learn.chatgpt.com/docs/extend/mcp?surface=cli ；已读取而非仅引用搜索摘要。

验证：Python 全量 403 passed/3 平台 skip，日志 test-connect-multiproject-full.log；Node 34 passed，credential 17 passed，加两种 late-ticket smoke；mypy 72 文件、ruff、架构、99 command/115 schema、文档和 diff 检查通过。结构化记录 validation-connect-multiproject.json。原宿主没有在这一批登记，不宣称 LLM 已执行；所有临时测试 daemon 已停止。

新增异常：一次 isolated Python ticket 测试路径哈希到 26822，撞上 MSI.TerminalServer PID 23880 的监听端口，按原协议返回 credential_private_lock_busy。未杀其他进程或跳过互斥；后续全量用不同 temp 路径通过不能证明此局限消失。原会话实测前需要处理这项接入可靠性问题。还要确认首次实际 MCP 加载、O5/O6/O7 原对话行为，然后进入 FX5/FX7/FX6。

## 原宿主实测与新增修复 — 2026-09-28T13:18:00.000Z

Windows 命名管道互斥修复及双向跨语言/进程退出测试通过；安装器保留额外依赖的命令契约通过。主会话与两 Worker 已分别 enrollment，其中 main 和一个 Worker 已实际调用共享 MCP。实际 daemon 消息仍因旧 Desktop endpoint 失败，不能标为接入/唤醒全部完成。原 daemon 曾消失，原因未证实；正在补 Windows Job 生命周期验证。详细过程、部署时间、失败消息 ID、首次加载差异与证据强度见 [原宿主实测记录](research/live-original-host-20260928.md)。FX4 保持 in_progress，FX3/FX6 验收保持未完成。

## 现场状态更新 — 2026-09-28T15:35Z

共享 MCP 已在当前 main 与两名原 Worker 实际返回各自 context；不需要继续找不存在的刷新按钮。动态 endpoint 转发及原绑定恢复后，daemon 消息、完整 payload、回信和业务工作均已发生；前述失败保留。Windows Job 生命周期和 stop 目标核对修复已通过真实隔离进程测试；当前实测 daemon 仍运行于 13:54 的旧进程，后来对它的 stop 被命令策略拒绝，尚未完成最终同库重启链路，FX4 继续 in_progress。

## 遗留 MCP 注册迁移 — 2026-09-29

现场检查发现用户级 Codex 配置同时保留共享 `tsunagou` server 和早期按 profile 注册的固定-session server。后者会令已经启动的 Desktop 对话继续读取过期 ticket/session，表现为 `not_enrolled:no_ticket_or_session_file`；这不是 daemon 合并 Agent 身份，也不能靠不存在的 Settings 刷新按钮解决。

`agent connect` 现于共享 server 成功登记后，在同一用户配置锁内枚举并删除同时满足以下条件的遗留条目：名称符合旧 Tsunagou profile 格式、未使用 routing directory、`TSUNAGOU_PROJECT_ROOT` 为当前项目、带固定 session、且 command/args 与当前 bridge 相同。不同项目、不同 bridge 和运行中的 Desktop 进程不在清理范围。已启动的旧 bridge 不会热切换，操作指引改为先新建对话验证，只有新对话仍未加载共享 MCP 时才完整重开 Desktop 一次；不重新 enrollment、不要求用户填写身份。

验证：`uv run --no-sync pytest tests/unit/test_onboarding_request.py tests/integration/test_onboarding_connect.py -q` 为 9 passed；`uv run --no-sync ruff check src/tsunagou/cli/app.py tests/unit/test_onboarding_request.py` 与 `uv run --no-sync mypy src/tsunagou/cli/app.py` 通过。该修复尚未替代 A1–A8 的原会话实测证据，FX4 保持 in_progress。
