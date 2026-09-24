# Desktop attach 阶段 B 实施计划

## 实施顺序

1. 扩展 host binding DTO/CLI：`provider`、`endpoint`、`thread_id`、`attach_confirmed`，默认仍为 managed。
2. 实现 `DesktopAttachProvider`：Unix socket proxy、只读 `thread/read` probe、禁止隐式 `thread/start`。
3. 实现共享 store 的 `HostWakeProviderRegistry`，按 binding provider 路由 probe/wake/poll/close。
4. 增加 unit 测试：endpoint 校验、私有字段隔离、thread/read 确认、无隐式新 thread、ws 拒绝、权限和 revision 边界。
5. 增加 disposable Unix socket app-server 集成测试；先用真实 `codex app-server --listen unix://...` 或受控 WebSocket transport 验证 Upgrade/frame/JSON-RPC，再记录当前 Desktop discovery 结果。
6. 更新 CLI/HTTP 手册、Codex adapter 文档、证据 fixture 和 B 任务状态。

## 文件

- `src/tsunagou/hostwake/codex_app_server.py`
- `src/tsunagou/hostwake/registry.py`
- `src/tsunagou/api/app.py`
- `src/tsunagou/cli/app.py`
- `src/tsunagou/bootstrap/container.py`
- `tests/unit/test_hostwake.py`
- `tests/integration/test_hostwake_attach.py`
- `docs/implementation/codex-host-wake.md`
- `docs/overview/cli-http-manual.md`
- `docs/research/evidence/codex-desktop-attach-2026-09-23.json`

## 完成标准

- Unix socket attach 的注册、probe、resume、wake、failure recovery 和 secret-free public ref 有自动测试。
- 当前 Windows Desktop 的实际 discovery 结果真实记录；没有稳定 endpoint 时明确 `unknown/unsupported`。
- managed A 阶段所有测试与证据不回退，B 不改变 A2A、权限、消息和项目持久化语义。
