# 首发本机认证与主从边界

> 核对日期：2026-09-17。
> 状态：用户已确认的首发范围；对应 D93，并覆盖 D54/D55 中过重的 token 轮换、凭据库与浏览器接入设计。

## 首发安全目标

首发只支持同一用户在本机运行调度中心和多个 Coding Agent。认证机制服务两个目标：

1. 让服务端稳定识别请求来自 user/control、哪个 Agent 和哪个 HostSession；
2. 让服务端根据当前项目状态强制主 Agent、子 Agent、任务 owner 和资源 scope 的边界。

首发不把认证机制描述成恶意进程隔离。拥有同一 OS 用户 Full Access 的进程原则上能够读取本机文件、调试其他进程或绕过自然语言约束，因此本方案不承诺防止此类主动攻击。它保证的是：只要请求通过调度中心的正式 API/MCP 工具，就不能靠伪造请求字段、旧角色或错误任务 ID 获得管理权或接管任务。

## 明确延后的工作

- 用户账号、密码、OAuth/OIDC、API key 管理和多租户登录；
- JWT、公私钥签名、PKI、mTLS、证书生命周期和 TLS termination；
- access/refresh token 轮换、系统凭据库适配和跨设备登录；
- LAN/公网监听、远程威胁防护、rate limit 和恶意客户端隔离；
- Web Cookie、浏览器 session、CORS、CSRF、origin 配对和 WebSocket 认证；
- 同一 OS 用户下抵御 Full Access Agent 窃取其他凭据。

未来启用 Web 工作台或远程连接时必须重新进行威胁建模，不能把首发 session token 直接提升为远程认证方案。

## 传输与凭据

### 本机端点

- daemon 只绑定 `127.0.0.1` 的随机端口，endpoint manifest 记录 instance ID、端口、PID 和启动时间，不包含 token。
- 首发关闭 CORS，不支持 Cookie，也不监听 `0.0.0.0`、LAN 地址或 Unix/Windows 远端转发。
- bridge/CLI 在 `Authorization: Bearer <opaque-token>` 发送凭据；不得放入 URL、query、JSON body、prompt 或命令行参数。

### Control token

- daemon 初始化时生成 32 字节随机值；使用 Python `secrets.token_urlsafe(32)` 或等价 OS CSPRNG。
- 仅 CLI/用户控制面持有，映射为 `principal_kind=user_control`。
- Agent bridge 不读取、不转发 control token；任何 Agent session token 都不能调用 user-only 命令。
- 服务端保存 hash；runtime 私有文件仅当前 OS 用户可读。首发不接入 Windows Credential Manager。

### Agent session token

- attach/enrollment 成功后为每个 HostSession 生成独立 32 字节随机 opaque token；服务端只保存 hash。
- token 查表得到 `project_id`、`agent_id`、`host_session_id`、`status` 和创建/撤销信息。token 自身不携带可被信任的 role、capability、task 或 root claims。
- 生命周期与 HostSession 一致，无 refresh token。detach、revoke、retire、project archive/delete 和明确的 session invalidation 立即令其失效。
- bridge 在内存中代持；若宿主重启恢复必须落盘，则写 daemon/adapter 的 runtime 私有目录并限制为当前 OS 用户读取。文件不进入项目目录或 Git。

### Enrollment ticket

- ticket 是 32 字节随机 opaque token、默认十分钟有效、单次兑换，服务端只保存 hash。
- 普通 worker ticket 与 D91 的 `main_agent_enrollment_ticket` 使用不同 kind 和 handler；普通 ticket 永远不能因为先连接而获得主 Agent权力。
- ticket 限制 project、candidate/host 条件、初始授权上限和签发者。兑换成功后在同一事务消费，重放返回已消费错误而不新建 session。

