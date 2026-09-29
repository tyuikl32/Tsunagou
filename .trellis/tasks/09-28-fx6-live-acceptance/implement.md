# FX6 可执行验收准备与调试

前置 FX1–FX5；最终业务回归前 FX7 通过。使用 PowerShell 与安装产物，测试工作区路径从本轮记录取得。

1. 新增 tools/dev/live_repair_acceptance.py，子命令 prepare/check/export；prepare 只生成新验收目录、版本与起始时钟，不替用户创建 Desktop 对话；check 调用实际查询断言记录，export 过滤秘密。不让该脚本伪造模型执行。
2. 将 docs/acceptance/live-repair-first-run.md 写为逐条可复制操作单：确认安装位置→启动 daemon→bootstrap→接入 main/Worker→实际消息→执行→重启恢复→查询→业务检查→结束标准。每条列出预期返回及失败时查哪个日志，不泛泛要求“刷新 MCP”。
3. 安装与接入命令使用 FX4 实现后的 help 验证，至少在一个非源码项目目录直接执行。记录安装与 connect 真起止。
4. 用户需手动创建对话时提供一段接入提示和精确项目目录；每个会话由自己的 Agent 生成接入请求。主 Agent 不代替 Worker 读取其 session 文件宣布成功。
5. 先做空闲原会话的消息唤醒，再开始有代码修改的任务。运行中不以本开发会话的应用工具补发消息；需要补发则记录本场景失败。
6. 执行 design 的场景，逐项保存事实并用真实 CLI核对。全程不删除旧身份数据或历史证据。
7. 业务服务部署后，通过返回端口访问 /health 与实际页面，上传正常、损坏和截断样本；记录 HTTP 状态、requestId、页面结果。
8. 复核输出文件可读和索引链接，完成 A1–A8 表，再交用户做重大交付确认。

以下现有 CLI 语法已通过 --help 核实；变量来自新版接入和任务创建结果，不要求用户寻找 ID：

~~~powershell
tsunagou project history $projectId --json --export
tsunagou project diagnostics $projectId --json
tsunagou task history $taskId --project-id $projectId --json
tsunagou checkpoint list
~~~

源码检查仍需 python tools/docs/validate_docs.py。prepare/check/export、agent prepare、task begin 等新入口由所属任务实现并通过实际命令验证后写入操作单。不能先发布一份依赖不存在命令的“已可操作”手册。

完成时报告真实部署和工作时长、未通过项（应为空）和用户确认状态；不把用户尚未确认写成项目 completed。
