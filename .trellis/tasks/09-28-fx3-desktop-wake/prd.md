# FX3 Codex 原会话自动唤醒

状态：planning；需求 FX-R03，遵守 FX-D03/04。无代码依赖，可优先实施；与 FX4 接入集成后由 FX6 最终验收。

## 目标与证据

daemon 的消息触发用户手动创建的原 Desktop 会话，用户无需再发“继续”。当前独立 listener 的 thread/resume 报 active writer；新发现的应用工具管道 tools/list 实际可达，但发送和后台生命周期尚未验证。[研究及版本](../09-28-real-test-repair/research/codex-wake-control.md)。

## 验收

| ID | 可观察结果 |
| --- | --- |
| W1 | 空闲的手动 Desktop 原 thread 被 daemon 自动触发，原 agent_id 实际读取收件箱；应用侧能看到新回合 |
| W2 | 接入会话的当前回合结束后仍能触发；无需开发者对话持续运行，无替代 thread/Worker |
| W3 | 已确认接受的同消息重送不重复启动回合；结果未知先核对再重试；忙时合并待处理通知，结束后处理，不每条消息另起推理 |
| W4 | daemon/bridge 重启后仍使用同一绑定；Desktop 重启通过重新启动的宿主 bridge 自动登记新连接，不要求用户复制 endpoint/ID |
| W5 | 不因唤醒改角色、范围、模型、approval 或 sandbox；不触发无关项目和未绑定会话 |
| W6 | 不可达、拒绝、超时和结果未知可按消息查询；未处理消息不丢；人工跟进不覆盖此前失败 |
| W7 | managed 路径继续通过真实消息闭环；其成功不代替 W1/W2 |

## 约束

允许维护私有本机接口，不修改应用二进制、不删 writer 锁、不伪造其他活跃回合。真实调用路径仍有工程风险，第一步即验证它；工具目录、mock 和方法存在不是完成标准。设计见 [design.md](design.md)，步骤见 [implement.md](implement.md)。
