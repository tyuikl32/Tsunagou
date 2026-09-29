# FX5 实施顺序与验证

1. 对齐 shared_kernel/time.py、query_models.py 与现有 diagnostics 格式，补发生/记录时间、触发来源及关联。
2. 修 hostwake/dispatcher.py 全部终态路径、异常与重启 unknown。同步 API/CLI diagnostics filters，不重写 history。
3. 接入 FX4 安装/接入计时与 FX2 begin/submit 事实；减少无变化 reconnect 由 FX4 实现，FX5 验证只读无噪声。
4. 在可选 telemetry 依赖组和 platform/telemetry.py 完成五个边界埋点，携带 outbox 因果；本机 exporter 可关闭。
5. 新增 tests/unit/test_telemetry.py 与 tests/integration/test_failure_timeline.py；复用 test_hostwake、test_history_cli 和协议审计测试。覆盖 failed 无 evidence、异常、响应丢失、人工恢复仍保留失败、跨时区过滤及秘密 sentinel。
6. 新增 tools/dev/collect_acceptance_trace.py 作为验收用本机 OTLP 接收器，输出脱敏 spans 到指定 acceptance 目录；它不作为运行产品依赖。
7. 更新用户查询示例、字段解释和计时口径。CLI help 中不存在的参数不得写成当前已可运行。

~~~powershell
uv sync --locked --extra dev --extra telemetry
.\.venv\Scripts\python.exe -m pytest tests/unit/test_telemetry.py tests/unit/test_hostwake.py tests/unit/test_history_cli.py tests/integration/test_failure_timeline.py tests/protocol/test_audit_contract.py -q
.\.venv\Scripts\python.exe tools/codegen/validate_protocol.py
.\.venv\Scripts\python.exe tools/docs/validate_docs.py
~~~

代码实现后，实际从项目 CLI 查询一条失败到恢复链和两名 Worker 的时长；trace 要由真进程产生。不能只写带 trace_id 的 JSON 冒充 SDK spans，也不能为了补诊断再写领域成功事件。
