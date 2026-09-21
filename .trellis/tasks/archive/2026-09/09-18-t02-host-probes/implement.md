# T02 执行步骤与交接

## 开始前

- [x] 检查依赖 无，可作为起点 的完成证据，读取本任务 PRD/design/上下文与对应 Trellis spec。
- [x] 检查工作区现有改动，确认Schema/端口已有产物和版本；不得覆盖用户改动。
- [x] 使用 task.py start 显式开始；现在任务保持planning，不自动运行产品实施。

## 实施步骤

- [x] 核对四宿主官方资料、已安装或可获取版本，确认目标Harness而非模型API
- [x] 逐宿主验证同目录双session、resume、compact、new、clear、fork和安装profile标识
- [x] 验证typed tools、共享项目MCP鉴权、stdio转发、token私有交付；锁定Python/TS官方SDK兼容API
- [x] 记录wake/gate/presented/launch/stop增强实测值，给出正式支持版本窗或明确阻断原因

## 检查

- [x] 11项共同基线逐项有证据状态，未知不填supported
- [x] 身份连续性无法证明则不ready，不用cwd/PID/LLM自报替代
- [x] 两个宿主连接共享服务但不能共享principal
- [x] 所有probe日志无token/raw conversation ID/私有transcript；失败不被隐藏
- [x] 执行相关模块检查及协议/架构公共门槛，记录确切命令、退出状态与证据文件。
- [x] 执行 python tools/docs/validate_docs.py 和本任务 task.py validate，更新规范与上下文。

## 结束与交接

- [x] PRD逐项标记并附证据；没有产品实现前不得填写已通过。
- [x] 在Trellis journal记录结果、限制、依赖影响与下一任务。
- [x] 检查通过后完成/归档，更新任务依赖引用；发布、push、用户重大决定按已有授权处理。
