# FX1 实施与验证

日期：2026-09-28。分支 codex/live-test-repair；尚未提交。用户已授权完成全部 FX 任务。

## 已完成

- cognition 本人/代理接受共享 proposed+digest 检查，终态不可复活；slot 接受不可覆盖原操作者。
- 参与者只接受明确 slot/agent_id；拒绝空白、字符串、重复 slot、未注册项目成员。相同 Agent 可承担多个不同 slot。
- proxy 保存真实主 Agent 与代表的 Agent ID，返回整个 proposal_status；不再以 slot 代替身份。
- supersede 先验证并创建替代版本再关闭旧版本；原提议者身份保留，公开入口校验原提议者。
- 无 claimed/running current Attempt 的取消直接 cancelled；blocked Attempt 记录 ended_at；submitted 结果保留。有执行者需 owner ACK 或 main 回收；普通 submit 无法绕过 cancel_requested。
- main 回收更新 Attempt revision/ended_at，终态任务不允许再取消、失败或重开。
- 更新命令目录、手写 Schema、样例、打包协议镜像、模块文档和用户手册；旧空 supersedes_id 样例改为省略可选字段。

## 验证范围

单元回归覆盖终态矩阵、参与者结构、代理权限及身份、部分接受、替代失败、取消矩阵与 main 回收。真实应用集成使用独立临时 Git 项目和 SQLite，经过认证和 command UoW，不直接改库构造成功。

S1–S5 覆盖失败无 domain/event 副作用、主从权限、同 command_id 原响应重放与新命令拒绝。S6 通过释放数据库进程锁后重新 build_application 读取同库，检查契约、代理身份、取消、事件时间不变；真实 history 查询投影及 CLI JSON/文本渲染均检查。CLI 测试仅替换网络跳转，不声称完成真实宿主接入验收。

具体执行命令与时间保存在 [validation.json](validation.json)。FX2 将继续验证显式 ResourceReservation 和 Grant 与取消的同事务收口；FX3/FX6 的真实 Desktop 验收不属于 FX1 完成证明。

## 本轮纠正的测试假设

- 原 unit fixture 把可选 supersedes_id 写为空字符串；已改为省略，未添加兼容分支。
- 审计数据库使用 event_type 存命令种类，actor_ref 保存实际 Agent ID。集成断言已按真实接口修正，未为测试改变存储语义。
