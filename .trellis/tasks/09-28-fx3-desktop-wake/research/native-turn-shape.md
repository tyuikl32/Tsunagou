# 原 Desktop 回合来源识别修复

记录日期：2026-09-28。范围：`codex_desktop.py` 的只读回合观察与 `test_codex_desktop.py`；不修改 dispatcher/port，也没有向测试会话发消息或重启真实 daemon。

## 原宿主观察

两条已接入的原手动 Worker 会话均收到 daemon 拉取通知。只读 `read_thread` 显示：其新回合不是 `userMessage`，而是宿主生成的 `functionCallOutput`。简化且去除原 thread 的结构如下：

```json
{
  "status": "completed",
  "startedAt": 1790602533,
  "completedAt": 1790602621,
  "items": [{
    "type": "functionCallOutput",
    "name": "send_message_to_thread",
    "namespace": "codex_app",
    "output": {
      "text": "<codex_delegation>\n  <source_thread_id>[private]</source_thread_id>\n  <input>[Tsunagou wake wake:example] Read your Tsunagou project context and pending coordination inbox using its MCP tools, present/ACK the messages, then handle them under your current role and task scope. This notification contains no task instructions or new permissions.</input>\n</codex_delegation>",
      "truncated": false
    }
  }]
}
```

同一 Worker 以 `includeOutputs=false` 读取时，`functionCallOutput` 的 type/name/namespace 仍在，但 `output` 整体消失。因此仅扩展匹配类型而不调整读取参数，依旧无法认出已经执行的回合。

首次真实完整回合的宿主时间：

| 对象关联 | startedAt 转换为 UTC | completedAt 转换为 UTC | 观察 |
| --- | --- | --- | --- |
| Worker A / wake:402d9669-9085-4437-99b8-881550113763 | 2026-09-28T13:35:33.000Z | 2026-09-28T13:37:01.000Z | completed；原会话含共享 MCP context、claim、fetch、presented、ack 调用 |
| Worker B / wake:b85465ff-a87f-4db3-ab41-689e5413be48 | 2026-09-28T13:36:44.000Z | 2026-09-28T13:38:17.000Z | completed；原始触发同为 app-tool delegation |

后来两条新回合在 `2026-09-28T13:41:33.000Z` 开始；此次读取时均为 inProgress，completedAt=null。没有将未完成时间填为读取时间。以上时间来自宿主秒级 Unix 时间戳，`.000` 表示其秒级精度，不是推测出的毫秒。

## 根因和改动

旧 poll 只在 userMessage 文本任意位置寻找 marker；实际 app-tool 形态被漏掉，而且 `_read` 关闭 output。于是宿主已执行、Worker 已处理收件箱，provider 仍停在 starting。

新实现只对已发送或结果未知的 poll 设置 `includeOutputs=true`，继续限定最近三回合、每项最多 1200 字符。初次状态检查、忙碌检查、inspect 等仍不请求 output；不会把这些输出保存进 wake evidence。

来源匹配只接收：

1. `userMessage` 中 type=text 的正文以完整 `[Tsunagou wake <当前 wake_attempt_id>] ` 开头。
2. `functionCallOutput` 且 namespace=`codex_app`、name=`send_message_to_thread`，未截断 output.text 可解析为 `codex_delegation`，它唯一的直接 input 子元素以同一个完整 marker 开头。

Agent 回复、其他工具/namespace、marker 引用、别的 wake ID、标记出现在 input 外、无 delegation 包装和截断输出均不能将 attempt 升为 running/completed。观察失败或缺少关联仍保留原状态，不靠 Worker 自报完成猜测发送来源。

识别到回合后沿既有 evidence 写 turn_started 和 turn_completed/wake_failed，保留宿主原始 startedAt/completedAt；observed_at 仍为实际观察时间。首次观察已经 completed 的回合也补齐两个已发生的事实，不伪造中间观察。原 turn ID 只存 digest，原始 thread、source_thread_id 和通知正文不进入证据。

## 验证

`tests/unit/test_codex_desktop.py` 23 passed；同时覆盖原 userMessage 形态和实测 delegation 形态、includeOutputs 字段是否请求、响应丢失后的观察、provider 恢复、失败/中断终态、真实时间保留、重复 poll 不追加完成证据及八类假来源拒绝。

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/test_codex_desktop.py tests/unit/test_hostwake.py tests/integration/test_desktop_wake.py -q
.venv\Scripts\python.exe -m ruff check src/tsunagou/hostwake/codex_desktop.py tests/unit/test_codex_desktop.py
.venv\Scripts\python.exe -m mypy src/tsunagou/hostwake/codex_desktop.py
```

组合回归 48 passed、exit 0；Ruff/mypy 通过。原 implement.md 的命令引用不存在的 `test_wake_callback_fence.py`，第一次执行在收集前报错；按当前文件清单移除不存在项后运行上列命令，没有把该失败计入通过。回归中仅见既有 FastAPI on_event 弃用警告。

本修改尚未在本子任务中载入真实运行的 daemon；由协调者在其计划的重启/恢复测试中验证持久 wake-attempt 从 starting 正确进入完成状态。这里的只读原宿主形态证明根因和数据来源，不代替重启后的产品闭环验收。
