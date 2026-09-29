# 实施调度和最终检查

用户已授权完成全部任务，当前正在实施。开发者 tyuikl32，平台 Codex；不自动提交 Git。

## 开始前

1. 读取当前 Git 状态和 HEAD，保留所有已有改动。本次设计核对基线为 1fb86e0；若代码前进，先重核变更点，不把旧行号当永久定位。
2. 阅读总 PRD/design、本轮决策以及目标子任务三份文档和 JSONL；按 .trellis/workflow.md 进入对应阶段。
3. 使用全新项目/协调状态，不迁移旧身份和运行记录。源码安装、Python CLI、TS bridge 和 Skill 同一版本。
4. 按 [任务索引](../../../docs/implementation/live-test-repair-tasks.json) 检查前置；task.py start 只在真正开始该任务时运行。实际进度、接口就绪和最终验收分别记录，不用规划或实验替代完成。

## 推荐顺序

FX3 → FX1 → FX2 → FX4 → FX5 → FX7 → FX6。

FX3 先以最小真实后台调用验证最有风险的宿主路径，再完成 provider 和恢复。若发现真实技术失败，可继续独立的 FX1/2/7；不得把总任务关闭或把 Desktop 验收改为可选。

每项修改与检查命令见其 implement.md；不在本总任务重复维护另一套命令清单。执行后记录实际命令、退出码、UTC 起止和对应验收项；新增测试文件明确由该任务创建，不能把不存在的测试当作已运行。依赖任务通过后再推进需要它的任务。

FX7 在 SegaImageManageTool 的隔离 checkout 实施，先读取目标 AGENTS；源码不搬入 Tsunagou。当前版本前端为 wwwroot 静态文件，无 pnpm build script，按 FX7 已核实的 dotnet/Node/HTTP 步骤执行。

## 全量收口

- 跑各任务必要测试，跨层改动完成后跑协议生成校验、架构检查、TypeScript 检查、完整后端/bridge 回归和文档校验；具体完整测试命令以仓库现有脚本为准。
- 搜索旧 renew、expires_at、worker.ready 和分步准备示例；确认仅后台 Job 或明确历史文档保留相关语义。
- 更新 docs/implementation 的任务/资源/工作区/认知/适配/协议文档和 overview/Skill/安装产物，区分新语义与旧验收。
- 逐项核对 research/issue-disposition.json；已修与正确边界只回归，不复制旧缺陷为新需求。
- FX6 用独立安装产物、两名真实手动 Desktop Worker、真实 A2A HTTP 和业务页面验收；不以开发会话工具补发消息冒充 daemon 唤醒。
- 留档部署、接入、工作、提交、审查及用户等待；失败来源保留，未知时间和 token 用量不猜测。
- 最终向用户报告实际成果和验收结果，用户重大交付确认后才关闭总任务。

## 本规划阶段的校验

完成文档后运行 python tools/docs/validate_docs.py，并对总任务及七个子任务运行 .trellis/scripts/task.py validate。额外核对新机器索引依赖无环、meta.depends_on 对齐、42 条异常恰好覆盖一次、所有必需文件和上下文存在。

规划校验不表示产品测试通过，也不启动 daemon、安装修改或业务代码测试。
