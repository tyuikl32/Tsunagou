# 已确认设计与最小边界

差距在宿主入口和用户级路由，不在 daemon 权限或业务域。复用 DSH 的安全 CLI 启动模式、Codex 的申请认领和回执、agent_connection 与 onboarding 的票据及路由。

- agent prepare --adapter opencode 安装一次用户级工具及无凭据共享 MCP；先校验冲突、重复执行幂等、只写拥有的条目。宿主 2.0.18 具体插件接口先实测。
- 一个薄宿主工具直接调用 agent join --adapter opencode，真实身份仅内部传入 CLI 子进程。无参数；不重复 pending 查询或业务规则。
- agent join 默认 codex；OpenCode 路径验证 adapter、manifest、私有路由/旧绑定冲突后 claim，connect，绑定回执，mark_enrolled。复用现有状态和锁。
- 独立 hosts/opencode 路由目录；共享 bridge TSUNAGOU_HOST_META_KEY=ai.opencode/sessionID。正常 MCP 使用宿主原生客户端。
- bridge 将可验证 console_enrollment 回执支持扩展到 OpenCode，保持 Codex wake 独立、helper 排除。
- 控制台本地 OpenCode prepare 无票；现有界面/轮询使用认领和精确原会话回执判据。旧记录/跨机维持原路径，避免误认旧记录。

预计源码边界：薄 OpenCode host 工具及其注册、cli/app.py、application/agent_connection.py 和 onboarding.py、platform/enrollment_store.py（仅必要宿主筛选）、console/enrollment.py、bridge-server 的回执条件。测试、文档/规范随公共 CLI 语义同步。无 daemon schema 或权限更改，无自动 Git 提交。

旧绑定冲突检测只读所选项目与现有本机项目索引中的 bridge 身份记录，不扫描磁盘或清理配置；未登记或移动后索引失效的旧项目无法自动发现，用户指南明确该边界。已存在的新共享路由始终阻止跨项目覆盖。
