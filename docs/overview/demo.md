# 十分钟本机演示

这是首发的演示路径，不代表四个宿主已经完成正式共同基线。演示重点是认知协作闭环、子 Agent 独立加入、权限边界和恢复事实。

## 0–2 分钟：初始化协调仓库

准备一个用户已有的 Git 协调仓库，然后初始化本机项目。`.tsunagou/` 从初始化开始保存项目中心持久化；代码仓库、外部根和协调仓库可以是多个目录。

```powershell
tsunagou project init D:\Work\ControlRepo --name Demo --objective "统一 API 字段契约"
tsunagou doctor
```

## 2–4 分钟：接入主 Agent 和子 Agent

用户在三个独立宿主对话中选择目标会话，按对应 adapter 的诊断结果执行 attach。系统签发一次性 worker ticket，bridge 私下兑换并保存 session credential；用户和模型都不粘贴 token。当前未通过真实基线的宿主会显示 diagnostic，不能 claim 任务。

```powershell
tsunagou --project PROJECT_ID agent enroll --adapter codex --mode attach
tsunagou --project PROJECT_ID agent enroll --adapter opencode --mode attach
tsunagou --project PROJECT_ID agent list
```

用户只任命一个主 Agent；普通子任务由主 Agent 协调，不要求用户逐项审批。子 Agent 的临时宿主 subagent 不会自动成为项目成员，必须有独立 conversation digest 和 enrollment。

## 4–7 分钟：展示认知分歧和契约

主 Agent 创建并发布一个任务，两个已 enrolled 的会话分别提交对同一字段的显式 claim，例如“status 可空”和“status 必填”。调度中心只比较结构化 claim，不推断隐藏思维。它产生 discrepancy，主 Agent 组织 proposal；两个参与者分别用同一 proposal digest 接受。

用户可以在黑板看到身份、责任、当前 Attempt、分歧、契约和 blocker；私信正文仍只对收件人可见。ACK 不等于业务响应，contract acceptance 不能由一条聊天消息代替。

## 7–9 分钟：执行、挂起和恢复

子 Agent claim 后先 preflight，再 start；共享资源有 Lease，主 Agent 负责 Git 写操作。用户提出重大 API 方向变化时，相关 Agent 提交 SuspensionSnapshot、block 并释放 Lease；不相交的 Agent 继续工作。用户稍后 resolve 精确 revision/digest，Agent 重连并 resume，再次 preflight/start。无 wake 宿主可由用户打开原会话后 pull 黑板恢复。

```powershell
tsunagou --project PROJECT_ID decision list
tsunagou --project PROJECT_ID operation show OPERATION_ID
tsunagou recover
```

## 9–10 分钟：说明验收状态

运行 `uv run python tools/dev/release_check.py` 查看真实宿主 gate。当前 T02 证据不足时，命令会明确列出 `live_baseline_missing`；这是预期的保护性结果。只有四个宿主各自 11 项 baseline 有脱敏 evidence refs 后，才可将它们写成正式支持。

研究效果也单独运行 `tools/experiments/prepare.py` 和固定定义的真实 runs。准备器只生成 A/B/C/D 计划，不生成结果、不填充 token 0、不宣称改善。真实结果必须保留失败样本和 limitations。
