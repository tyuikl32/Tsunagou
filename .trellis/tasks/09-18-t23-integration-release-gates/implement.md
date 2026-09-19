# T23 执行步骤与交接

## 开始前

- [x] 检查依赖 T15, T16, T17, T22 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认 Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；当前任务为 in_progress，分支为 `elysia`。

## 实施步骤

- [x] 实现 validation 列出的核心故障子集，使用真实临时 SQLite、持久 inbox 和 loopback
- [x] 覆盖消息恢复、单 owner、旧 epoch、崩溃回滚和未知发布 gate
- [x] 校验命令 registry/OpenAPI/架构与生成物公共门槛
- [ ] 记录 Windows 完整基准和 macOS/Linux 实际支持范围（待对应环境运行）

## 检查

- [x] 无消息丢失/双 owner/旧 epoch 授权复活
- [x] 崩溃恢复不伪造成功和不盲重不可验证动作
- [ ] 所有工程阻断项通过，失败有最小复现
- [x] mock adapter 通过不冒称真宿主已完成
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 `python tools/docs/validate_docs.py` 和本任务 `task.py validate`，更新规范与上下文。

## 2026-09-19 首次真实验收

- [x] Python 3.13.15 环境完成同步；pytest 66 passed、1 skipped，Ruff、mypy（40 files）、协议校验（106 policies / 111 schemas）通过。
- [x] 修复 pnpm 12 构建审批占位值，仅允许 `esbuild@0.28.2`；冻结安装通过。
- [x] 修复根 TypeScript 检查指向不存在 `tsconfig.json` 的问题；6 个 workspace 检查、Vitest 19 tests、生成物零差异通过。
- [x] CLI `--version`、doctor、三个 enroll 外壳、临时 Git 项目初始化和 loopback HTTP health 通过。
- [x] Codex `0.155.0-alpha.9` 无模型探针证明初始化和同目录双 thread 隔离；空 thread resume/fork 返回 `-32600`，不得据此提升 ready。
- [x] 后续重试已跑通 OpenCode `1.18.31` 与 DeepSeek Harness `0.1.5-rc.2` 隔离真实探针，并形成 2026-09-19 脱敏证据。
- [x] 根据失败修复 bridge/adapter：语义指纹去重、并发合并、幂等冲突、受控重试、epoch 恢复、inbox claim/fetch/presented/ACK 分离及宿主身份/生命周期脱敏。
- [x] 修复 Codex Windows 探针的临时目录 ACL 与 UTF-8 解码问题；复跑证明初始化和 session isolation，空 thread resume/fork 仍如实为 `-32600`。
- [ ] `release_check.py` 仍按设计返回 1：三个首发宿主各缺其余 10 项真实共同基线；T23 不完成、不归档。

## 结束与交接

### 2026-09-19 elysia 环境复核与首轮续测

- 分支 `elysia`、HEAD `402cd6b`，测试前工作区干净；T23 负责人仍为 `tyuikl32`，本轮未修改指派。
- 当前执行环境只有 Python 3.14.7（项目要求 `>=3.13,<3.14`），`uv` 不在 PATH；`pnpm` 为 11.19.0（项目要求 12），`corepack pnpm --version` 因缓存目录权限报 `EPERM`。OpenCode 与 `dsh` 不在 PATH；未安装软件或调用网络获取包。
- 对 OpenCode 与 dsh 分别尝试 `npx --no-install ... --version` 均退出 1（`ENOTCACHED`）；离线缓存不可用，未授权在线下载，因此两项真实探针本轮未运行。
- `codex-cli 0.155.0-alpha.9` 的一次性无模型探针退出 0：初始化及同目录双 thread 隔离通过；空 thread resume/fork 返回 `-32600`；其余共同基线保持 unknown，`ready: false`。本轮输出仅保存在临时验收目录，未覆盖仓库已有 evidence。
- `release_check.py` 退出 1：Codex、OpenCode、DeepSeek 各缺 session isolation 以外的 10 项正式证据。`python -B tools/docs/validate_docs.py` 退出 0。当前 Python 无 pytest、Ruff、mypy 模块；完整质量门禁未能在本轮环境复跑，不能将环境阻断记为产品测试失败。
- 源码复核确认 CLI `agent enroll` 仍固定返回 `ticket_required`，真实 ticket 兑换与 HostSession 接入未由本轮验证。没有建立两个真实 Agent 的 Tsunagou 协作会话；T23 继续保持 `in_progress`，不归档。
- 继续追查接入阻断（源码推断，非真机通过/失败）：`src/tsunagou/api/app.py` 的默认 dispatcher 没有注册业务 handler，HTTP 目前按调用方提供的 `X-Principal-*` 请求头传入身份；`AuthorityService` 虽有 ticket 发行/兑换方法，但 CLI、HTTP 和宿主 bridge 之间尚未接成可信链路。真实接入需跨 T06/T16/T17–T21 的身份、凭据和 handler 设计，不能仅把返回字符串改成 `ready`。
- 发现待裁决的契约差异（源码/文档对比，未修复）：`docs/implementation/modules/02-agents.md` 允许 fetched 或 presented 后 ACK，`.trellis/spec/adapters/index.md` 与当前 BridgeClient 则要求先 presented；回归前需明确统一语义。另需覆盖“旧 epoch 请求尚在执行时发生重连”的并发测试；当前测试只证明已完成结果在重连后重新进入 transport。
- 收尾验证：`git diff --check`、T23 `task.py validate`、文档校验均退出 0；未运行 Python/TypeScript 全量测试，也未提升任何宿主能力状态。

