# FX6 场景及完成判定

## 环境

使用全新测试目录与 .tsunagou 状态，记录安装源码 commit、包版本、Codex app/CLI/plugin 版本。普通依赖服务在启动前实际 health 检查，测试端口从服务返回读取，不硬编码 5080 等旧值。

业务回归采用 SegaImageManageTool 的隔离 checkout，main 负责 Git/工作区准备，不清空旧验收目录或修改原业务数据库。先读取目标 AGENTS 和基线；已有 unrelated 改动保留。最小两 Worker 场景可先验证简单真实 HTTP 路由与页面联调，随后跑 FX7 完整性回归；不能用两个 mock Worker 当成功。

## 核心场景

1. 用户手动创建 main 与两名 Worker 会话；各自走新版接入。记录同 IDE 不同 conversation 对应不同 agent_id，主权限只有用户任命的一名。
2. 两名 Worker 完成当前轮并 idle。main 在已有用户项目授权内发布两项明确范围任务，发送 message/send；daemon 触发原会话。测试组织者不发额外“继续”。
3. 一个 Worker 做业务功能或后端修复，另一个做边界不同的真实 HTTP/UI验证，必要时经 main 修改计划划分重叠测试范围；不以超大 tests scope 抢占掩盖真实冲突。
4. 注入一项与真实需求相关的接口理解分歧，通过认知报告、主 Agent 协调与契约解决；不为证明模块存在强制每个任务经历协商。
5. 工作中 daemon 正常重启，再由原 owner 恢复；另测显式回收。在全新测试任务上验证，避免破坏正执行的真实业务修改。
6. user decision 保持未答一段操作时间。相关任务挂起，无关任务完成；计时不触发自动同意/取消。随后用户答复，经消息原会话继续。
7. main 审查两项结果；运行真实 HTTP、浏览器与损坏样本验证，提交用户可演示成果。用户完成确认单独记录。

## 留档

每次运行在 docs/acceptance/evidence/live-repair-<UTC-run-id>/ 保存 manifest.json、timeline.json、deviations.md、summary.md 和脱敏 trace。原始私有 socket、令牌、thread/session 标识与消息正文留在本机 .tsunagou/local，不复制入项目证据。

manifest 固定 source/runtime 版本、机器时区、开始/结束时间、任务/Attempt/Agent 引用、每项 A1–A8 pass/fail/未执行及文件引用。timeline 记录发生和观测时间，deviations 按触发→现象→实际原因→处理→复测结果记录，不覆盖失败。

正常路径每个无返工任务只有一组 begin/submit；重复网络请求必须幂等。记录模型工具调用次数和协调恢复次数，不虚构 token 节省百分比。耗时拆部署、接入、工作经过、审查等待和用户等待。

## 门槛

FX3 原 Desktop 自动唤醒必须真实通过；仅 managed 成功、开发者跟进、另建 thread、只查消息 accepted 都不合格。未满足的条目保留未完成，总任务不得归档完成。验证失败应回到所属 FX 任务修复，避免让用户手动修状态来跑完。

## A6 实施前发现的断点

2026-09-28 现场准备时核对源码发现：`bootstrap/container.py` 已有真实 decisions 查询，但字段为 expected_revision/input_digest，与操作单所需 revision/proposal_digest 不一致；`user_decision.resolve` 改完状态未给 main 发送持久通知。UserDecision 虽已持久化 ID/digest/status，却未保留用户实际需审阅的 choices/summary。这使现有 CLI 操作单无法完整完成“列出当前提案→用户回答→主 Agent 收到答复”的路径。最初将后面的空列表 fallback 误认为全部查询实现，已在 16:31Z 复核后更正；不为已经存在的查询重复开发。

本批只补三项：持久保留已提出的 choices/summary；已有 decision list 查询投影真实决定和一致的 revision/proposal_digest/UTC 时间；U 解决决定成功时同事务向当前 main 写一条结果消息，复用已有 outbox/原会话唤醒。main 再按实际任务判断是否继续，不让机械代码直接恢复执行或猜测业务结论。

边界与文件：application/workflows/lifecycle.py 的决定数据，application/handlers.py 的 resolved 通知，bootstrap/container.py 的现有查询分支，所需 schema/fixture、实际 SQLite/API/CLI 回归及用户说明。不得改变已授予的 U-only 权限、私信审计可见性、Task owner/scope 或引入决策引擎。重复 U 命令幂等只产生一次通知；用户未答/时间经过不改变 pending；重启保留待答内容。旧的“未执行 A6”结论仍保留，代码回归不能取代之后用户实际作答及原 Worker 恢复。
