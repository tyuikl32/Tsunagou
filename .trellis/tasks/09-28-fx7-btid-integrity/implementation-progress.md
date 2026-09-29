# FX7 实施与验收记录

状态：completed。目标副本：`D:\ALL.NET\SegaImageManageTool-fx20260928`，原业务目录未修改。BTID 解析修复由 parser Worker 提交并经 main 审查；HTTP/fixture 和同源 API 地址修复由 verification/UI Worker 提交并经 main 审查。各任务提交未产生 Git commit。

## 行为结果

- 合法文件完整读取后报告 BTID 元数据，CRC 检查必须为真；CRC 或 HMAC 不匹配拒绝为 `invalid_image`。
- 头文件不足沿用 handler 的 `400/file_too_small`；签名、CRC 表、扇区截断、非法 offset 和 size overflow 返回 `422/invalid_image`，不挂起。
- 前端保留有效的用户 loopback origin；没有保存值时，同源本机页面自动使用当前页面 origin；无效/非本机来源不会被接纳，也不会扫描端口。
- 业务无效与 API 不可达使用不同 UI 错误状态。页面曾实际展示 `valid.app` 成功元数据和 `crc-corrupt.app` 的 `invalid_image`。在新端口 fresh browser origin 中，设置自动选为当前地址且 health 实际在线。

## 工作与审查时间

所有时间为 UTC。任务区间包含 LLM 推理、工具和等待，不是纯编码时间；review 间隔单独报告，不与并行 Worker 时间相加。

| Worker 工作 | begin | submit | main review | 可见工作/审查区间 |
| --- | --- | --- | --- | --- |
| Parser：`Modules/Btid.cs` | 13:58:12.337 | 14:10:33.066（result_created_at） | 14:21:50.715 | begin→submit 12m20.729s；submit→review 11m17.649s |
| HTTP fixtures / API tests | 14:12:04.906 | 14:20:28.836 | 14:28:48.175 | begin→submit 8m23.930s；submit→review 8m19.339s |
| WebUI 当前 origin | 14:34:05.506 | 14:40:53.477 | 14:44:00.135 | begin→submit 6m47.971s；submit→review 3m06.658s |

Parser 的任务 history 仍对用户 CLI 隐藏 submit 事件，因为显式 evidence refs 包含 recipient-only 消息引用。早期 FX6 快照的 `submitted_at` 和工作时长因此为 `null/unknown`。16:47Z 新 `project timings` 实测从独立公开 Result.created_at 取得提交记录时间，可见 submit_events 仍为 0，没有读私信或从 review 反推。本表更新依据为 [新查询快照](../../../docs/acceptance/evidence/live-repair-20260928T150917Z/snapshots/20260928T164747-c06e35eb/timeline.json)。

## 验收记录

- [隔离业务基线](research/baseline-copy.json) 固定原仓库来源与复制范围；[运行时任务清单](research/runtime-tasks.json)记录各 Worker 任务与文件边界。
- Parser 连续读取、校验和失败边界通过；`dotnet build` 与后续 `dotnet build --no-restore` 均成功。最终构建 exit 0，0 warnings，0 errors，1.28 秒。
- [最终真实 BTID HTTP 回归](../../../docs/acceptance/evidence/live-repair-20260928T125752Z/btid-http-final.json)：9/9 通过；样例覆盖合法、CRC 错、HMAC 错、头/签名/CRC 表/扇区截断、非法 offset、size overflow。requestId 与响应头一致；请求 6.31–67.26ms。
- `tests/Http/run.ps1 -Port 57067` 通过；`node --test tests/WebUI/api.test.mjs` 8/8 通过；`node --check wwwroot/app.js` 与 `node --check wwwroot/api.js` 通过；业务 checkout `git diff --check` 通过。
- 14:34Z 的真实页面正反样本在显式设置 56416 后实际成功/失败显示；14:51:17Z 在新的 `http://127.0.0.1:57065/` browser origin 中实证自动选择当前 origin 与 health 在线。后续已在该新 origin 实际上传正常、CRC 损坏、截断扇区样本，分别得到成功、invalid_image、invalid_image；未手工 Apply API 设置。三个 request ID 与截图见 [页面检查](../../../docs/acceptance/evidence/live-repair-20260928T125752Z/browser-check.json)。
- 启动隔离服务、端口、PID 与健康证据见 `docs/acceptance/evidence/live-repair-20260928T125752Z/business-origin-test.json`。FX6 按各自场景复核，本任务完成不表示用户已确认整体项目交付。