### 2026-09-19 首轮真实宿主取证与 pytest 入口回归

- cc 在独立临时协调项目执行本地门禁、三个无模型真实宿主探针与 CLI/HTTP 接入检查；Codex `0.155.0-alpha.9`、OpenCode `1.18.31`、DeepSeek Harness `0.1.5-rc.2` 的原始探针 JSON 经审查后以 `docs/research/evidence/*-2026-09-19T*.json` 保存。JSON 均为 11 行基线、仅 `identity.session_isolation` 有 `supported` 与引用、其余 10 行 `unknown`、`ready: false`；没有 token/cookie 字段或私人绝对路径。仓库副本与临时原件的 JSON 内容相等；行尾格式不同，字节哈希不相同。
- cc 实测三个 `agent enroll` 均停在 `ticket_required`；`agent.ticket.create`（M）与 `agent.enroll`（T）的 HTTP 尝试均返回 404 `handler_not_registered`。源码复核：CLI 返回值固定，默认 HTTP dispatcher 未注册业务 handler，且请求身份目前来自调用方请求头；只注册 handler 或改 `ready` 字符串不足以形成可信接入。没有两个真实 HostSession，11 项协作顺序测试未进入。
- cc 的 `uv run pytest -q` 在收集 probe 测试时找不到仓库 `tools`；本轮独立复现同一导入错误。`pyproject.toml` 为 pytest 配置仓库根导入路径，新增工具链策略测试防止回退。使用已安装环境的 `uv run --no-sync pytest -q` 返回 0；给 uv 指定可写的同盘缓存后，文档原命令 `uv run pytest -q` 也返回 0（1 skipped）。沙箱默认 pytest 临时目录与 uv 默认跨盘缓存错误属于当前执行环境问题，未计为产品测试失败。
- 真实 bridge 接入需要 CLI 用户控制凭据、私下票据兑换、服务端认证、HostSession 绑定及注册领域 handler，跨 T16/T17/T18–T21；未在 T23 验收任务里以未认证的 HTTP 请求头拼接替代实现。三个首发宿主的正式基线仍各缺 10 项，T23 保持 `in_progress`。
- 最终复核：Ruff、mypy（40 files）、协议校验（106 policies / 111 schemas）、6 workspace TypeScript、Vitest 28/28、文档校验和 T23 上下文校验均退出 0。`release_check.py` 仍退出 1，仅报告 Codex/OpenCode/DeepSeek 各缺其余 10 项 live baseline；没有修改检查逻辑。

### 2026-09-19 Codex 单宿主快速试验