[Python `secrets` 文档](https://docs.python.org/3/library/secrets.html)将该模块定位为生成认证 token 等安全随机值；[RFC 6750](https://www.rfc-editor.org/rfc/rfc6750)指出 bearer token 的持有者即可使用其权限。因此首发虽然不实现 OAuth，仍必须避免 token 进入日志、URL、prompt 或 Agent 可见参数，并为不同 session 使用不同 token。

## 认证与授权分离

认证 middleware 只输出不可伪造的 `RequestPrincipal`：

```text
RequestPrincipal {
  kind: user_control | agent_session
  project_id?: ProjectId
  agent_id?: AgentId
  host_session_id?: HostSessionId
  credential_id: CredentialId
}
```

请求 JSON 中即使出现 `actor_agent_id`、`role=main`、`owner_agent_id` 或 `capabilities`，也只能作为目标/数据字段，不能覆盖 `RequestPrincipal`。Application command handler 从 principal、数据库当前状态和 expected revision 构造授权上下文。

每个受保护命令至少按以下顺序判断：

1. endpoint 是否允许当前 principal kind；
2. principal 是否属于目标 project/lineage/active replica；
3. HostSession、Agent 和 project lifecycle 是否有效；
4. authority epoch、current main identity、task attempt owner 是否匹配；
5. 当前 grant、root scope、project policy、condition/blocker 和 operation intent 是否允许动作；
6. expected revision/epoch 是否仍匹配，然后才进入 Unit of Work。

认证成功不代表授权成功。服务端必须在每次命令执行时读取当前 authority/task/grant 状态，不能把 attach 时的 role 缓存在 token 中长期使用。

## 主 Agent与子 Agent边界

| 动作 | User/control | 当前主 Agent | 子/普通 Agent |
|---|---:|---:|---:|
| 首次任命/紧急撤销主 Agent | 允许 | 禁止 | 禁止 |
| 计划 handoff | 允许 | policy 与 grant 允许时 | 禁止 |
| 修改用户 LocalAccessCeiling | 允许 | 禁止 | 禁止 |
| 在 ceiling 内签发 worker ticket | 允许 | 具备 `agent.enroll` 时 | 禁止 |
| 创建/发布根任务 | 允许 | 允许 | 禁止或仅提交请求 |
| 创建自己的子任务 | 允许 | 允许 | grant 允许时 |
| 执行自己当前 attempt | 不适用 | 允许 | 允许 |
| 执行其他 Agent 的 attempt | 禁止 | 禁止 | 禁止 |
| 修改其他 owner 的 attempt 结果 | 禁止 | 禁止；只能取消/关闭后重建 | 禁止 |
| 代表主 Agent确认契约/管理授权 | 用户 override 使用独立语义 | 允许 | 禁止 |

“主 Agent”是 project authority 角色；“task owner”是某个 TaskAttempt 的执行者，两者独立。成为主 Agent不会自动取得其他 Agent 正在运行的 attempt，主 Agent也不能把自己的运行中 attempt 原地改 owner 给子 Agent。

主 Agent委派工作时创建子任务或关闭旧 attempt 后创建新 attempt。子 Agent只能领取/执行显式属于自己的 TaskAttempt，并向父任务提供结构化结果。父任务是否完成、是否接受子任务结果仍由父任务 owner、验收策略和相关契约决定。

## 最小服务端数据

首发不需要 OAuth authorization server。至少保存：

- `credentials(id, kind, token_hash, status, created_at, revoked_at)`；
- `host_sessions(id, project_id, agent_id, host_instance_id, status, created_at, last_seen_at)`；
- `agents(id, project_id, status, adapter_kind, capability_snapshot_id)`；
- `project_authority(project_id, current_main_agent_id, authority_epoch, status, revision)`；
- 已规划的 grants、TaskAttempt owner 和 command result/idempotency 表。

credential/HostSession 属于本机 runtime 状态，不写入 `.tsunagou` 共享 Git 历史。共享历史可以记录稳定 agent identity 和 authority 事件，但不包含可使用的 secret。

## 必须通过的验收场景

1. 子 Agent把请求 body 的 actor/role 改成主 Agent，服务端仍按 token 映射的真实 agent 拒绝管理动作。
2. 子 Agent使用自己的 token 对主 Agent attempt 调用 start、submit、complete 或写结果，返回 `attempt_owner_mismatch`。
3. 主 Agent创建子任务后，子 Agent只能操作子任务 attempt，不能改变父任务 owner 或父 attempt。
4. handoff 完成后，旧主 Agent的同一 session 不能执行 management command；若仍有普通 grant，只能执行该 grant 允许的普通动作。
5. 两个 Agent不得复用同一 session token 建立两个有效 HostSession；检测到 token/session binding 不符即拒绝。
6. 普通 worker enrollment ticket 无论连接顺序如何，都不能触发 main-agent appointment。
7. token、ticket 和 Authorization header 不出现在结构化日志、异常、trace、SQLite audit payload 或 Git 文件中。
8. daemon 不能从非 loopback 地址连接；预检确认未监听 `0.0.0.0`。

## 仍需决定

- 主 Agent将自身任务拆给子 Agent时，父任务与子任务的完成/验收关系。
- HostSession 连续性的最小心跳和重连规则，以及 bridge 重启是否复用 session。
- 具体 capability/grant 数据模型与撤销投影。
- 何种 adapter 能提供独立子 Agent session；不能提供时是否完全禁止独立子 Agent。
