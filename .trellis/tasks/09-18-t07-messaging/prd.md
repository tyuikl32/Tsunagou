# T07 持久消息、收件箱与回应义务

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- Message/RoutingSnapshot/Delivery/ResponseObligation
- pull/fetch/ACK/response端口
- SSE高水位与outbox投递

## 前置依赖

T06。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 固化sender/recipient/response contract和payload限制，正文领域授权
- 实现投递租约、批量限制、优先级aging、fetch后去重、defer和ACK
- 实现response/waive/supersede义务与发送同UoW；ACK不满足义务
- 实现push失败抑制和SSE提示，重连REST sync，无replay真相表

## 验收标准

- [x] 重传不重复消息/回应，主Agent不能读取他人inbox（command_id 去重、recipient-scoped fetch/ack）
- [x] 无push仍能完整pull恢复（`sync` 与过期 delivery lease）
- [x] 无presented证据不标已呈现，无retry次数自动deadletter（ACK 与 present 分离、无隐式 deadletter）
- [x] payload/summary/batch限制与过期租约行为跨语言一致（固定上限与 30 秒 delivery lease）

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
