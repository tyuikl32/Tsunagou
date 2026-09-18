# T01 执行步骤与交接

## 开始前

- [ ] 检查依赖 无，可作为起点 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [ ] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [ ] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [ ] 核验Python/Node/pnpm/TS版本窗口和注册表可用性，保存实际输出；冲突记录兼容矩阵
- [ ] 建立单Python distribution和六TS工作区包，生成目录标只读
- [ ] 安装并锁定FastAPI/数据库/CLI/Schema/测试依赖，MCP SDK精确版本接T02结论
- [ ] 加入Ruff/mypy/pytest/Vitest和import边界检查入口，制定源码运行命令

## 检查

- [ ] Windows干净环境可按锁文件安装和导入空应用
- [ ] Python域层不依赖框架，TS内部包使用workspace:*和strict/NodeNext
- [ ] 重装不改变锁文件；不把未实现产品演示写成已可运行
- [ ] 版本冲突有证据，无静默扩大已定窗口
- [ ] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [ ] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [ ] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [ ] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [ ] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
