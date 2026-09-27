# PT6 运行降噪与后续工作留痕

- created_at: 2026-09-27T14:39:38Z
- status: planning；parent: persistence-traceability；depends_on: PT5

## 目标

把领域历史与 bridge/MCP/A2A/host wake 诊断分层，减少稳定连接的无意义写入，同时保留真实唤醒和后续修复的证据。

## 范围与约束

- enrollment、任务/认知/权限/结果/checkpoint 是领域历史；rebind、callback、presentation、wake requested/started/observed/unknown 是诊断历史。
- A2A durable message、delivery callback、host wake、Agent pull、turn start 分别记录；一个证据不能冒充另一个。
- 只有 epoch/凭据/宿主状态真的改变才产生领域事件；no-op 查询不得推进 revision。
- 验收后的新缺陷建新 task/result，以 `caused_by`/`fixes` 关联，禁止追补旧验收。

## 交付与验收

1. 常驻 bridge 重复调用、重启、旧 epoch、实际凭据变化各有 fixture，且能区分 domain revision 和诊断计数。
2. A2A delivery 失败/重试、host wake unknown、Agent pull 和 turn 执行的时间线可查询。
3. 对当前历史 reconnect/attempt 不删除、不重写；为真实后续修复建立关联事件。

## 不做

不承诺宿主私有 API 的自动唤醒，不把 callback 成功写成 turn 已执行，不清空历史噪声以获得好看的统计。
