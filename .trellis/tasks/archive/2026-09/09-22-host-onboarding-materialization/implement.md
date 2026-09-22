# 宿主接入入口实施计划

1. 读取 T02 宿主矩阵，记录 Codex/首发宿主的真实项目文件发现证据。
2. 更新项目 skill 模板和 onboarding 文档，加入 context/inbox/role/ready 判定。
3. 如需平台专属文件，仅按已验证格式生成；否则生成 manual fallback 并保留 unknown 状态。
4. 增加 smoke：新项目启动 Codex/generic bridge 后能找到入口；新 conversation 不能继承旧 session。
5. 更新 `docs/overview/agent-quick-start.md`、`docs/overview/subagent-guide.md`、`docs/implementation/adapters.md`。

验证：adapter tests、bridge build/check、generic 文件扫描、`python tools/docs/validate_docs.py`。generic `AGENTS.md` 与项目 skill 已生成；未验证的宿主 hook 保持 unknown/manual，不伪造 enforced。
