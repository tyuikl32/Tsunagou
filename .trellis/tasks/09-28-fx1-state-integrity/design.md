# FX1 技术设计

状态：已按授权实施；验证记录见 implementation-progress.md。仅修改现有认知、任务与应用端口。

## 契约入口与状态

contract.propose 保留 required/optional 两组，元素统一为 {slot: string, agent_id: string}。两字段非空白；slot 在两组间唯一；required 至少一项。同一 Agent 可承担多个语义 slot。删除字符串参与者和 _slot 身份猜测。

protocol/schemas/commands/contract/propose.schema.json 负责 wire 结构；handler 查项目成员存在性；domain 检查结构和 slot 唯一性。沿现有 Problem 返回字段及原因，不复制身份数据库。

本人/代理接受共享状态检查：只修改 proposed 且 digest 一致的 proposal。代理接口用 participant_slot_id 定位，服务解析真实 agent_id；acceptance 保存 real_actor_id 与 represented_participant=agent_id。沿用 contract.accept_proxy 权限，worker 不可代理。

| 操作 | 来源 | 结果 |
| --- | --- | --- |
| accept / proxy accept | proposed | 记录 slot；required 全满足才 accepted |
| reject / withdraw | proposed | rejected / withdrawn |
| supersede | proposed / accepted | 验证并创建新 proposed，再将旧记录 superseded；同一事务 |
| 接受已终结 proposal | accepted / withdrawn / rejected / superseded | 拒绝；同 command_id 重放由已有幂等层处理 |

_mark_proposal_accepted_if_complete 自身也只接受 proposed。替代失败不先修改旧状态。contract.accept 返回区分本次 slot 接受与整个 proposal，增加实际 proposal_status 并同步 fixtures。

实施明确：替代提案沿用原提议者，公开 propose 的 supersedes_id 仅允许该提议者使用；未替代时省略字段，不传空字符串。已接受 slot 的新命令拒绝覆盖，保留原 actor；原 command_id 仍由幂等层返回原响应。业务元数据保持可选，不增加结构外语义门禁。

## 取消

复用 TaskService.request_cancel。活跃执行者指 current Attempt 为 claimed/running，或已有 cancel_requested 且该 Attempt 仍未终结；不以心跳、连接或时间判断。

- 无活跃执行者：直接 cancelled。blocked Attempt 一并 cancelled，记录 ended_at。
- 有活跃执行者：cancel_requested，保留占用到 owner 确认或 main 显式回收；正常 submit 不得绕过取消。
- submitted 的结果保留为历史；此时取消可直接结束任务。
- main recover(cancel) 可终结活跃 Attempt；worker 无此权限。

取消、Attempt 收口、占用释放、Grant 撤销和 outbox 经同一 command UoW 提交；资源及 Grant 的完整联动与 FX2 集成。Full Access 的 OS 写入不因逻辑撤权而被声称已停止。

## 留痕

复用 command/event/diagnostic，记录 actor、被代理者及关联标识。公共时间使用带时区的 UTC。拒绝不写业务成功事件，不新建审计数据库，不处理旧格式迁移。
