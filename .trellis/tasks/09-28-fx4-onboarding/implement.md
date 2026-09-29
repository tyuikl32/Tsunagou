# FX4 实施与验证

前置 FX2、FX3。普通调用位置为业务目录，source-root 明确来自已安装 Tsunagou。

1. 修改 tools/install/install.py，固定 source selection/启动入口/安装起止记录；补 tests/unit/test_install.py，包含两个 checkout 和无关 cwd。
2. 将 cli/app.py 的 project-root/state/credential/endpoint 解析收敛到一个复用函数；补 tests/unit/test_cli.py、test_history_cli.py；覆盖多个项目引用同一 daemon，不强制每项目启动进程；避免复制相同解析逻辑到每个命令。
3. 实现 agent prepare、connect 的 request-file 流程和完成报告；扩展已有 enrollment ticket 的私有绑定意图。更新 API/Schema，保持 U 任命边界。
4. 改 packages/bridge-server/src/server.ts 与 credential-handoff.ts 的逐会话路由、晚到请求和实际需重连判断；复用已有 private-file 锁及保存/ACK，不重开已修的 Windows 端口锁问题。
5. 修改 project_integration.py：生成 begin/submit 规则、main 响应职责、选定宿主资源和 workspace root。同步 .agents/skills/tsunagou-install、tsunagou-agent-onboarding 及实际打包资源；不只修改用户机器上的副本。
6. 新增 agent list，复用 agents query。更新 quick-start、CLI/HTTP 手册，所有命令用安装产物而非依赖开发目录。
7. 新增 tests/integration/test_onboarding_connect.py，真进程覆盖两个会话、同会话重连、子目录、终端关闭、延迟 ticket、daemon/bridge 重启。

~~~powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_install.py tests/unit/test_cli.py tests/unit/test_history_cli.py tests/integration/test_project_bootstrap_cli.py tests/integration/test_onboarding_connect.py -q
corepack pnpm --filter @tsunagou/bridge-server run build
corepack pnpm -r run check
corepack pnpm exec vitest run
.\.venv\Scripts\python.exe tools/codegen/validate_protocol.py
.\.venv\Scripts\python.exe tools/docs/validate_docs.py
~~~

实施结束提供实测的一条接入命令与返回，隐藏私有数据。O1–O8 全通过，不接受只 ticket_issued 或 main 替 Worker 查询 context 作为 Worker 已接入。
