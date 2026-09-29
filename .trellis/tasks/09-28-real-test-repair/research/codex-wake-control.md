# Codex 唤醒：会话控制路径与本轮交付边界

核查日期：2026-09-28；源码基线 `1fb86e0`；本机 Codex `0.158.0-alpha.2.1`。本记录用于修复设计，不是已完成验收，也不是新增能力证明流程。

## 已经证明的问题

[本轮原始补测](../../../../docs/acceptance/evidence/sega-image-manage-tool-2026-09-28/native-wake-followup.md)分出了两个独立原因：最初没有启用 provider；补齐配置后，新的 listener 可以读取 Desktop thread，但 `thread/resume` 实际返回 RPC `-32600`，错误为 `already has an active writer`。旧方案中「启动另一个 listener → 读取原 thread → 宣称 ready」不能成立。

消息本身已经持久化，后来的同身份读取和 ACK 由应用跟进触发；这证明消息未丢失，不能证明 daemon 成功唤醒。诊断漏记 provider 失败也是独立代码缺陷，必须修复。

[此前受控会话实验](../../../../docs/research/evidence/codex-app-server-managed-2026-09-23.json)已经验证 managed 路径启动模型回合并读取收件箱。不能把已有 managed 实验重复包装成 Desktop 修复成果。

## 官方接口核查

- [App Server](https://learn.chatgpt.com/docs/app-server)：`thread/read` 读取存档，不等于恢复；恢复和启动分别有 `thread/resume`、`turn/start`。`turn/steer` 面向已有活跃回合。CLI 可以通过 `--remote` 连接同一 app-server。这些接口证明「可控制的 app-server 能执行回合」，没有解决独立 listener 接管 Desktop writer 的实测冲突。
- [Developer commands](https://learn.chatgpt.com/docs/developer-commands)：`codex remote-control` 与 managed daemon 管理面有关，不能据此把它当作现有 Desktop 控制连接。本机 `codex app-server daemon enable-remote-control --help` 同样明确指向 managed daemon。此次只读取帮助，没有启动、停止或改变配置。
- [Remote connections](https://learn.chatgpt.com/docs/remote-connections)：桌面远程访问和 SSH 工作流有产品支持；SSH 路径由应用启动远端 app-server。本轮检索没有找到供独立 Tsunagou daemon 直接控制现有本机 Desktop stdio 进程的公开接入步骤。这里是证据尚未建立，不是断言所有宿主版本永远不支持。

这些结论不授权删除宿主锁、结束用户应用或修改其私有运行状态。`mcp__codex_app` 在本开发对话内可调用，也不能推导为 Tsunagou 安装后可从 Python 调用的接口。

## 必须改正的实现和验收

1. `src/tsunagou/hostwake/codex_app_server.py` 的 `DesktopAttachProvider.register_binding` 只能说明绑定配置已存；`thread/read` 成功不能作为可启动原会话的完成条件。不引入额外检测仪式，真正发送消息时使用真实执行结果。
2. provider 失败沿现有 outbox/诊断链落盘，包含发生时间、原始错误类别、agent/message/wake 关联。收件箱消息继续存在；后续人工启动处理不覆写先前失败。
3. 忙碌的原会话、空闲的原会话及连接恢复，须在其实际控制连接上验证。另建 thread、换 Worker、删锁或手动发送跟进均不能替代原会话自动唤醒验收。
4. 事件记录区分 daemon 自动触发与用户/开发工具跟进；协议接收、宿主接收、模型回合启动、收件箱处理分别记录真实时间，不新增一套独立业务状态机。
5. 无论最终交付顺序如何，资源简化、契约终态、取消收口和安装定位均不依赖 Desktop 控制路径，可以先实施和验证。

## 已确认的用户目标：FX-D03

用户此前选择组合方案 C，先完善受控会话，长期偏好手动创建的 Desktop 会话接入。本轮仍按这个目标规划；没有擅自把 Desktop 自动唤醒降为手动轮询。

用户已经选择 A：[手动创建的原 Desktop 会话自动唤醒继续作为本轮关闭条件](../../../../docs/decisions/2026-09-28-desktop-wake-required.md)。不以 managed 通过结束本轮，不再询问这一目标。获得实际控制路径属于接下来的技术工作，研究结果和产品验收分别记录。

## 后续发现：应用自带工具管道

2026-09-28T08:40:27Z 的独立 Python 只读请求取得了[真实工具目录](codex-app-pipe-readonly.json)。这是新找到的本机连接证据，不是仅依据本开发对话的工具列表做推测，也尚不是唤醒通过。

- 安装包：OpenAI.Codex_26.924.2738.0_x64；包内应用版本 26.924.22138；CLI 仍为 0.158.0-alpha.2.1。
- 本机 codex-app-tools 插件 0.1.5 的 server.mjs（约 24773、24870、24965、25097 行）读取宿主传入的 CODEX_APP_TOOLS_PIPE_PATH，使用带长度前缀的本机 JSON-RPC 管道。没有扫描其他用户的管道、读取令牌或改变 peer authorization。
- tools/list 返回 codex_app 的 list_threads、read_thread、wait_threads、send_message_to_thread。独立 Python 进程已经实际收到结果；原始 endpoint 不写入归档。
- 应用资源中的 main-DAwJoFgo.js 实现对应的工具转发服务；send_message_to_thread 的调用需要 callerSource、threadId、turnId、callId 等上下文。不能因为列表可读便假定 daemon 长期持有合法调用上下文。
- 本次没有执行 tools/call、没有发送消息或启动回合、没有安装插件、没有修改应用文件或用户配置。

按 FX-D04 拟采用 Codex 专用的薄宿主适配器：enrollment 通过当前宿主自动登记连接信息；daemon 经合法的宿主连接请求在目标原会话继续；持久收件箱、去重和失败追踪仍复用 Tsunagou。它可能避免另起 app-server 抢 writer，但这只是基于路由位置的推断，尚须实际发送并观察原会话。

与旧 host-wake 设计的公开 app-server 路径相比，这条管道没有本轮已找到的公开稳定协议承诺。用户已选择 A，[FX-D04](../../../../docs/decisions/2026-09-28-codex-local-app-interface.md) 允许将它作为 Codex 专用实现路径，并接受版本适配成本。旧设计排除 Desktop 私有 RPC 的限制由此替代，不再继续询问这个选择。

实施必须验证：有效 caller 上下文及空闲后的合法性、原 thread 路由、宿主升级与重启后的重新登记、默认权限/确认机制、重复触发和真正 turn_started。不能伪造仍活跃的调用身份、关闭宿主校验、复制私人会话凭据，或以轮询 LLM 作为等价实现。若合法调用路径不成立，应保留失败事实继续寻找其他接口，不能以目录返回成功关闭 FX-R03。
