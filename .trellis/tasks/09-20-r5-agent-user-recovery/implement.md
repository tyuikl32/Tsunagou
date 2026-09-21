# R5 实施步骤与交接

先读 [PRD](prd.md)、[design](design.md) 和 implement.jsonl。以下拆自独立成品方案，不表示已经修改代码。

## 启动

先确认 R4 的全部验收条件通过。

```powershell
python .trellis/scripts/task.py validate .trellis/tasks/09-20-r5-agent-user-recovery
python .trellis/scripts/task.py start .trellis/tasks/09-20-r5-agent-user-recovery
```

## 实施顺序

实施：

1. 整理bridge-server复用bridge-sdk，去除第二套手写工具、硬编码digest及“内容相同永远同command_id”的逻辑。每次用户/模型动作生成新command_id；同一次动作网络重试保留ID。不同时间发送相同内容的两条消息可以是两次动作。
2. 提供逐会话bridge配置生成器。CLI从daemon申请ticket，私有交付给本机bridge；bridge启动兑换。用户只向宿主配置非秘密启动描述路径，不手填conversation_id或向模型粘贴token。
3. 将接入结果非秘密agent_id/session_id/角色回报用户和模型；用户通过U接口任命main。两次新接入不能共享session文件；resume读取原私有记录并用nonce/epoch与daemon验证。
4. local_session接入按本方案第1节落地；宿主报告不阻塞本机协作。保留ticket、协议、真实持有凭据和主体边界校验。
5. MCP工具覆盖M1命令及query工具，返回精确Problem；能力不足的动作不在tools/list冒充可调用。attach/resume/任务边界读取黑板和增量收件箱；先呈现再ACK，不把ACK当业务回答。
6. UserDecision与CompletionProposal归projects模块；workflows只调用端口。主Agent提出重大决定，user通过CLI resolve精确revision/digest。解决不自动start；相关owner显式恢复，无关任务不阻塞。
7. checkpoint由真实Operation/Job驱动模块export；本机私有状态不进入shared文件。项目完成确认同事务写completed+checkpoint Operation，物化失败保留completed与错误，不能丢失用户结论。
8. 观测模块消费已提交事件，持久化审计投影和处理水位；提供query，必要日志关联command_id/attempt_id/event_seq；不记录私有token和消息全文。

出口：人只需CLI启停/接入/任命/重大确认，Agent使用实际MCP工具完成工作；停止bridge会话再恢复可读原任务及消息；checkpoint/审计能够用于查故障。

## 验证与调试

1. 运行两个真实 stdio bridge 子进程，通过 MCP 初始化、tools/list、tools/call 连接同一 daemon，检查身份隔离。
2. 中断网络重试同动作、再次发送同正文新动作，校验 command_id 与 inbox 呈现/ACK 顺序。
3. 通过 U CLI 提交决定/完成确认，注入 checkpoint 物化失败；断言用户结论保留、状态可查、旧 epoch 不延续执行权。

相关检查入口：

```powershell
uv run python -m pytest -q
corepack pnpm run check
corepack pnpm exec vitest run
python tools/docs/validate_docs.py
```

按实际变更运行对应 lint/type/schema 检查。本轮仅建任务，以上不是已通过的实现验收记录。

旧审计器若因协议变化不能运行，需迁移行为断言到正式入口测试，不能删除失败项后声称完成。

## 交接记录

- [ ] PRD 逐项通过，记录真实命令、退出码、公开查询和数据库事实。
- [ ] 公共接口同步 Schema、registry、生成类型、fixtures 与操作文档。
- [ ] 拒绝用例零部分写入；持久化改动经过重启验证。
- [ ] 记录修改文件、兼容处理、后继依赖和剩余范围，清除成功占位。
- [ ] 验收通过后更新任务/机器计划；按用户授权处理 Git，不自动提交或发布。

实际实现结果（2026-09-21）：已完成第一轮 bridge 基础修正：摘要改为读取共享 protocol registry 或 `TSUNAGOU_SCHEMA_BUNDLE_DIGEST`，默认每个 MCP 动作生成新的 UUID command_id，当前静态 bridge 暴露 49 个工具；`tsc`、本地 stdio `initialize/tools/list`、一个真实认证 bridge 的 `tools/call` 探针和两个独立 bridge 的完整首轮协作均通过，记录见 `docs/standalone/bridge-smoke-2026-09-21.json`、`docs/standalone/bridge-auth-smoke-2026-09-21.json` 与 `docs/standalone/bridge-two-session-smoke-2026-09-21.json`。CLI 的 `agent enroll --output-dir` 已能生成不含秘密的逐会话启动描述；checkpoint 失败重试和 audit 查询也已有公开入口。断线故障注入、完整用户恢复矩阵和真实宿主基线仍待验收，因此任务保持 planning。

补充：启动描述同时保存 daemon state 目录；bridge 启动时优先读取当前 endpoint manifest，解决 daemon 随机端口重启后的旧 URL 问题。完整公开入口 smoke 已覆盖两 bridge、用户决定、项目完成、checkpoint、recovery 和重启后的身份恢复，但真正宿主与故障注入仍待验收。
