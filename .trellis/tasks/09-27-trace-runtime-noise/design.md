# PT6 设计

created_at: 2026-09-27T14:39:38Z

用 `domain_event` 与 `diagnostic_event` 两个投影区分业务事实和传输观测，二者共享时间、actor、subject、causation，但诊断不改变业务 revision。bridge rebind 只有 epoch/credential/host 状态真实改变才写领域事件。A2A 记录 message durable、delivery callback、host wake、Agent pull、turn start 五类可区分证据。

后续修复通过 `caused_by`/`fixes` 指向旧 task/result，新任务有新时间线，不回写旧验收。
