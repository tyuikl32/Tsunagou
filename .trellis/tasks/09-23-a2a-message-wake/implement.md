# 实施步骤

1. 在 `src/tsunagou/api/a2a.py` 增加 config parser、HTTP notifier 和脱敏 push status。
2. 让 `create_app` 接受可注入 notifier，默认装配标准 HTTP notifier，Agent Card 根据是否装配声明能力。
3. 更新 `protocol/schemas/a2a/message-send.schema.json` 和 A2A unit tests。
4. 更新 `docs/implementation/a2a-boundary.md` 与 standalone gap 文档，记录官方规范和 host wake 尚需 adapter 证据。
5. 跑 A2A、protocol、storage 和 docs validator，核对没有 secret 落入快照。