- 用户要求先聚焦 Codex 的其余十项，不把这项试验误报为三宿主首发通过。试验记录：`docs/acceptance/codex-pilot-2026-09-19.md`；新探针 JSON：`docs/research/evidence/codex-2026-09-19T170100.json`。
- 本机 Codex 已更新为 `0.155.0-alpha.9.2`；无模型探针退出 0，仍只证明原生 thread 隔离，空 thread resume/fork 返回 `-32600`。`agent enroll --adapter codex --mode attach` 退出 0 但结果为 `ticket_required`；没有 ticket 兑换、两个真实 HostSession 或第 8 节十项正式操作。
- 定向 Codex adapter + bridge Vitest 17/17、Python 全量 pytest（1 skipped）、Ruff、mypy、协议校验和六 workspace TypeScript 检查退出 0。`release_check.py` 退出 1，Codex 及另两个首发宿主各缺十项；检查规则未改。
- 工作区另有正在审查的恢复/身份安全改动，尚未提交，不能把本地测试通过说成 Codex 真机协作已通过。T23 仍 `in_progress`，原负责人 `tyuikl32` 不变。

#### Bug Analysis: 旧 epoch 在途结果污染新连接

1. **根因类别**：D（并发测试缺口）+ E（隐含“重连时没有在途请求”的假设）。`reconnect()` 只清理已完成缓存，没有隔离 `inFlight`；旧 Promise 可能被新 epoch 请求复用。
2. **修复过程**：首次真实验收复核只发现风险、未修改；本轮在原拥有缓存的 bridge-sdk 处让更高 epoch 清理在途映射，旧请求完成/重试前检查连接代次，旧请求的 finally 只清理自身映射，避免删除新请求。没有通过 HTTP/宿主真机验证，不能夸大。
3. **防复发机制**：P0 并发回归同时保持旧/新 transport 请求，先释放旧响应，断言旧请求 `stale_connection_epoch`、新请求仍需新凭据/epoch 并独立去重（已加入 Vitest）；P1 真机断线重连时验证服务端幂等（未完成）。规则已写入 `.trellis/spec/adapters/index.md`。
4. **系统性扩展**：其他跨代缓存（inbox、Lease、认证上下文）也需逐项审查，不能因为同步单元测试绿就认为断线时序安全。
5. **知识固化**：上述 spec 已更新；仓库没有 `src/templates/markdown/spec/` 可同步。暂不提交本轮改动。

#### Bug Analysis: 自报身份和布尔值 ready

1. **根因类别**：B（CLI/HTTP/authority/adapter 身份契约未贯通）+ D（只测服务对象，缺真实 HTTP/宿主链路）。默认 HTTP 接受调用者自填 principal 请求头；`baseline_ok: true` 可直接标 ready，忽略十项缺口。
2. **修复过程**：本轮将 HTTP 身份改为可配置凭据解析、默认拒绝业务请求；服务端逐项要求 11 个 `supported` 和非空证据引用，degraded 无正式基础 Grant、不能任命 main；票据磁盘状态只留哈希。此举不等于已验证证据来源，也未完成 T 主体兑换或领域 handler。
3. **防复发机制**：P0 测试无 bearer、旧 epoch、degraded、U/Agent 凭据隔离、票据/会话密钥不落盘（已有单元断言）；P0 真 Codex 两会话私下兑换和跨身份拒绝（未完成）；P1 所有业务 handler 做 grant/scope/revision 检查（未完成）。可执行契约已写入 `.trellis/spec/backend/entrypoint-contracts.md`。
4. **系统性扩展**：`mcp_tools()` 名单、Schema、OpenAPI、真实 daemon 配置均需同一身份来源；不应在某个 transport 上补一个“可信 header”旁路。
5. **知识固化**：跨层检查清单已更新；没有 spec 模板副本可同步。暂不提交本轮改动。

#### Bug Analysis: pytest 命令入口不一致

1. 根因：D（测试覆盖缺口）兼 E（隐含假设）。此前只用 `python -m pytest` 可从当前目录导入 `tools.*`；文档中的 `pytest` console entrypoint 不保证把仓库根目录放进 `sys.path`。
2. 掩盖因素：只验证模块形式的测试命令，未运行文档中的原始命令。首次修复后沙箱临时目录权限另起假失败，已用非沙箱回归区分。
3. 防复发：pytest 配置显式加入仓库根目录；`tests/integration/test_toolchain_policy.py` 锁定配置；`.trellis/spec/backend/quality-guidelines.md` 要求验证两种入口。
4. 扩展检查：其他 CLI 入口若依赖仅在当前目录可见的仓库模块，也应以文档中的实际命令验证，而不以 `python -m ...` 替代。
5. 知识固化：相关 backend 规范已更新；仓库无 `src/templates/markdown/spec/`，不存在可同步的模板副本。

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在 Trellis journal 记录本轮结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
