# PT2 秘密交付与安全幂等迁移

- created_at: 2026-09-27T14:39:38Z
- status: in_progress；parent: persistence-traceability；depends_on: PT1（已验收）

## 目标

消除 enrollment/reconnect 的 `secret_token`、`reconnect_nonce` 等可用秘密在 command result、checkpoint、artifact、日志和 API 中的持久化，同时保留响应丢失后的安全恢复能力。

这里的 API 禁止秘密指普通查询/导出/日志与持久回执；已认证的 ticket/enrollment/rebind/reconnect 命令响应本身是必要的私有凭据交付通道。兼容现有 bridge 的交付形状，增加 delivery_ref 和保存后 ACK，不把可用凭据交给模型工具结果或用户终端。

## 范围与约束

- command result 只存 `receipt_id`、`delivery_ref`、目标 session/actor、过期/消费状态和安全摘要；秘密只进入 daemon 私有 delivery bucket，由本机认证 bridge 一次读取。
- 重试同一 command 复用 identity 和 receipt；已消费 receipt 不生成第二 Agent。重新发放必须撤销旧 epoch 并留原因。
- 旧库先备份、完整性检查、暂停写入、撤销 credential、清理结果/快照/WAL/SHM 可见副本，再升级；`secure_delete` 不承诺抹除所有备份介质。

## 交付与验收

1. 新旧 command result、事件、checkpoint DTO、artifact metadata、CLI/HTTP 和 bridge fixture 中 secret sentinel 全部不可见。
2. 注入 HTTP 响应丢失、bridge 重启、重复 command、跨 actor 读取和过期 delivery，验证幂等、拒绝和可操作错误。
3. 为旧 schema 提供 dry-run、备份路径、credential rotation、scrub、integrity_check 和回滚说明；真实项目迁移必须由用户单独确认。
4. 验证 secret 不会被异常、调试日志、WAL/SHM、patch 或导出带出，并记录平台密钥/ACL 的实际检查结果。

## 不做

不建立远程 KMS、不承诺 Full Access 下的取证不可恢复、不在本轮自动迁移用户演示库。
