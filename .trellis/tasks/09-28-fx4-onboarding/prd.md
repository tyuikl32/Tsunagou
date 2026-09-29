# FX4 安装定位与一次接入

状态：in_progress；覆盖 FX-R05 和 FX-R03 的接入部分。依赖 FX2、FX3。原宿主完整闭环仍待 FX3/FX6 验收。

## 目标与证据

用户说“安装并加入项目”，Agent 可以处理普通步骤，必要时给一条无需替换 ID 的 PowerShell 命令。接入完成即知道真实角色、项目、任务入口和宿主消息路径。

本轮问题：复用错误 checkout、PTY daemon 退出、项目根解析不一致、旧 MCP/session、缺 root binding、无关 OpenCode 配置。现有 tools/install/install.py 默认复用 ~/Tsunagou；cli/app.py:924 connect 最后仅 ticket_issued；application/project_integration.py 仍生成旧 claim/preflight/start 规则。

## 验收

| ID | 可观察结果 |
| --- | --- |
| O1 | 明确安装源与版本，业务目录和子目录可调用同一 CLI；不会默默复用另一个 checkout |
| O2 | daemon 独立于发起它的临时终端，关闭终端后可用；核对实际项目、进程及版本；多个项目可引用同一 daemon，不强制每项目新开进程 |
| O3 | bootstrap 一次写项目规则、选定宿主的 Skill/MCP 配置、根绑定和源码引用；保留用户其他文件内容 |
| O4 | 同 IDE 两会话得到不同 Worker，同会话重连不增身份；用户不填写 conversation_id、agent_id、pipe 或 token |
| O5 | 已有 bridge 能发现新接入材料，不反复要求重启；首次宿主加载必要动作具体、一次说明并复测 |
| O6 | 接入报告包含实际 project_id、agent_id、role、source/version 和连接状态；ticket_issued 不冒充 ready |
| O7 | main 收到请求时按既有授权主动处理/回复并记录；仅真实重大决策升级用户，不再问是否需要做普通调度 |
| O8 | 不生成未选宿主配置；新增只读 agent list 显示成员、角色、任务和最近活动，不能泄露私有收件箱 |

不改用户任命 main 的权限，不增加登录平台或远程认证。设计见 [design.md](design.md)，实施见 [implement.md](implement.md)。
