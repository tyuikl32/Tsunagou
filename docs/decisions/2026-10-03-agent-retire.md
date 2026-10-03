# D196 Agent "删除"做成退役：他不能再动，但历史一字不改

日期：2026-10-03
状态：已实施（前端按钮与后端命令都接线完成）

## 决定的形状

"删除 Agent" = **让他退役**（协议里早就声明了 `agent.retire`，这一轮把用户入口装配起来）。

- **只有用户能删**：新命令 `agent.retire.user`（U 权限），控制台持 U 令牌，页面按钮走它。
- **退役 ≠ 抹掉**：Agent 记录留着（名单显示"已退役"），任务归属、消息作者、契约接受者
  仍然写着他的名字 —— 历史不改写，否则审计就碎了。退役做的是**让他不能再动**：会话结束、
  凭据立即失效、授权全部收回、权威代次递增。
- **不给"回来"的路**：那条会话再接入就是新的一员，原身份不恢复，页面上也不承诺找回。
  记录一条都不删（理由只是"历史不能改写"，不是为了以后能恢复）。
- **当前主 Agent 不能删**（项目永远有且只有一个主 Agent）：拒绝码 `main_agent_cannot_retire`，
  提示先设别人当主。
- **手上还有活就不能删**：拒绝码 `agent_has_open_work`，并把"他还占着哪些任务"一起返回
  （`CommandRefused` → 409 带 `tasks`），页面照着列。第一版只拒绝，不自动收敛。
- **远端 Agent 只能在本机侧停掉**：他那台机器上的登记与配置我们碰不到，返回里带
  `machine`/`remote_registration_hint`，确认框与提示据此告诉人"去那台机器上清掉"。
- 退役的席位在页面上只剩"查看"：不再有"设为主 Agent"，也不再有"修改/删除"。

## 落点

- `modules/authority.py`：`retire_agent`（会话/授权/代次/状态）、`_retired_summary`；
  `authorize` 在会话检查之前先答 `agent_retired`，让被退的人下次调用得到的是一句明白话。
- `modules/tasks.py`：`open_work_for(agent_id)`（占着 Attempt 且任务未收尾）。
- `shared_kernel/errors.py`：`CommandRefused(code, detail)` —— 拒绝时把事实一起给出。
- `application/handlers.py`：`retire_agent` handler + 命令表；`api/app.py` 映射 409 + 事实。
- `docs/implementation/command-catalog.md` + `protocol/registry/commands.json` + schema
  （`agent.retire.user`）；CLI `agent retire`；词表补 `已退役 / 还有活 / 主不能删 / 删除`。
- 页面：`agentRemove` 命令位接上 `agent.retire.user`，`actions.removeAgent` 走确认框 +
  失败时列出任务；删除按钮对当前主 Agent 与已退役席位不画；`#delPmt` 的占位文案改单数。

## 一并修掉的坑

`tools/codegen/generate_protocol.py` 以前只把协议同步给 Python 侧，桥那边留着自己那份旧副本
—— 命令一改，桥的调用就会 `schema_bundle_digest_mismatch`。现在两侧一起同步。
