# 第三轮：实施边界最终确认（D161–D181）

记录日期：2026-09-18。来源：本任务上一轮 Plan 模式的用户逐项回答及后续澄清。这些决定已确认；这里补存此前受 Plan 模式限制未写入磁盘的内容。

## 决策账本

| ID | 最终决定 | 实施边界与覆盖关系 |
|---|---|---|
| D161 | 无状态应用工作流层 | `application/workflows` 编排八模块 public ports 与一个共享 UoW；不拥有业务表、不裁决语义、不成为第九模块。覆盖关系见架构规范。 |
| D162 | 完成事务提交即 completed | user 确认事务改变 lifecycle，同时登记必需 completion checkpoint Operation；未完成/失败显示 durability blocker，阻止归档及基于该结果的发布，不回滚用户结论。不新增 completing lifecycle。细化 D26、D153、D160。 |
| D163 | 本地命名引用可达才锚定 | 重申 D82：仅同 repository 的 `refs/heads/*`、`refs/tags/*` 可达并完整验证的 checkpoint；不要求当前 HEAD；remote tracking、reflog、detached HEAD、裸 OID 不构成锚点。 |
| D164 | 未锚定只门禁恢复性动作 | 普通协作、项目完成、本机归档可继续；跨 replica 激活/接管要求来源可验证锚点。最后本机副本清理不能把本仓库锚点当异地备份；缺独立恢复副本时只能 user 显式接受精确丢失清单。 |
| D165 | 按需加载后常驻 | 首次请求、连接或待处理 Job 时加载项目，常驻到 daemon 退出、归档或 unregister；首版无空闲计时卸载。启动扫描任务索引/数据库恢复 Job，不要求所有项目长期同时打开。 |
| D166 | 不合并 sealed lineage | 旧 lineage 仅审计、诊断和恢复来源；首版不支持跨 sealed/current lineage 合并。同 lineage checkpoint 分叉仍按 D27 三方合并；此前问答把它误称 D72，D72 实为分页。 |
| D167 | 首版只做恢复性重置 | 支持旧 checkpoint 回滚后继续，或明确清空协作状态；均新建 lineage。独立 `project fork` 延后，数据模型保留来源表达能力，不提供首版命令。 |
| D168 | 未知副作用按范围自治处置 | current main 可在可委派 scope 内提交 succeeded/failed 的证据结论或提出新 Operation；user-only、高敏、越过 ceiling 的处置仍 user。结论记录为追加 Resolution，不改写原未知历史，不把接受风险算作成功。 |
| D169 | 重大性由主 Agent 判断，固定 user-only 保留 | 设计/方向/重大验收变化的语义由 main 判断并创建 UserDecision，内核不作关键词/代码 diff 风险分类。项目整体完成、appoint/revoke、ceiling/Full Access 扩张、协调根/信任边界变化、破坏性 Git/最后副本删除、用户保留事项继续由 user/control 最终提交。用户先选完全 main 判断，后确认该固定权限边界。 |
| D170 | REST 是受支持的本地公共契约 | CLI、四适配器、未来 Web、第三方本地集成都使用版本化 REST；实时协议 current/N-1。不是仅内部接口，也不只保证 SDK。 |
| D171 | 每项目共享 MCP，逐连接独立鉴权 | project 级 MCP endpoint/server 共享；每个客户端有独立 HostSession credential。actor 从请求鉴权与连接绑定派生，不允许模型输入 actor/project 覆盖。共享进程不等于共享 token。 |
| D172 | lineage 重置后运行身份全部失效 | 新 authority=unassigned，用户重新接入/任命；旧 Session/token/grant/Lease/Job claim 不复活。共享历史按目标 checkpoint 恢复，不自动继承旧主权。 |
| D173 | 项目内内容寻址附件 | 默认 `.tsunagou/local/artifacts` 存 SHA-256 blob；需随 checkpoint 恢复的证据显式提升到共享层，按内容去重。 |
| D174 | durability 管字节，领域管引用与权限 | tasks/agents/cognition 等拥有 ArtifactRef 与可见性；durability 负责写入/校验/物化，不成为统一业务 ACL 模块。 |
| D175 | 首版附件不自动 GC | 本机及共享 blob 均不自动删除；领域历史永久保存。运行遥测明细 30 天策略可继续，但不得连带删除附件。 |
| D176 | 黑板在单次读事务中组合 | 非写入 query composition 调用各模块 public query ports，返回有界且带 section revision 的一致快照；不建独立黑板真相表。 |
| D177 | 最小上下文注入与按需工具 | attach/resume/task 边界注入身份、当前责任、blocker、水位；详细黑板、契约、证据按需工具读取，不每轮广播全量。 |
| D178 | 核心版本化提示片段 | core 维护宿主无关原则、字段、digest；adapter 做渲染和有界裁剪。Attach 记录实际模板版本，关键身份/授权信息不可裁掉。 |
| D179 | 对话呈现，CMD/HTTP Control 提交 | 用户希望保留三种接触面，经澄清最终：主 Agent 对话展示选项/记录偏好，user-only 状态转换由 CMD/CLI 或独立 control HTTP 提交，绑定相同 decision revision/digest。Agent 不能代持 control token 或代签。 |
| D180 | 首版不接受宿主 user-role 授权证据 | 宿主可证明用户来源的专用确认通道也延后；对话中的“是”本身不会使 API 权限升级。 |
| D181 | 决策提醒通过主 Agent与查询接口 | UserDecision 路由给 current main 在会话呈现，CLI list/show 与 HTTP query 可查；首版无系统通知。 |
| D182 | ZCode 首发验收后置 | 首发发布门禁只要求 Codex、OpenCode、DeepSeek Harness 三宿主完成 11 项共同基线。ZCode 适配器、探针和研究证据保留，但正式基线、宿主演示和发布验收延后，不计入 `release_check.py` 首发失败条件。 |

## 不再向用户逐项询问的工程细节

字段、索引、接口命名、错误码、Job 步骤、端口签名和测试组织按上述边界由实现规范确定。它们在 [工程消歧记录](engineering-resolutions.md) 标记为工程推导，不能伪装为用户原话。外部宿主能力和库版本必须实际探测，不因边界已确认就宣称已经通过集成验收。

## 仍生效的基础决策

D01–D160 保存在 [原始第一轮](../history/2026-09-18-source/implementation_decisions.md) 和 [原始第二轮](../history/2026-09-18-source/implementation_decisions_round2.md)。历史文档含候选与旧表述，不作为新 Agent 的首要实施入口；当前入口为 [实施指南](../implementation/README.md)。
