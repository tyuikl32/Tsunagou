# 一次 main 与两个 Worker 的事实轨迹

本页按 FX1/FX2 更新。M、A、B 只是阅读别名，实际 agent_id、task_id 和 revision 取已认证查询；不由模型发明。

## 接入与分工

用户选择 main，并让两个宿主对话接入。每个对话各有 Agent/session，不能靠相同 IDE/profile/cwd 共用身份。加入只获得相应基础权限；main 不拥有 Worker 的 Attempt。

M 为 API 和调用方创建 TA/TB，声明各自 scope 和必要 blocks；parent_task_id 只导航。文件任务各选 workspace.select，Git worktree 或外部根由 M 预先准备和绑定，再 ready/publish。可用 coordination.plan 一次生成任务、定向分派及持久通知；无固定 Worker 数量要求。

## 认知协商

A 报告字段可空，B 报告必填。显式 typed claims 引用同一 subject/equality key，参与者创建分歧并讨论；代码不判断业务方案谁更好。

参与者提交 Q1，required slots 指向具体 Agent；正文和槽共同产生 digest。每人接受自己的 exact slot/digest；最后必需槽接受后 proposal 才 accepted。ACK 不等于接受。改变正文/参与者须新 Q2；旧接受不转移。main proxy 记录真实 actor 与被代表 Agent。

只有 M 明确放入 Task.required_contract_ids 的契约阻止 begin；普通报告或无关协商不构成机械门槛。

## 一次开始与提交

A/B 读取任务当前 revision 后调用 task.begin。系统核对身份、定向分派、版本、scope、依赖、必要契约和隔离策略，在写事务前观察文件基线；短事务一次提交 Attempt、工作区、资源占用、Grant 和事件。冲突返回实际占用者，失败不留下 claimed 半成品。

正常结果为 running。Worker 工作期间无需续租；进度只记事实。task.submit 自动观察文件和生成 patch/Result，原子释放占用与执行 Grant，并给 M 持久通知。M review 接受普通任务或要求返工；Project 完成仍需用户。

## 上游阻塞与恢复

M 提出重大 API 决策，通知相关 A；不能仅靠提案假定 A 已停止。A 调用 block 保存摘要并释放资源，结束本轮；无关 B 继续。用户任意时间 resolve 都合法。

决策解除后 A 读取状态再 begin，新 Attempt 取得新基线并复用未变的任务策略。同库重启则保留原 running Attempt/owner/占用，原 owner begin 恢复同一 Attempt 的当前 Grant。新会话不能冒充；M 显式 recover 后才能交给新 Worker。宿主唤醒失败不使任务自动到期。

## 可核查结果

| 动作 | 持久事实 | 拒绝条件 |
|---|---|---|
| begin | Task/Attempt running、必要 baseline/reservation/Grant | 旧 revision、他人 owner、范围冲突、明确依赖未满足 |
| contract.accept | 自己槽的 immutable acceptance | 终态 proposal、错误 digest/槽/Agent、已有接受覆盖 |
| block | 挂起摘要、旧 Attempt blocked、资源 released | 错误 current attempt/owner |
| submit | Result、workspace result、撤权释放、通知 | 非 running 或他人 Attempt |
| recover | 精确旧 Attempt 关闭与释放，Task reopen/cancel/fail | Worker 调用、终态或错误 expected_attempt_id |
| 用户 resolve | 明确 proposal/revision/digest 的用户决定 | 不是 control 或内容已变 |
| completion.confirm | 项目完成及 checkpoint 操作 | 没有用户确认 |

自动验证：test_execution_begin.py、test_state_integrity.py；真实 CLI/HTTP/MCP 执行证据见 [FX2 进度](../../.trellis/tasks/09-28-fx2-execution-flow/implementation-progress.md)。原 Desktop 自动唤醒另由 FX3/FX6 验收。
