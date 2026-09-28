# 本轮交付与实测结果

记录时间：2026-09-28 05:58 UTC。测试起点为用户报告的 10:50（Asia/Shanghai，即 02:50 UTC，分钟精度）。业务代码位于 `D:\ALL.NET\SegaImageManageTool`，Tsunagou 源码保持在 `D:\Tsunagou`。

**业务交付已可运行；Tsunagou 平台验收部分通过。** 按用户要求，先完成业务任务，过度设计、效率及平台缺口留到事后复盘。没有自动提交 Git，也没有代用户确认项目完成。

06:17 UTC 补测修正：初始原生 wake 实际未配置；启用 provider、绑定现有会话后，真正的 `thread/resume` 被 Codex 的 active writer 保护拒绝。diagnostics 现在可查到请求和 fallback presentation，仍缺终态失败记录。详见 [原生唤醒补测](native-wake-followup.md)。当前 daemon PID 70156，listener PID 87044；下表保留初次验收时点，最新运行状态以后续证据为准。

## 立即使用

当前页面为 [Sega Image Workbench](http://127.0.0.1:5137/)。后端同时提供静态 UI 和 HTTP API，当前运行进程无需再次启动。如以后关闭了服务，在 PowerShell 执行：

```powershell
Set-Location 'D:\ALL.NET\SegaImageManageTool'
dotnet run --project .\SegaImageManageTool.csproj -- serve --port 5137
```

打开页面，选文件，再点 **Inspect image**。可用本轮的合成样本：

```text
D:\Tsunagou\docs\acceptance\evidence\sega-image-manage-tool-2026-09-28\synthetic-valid.PACK
```

此样本是 32 KiB 的合成加密头和零数据扇区，包含正确 CRC/HMAC，不含游戏内容。生成器 [make-synthetic-btid.ps1](make-synthetic-btid.ps1) 从既有解析器读取格式常量；后端实际执行原有解析代码，没有 mock 响应。页面应显示 **Inspection complete**、Game ID `TEST`、版本 `1.2.3`；原始响应含 `headerCrcValid: true`。[HTTP 结果](btid-success-record.json) 与 [截图](btid-success.png) 已保存。

## 谁完成了工作

| 角色 | 独立会话 | 结果 |
|---|---|---|
| main | SegaImageManageTool Main | 拆分、权限/工作空间决定和结果审查；事件 374/375 接受两项结果 |
| WebUI | SegaImageManageTool Web UI Worker | 静态页面、HTTP 客户端、5 个 Node 测试和 UI 验收说明 |
| HTTP | SegaImageManageTool HTTP Worker | ASP.NET Core 后端、请求关联、API contract 和 HTTP 验收脚本 |
| 当前 root 会话 | 本报告所在会话 | 部署调试、协调、独立验收和证据整理；此次合成样本和协议 harness 属于验收材料 |

业务实现由两个 Worker 完成。各自 Agent、session、task、attempt、result ID 和摘要见 [coordination-record.json](coordination-record.json)。两项 Worker task 已 completed，父总任务仍保留待用户确认；这两个状态不能相互替代。

## 实测结论

| 项目 | 结论与证据 |
|---|---|
| 代码与基本测试 | `dotnet build` exit 0；Node 5/5；HTTP acceptance exit 0。NuGet 漏洞源不可达警告已记录 |
| 真实 UI/HTTP | 在线状态、multipart 小文件错误、合成有效 BTID 成功均经过真实服务；并非只测 mock |
| 三 Agent 身份 | main/WebUI/HTTP 的身份与会话各自独立 |
| A2A HTTP | 两个接收者各发送三次（同 request ID 重试及同 messageId 新 request ID），共新增两条消息；tasks/get 返回 completed；异 Worker cancel/fail/retry 被拒绝。见 [请求响应](a2a-http-record.json) |
| 实际收件闭环 | 两个 Worker 自己 pull/present/ACK 后回复，main 自己接收并 ACK；四条 delivery 最终均 acked。见 [回执与事件](a2a-receipt-record.json) |
| 原生宿主唤醒 | **未通过**。前期失败和此次 `host_wake=disabled/not_configured` 均如实保留；本次继续对话由 Codex follow-up 触发 |
| 持久化与时间戳 | 公开项目 history 两页共 306 条可见记录，全部含时间和 actor；任务 history、单条 audit、checkpoint verify 成功；私信不出现在该公共历史中 |
| 查询不写业务事件 | 首次七项查询前后均为 seq 375；重启后的七项查询前后均为 seq 386。查询过滤意味着可见条数不等于事件序号 |
| 重启 | PID 76936 → 87492，同端口 56876；保留历史、任务结果、私信和可验证 genesis checkpoint。业务后端未停止。见 [重启记录](restart-record.json) |
| OTel / 完整 blame | **未实现** Tsunagou instrumentation、exporter 与 event↔trace/span 关联；actor/command 审计和 ASP.NET Activity 不等于 OTel 验收通过 |
| 失败留痕 | diagnostics 仍为空，拒绝型操作的原因目前主要保存在脱敏 HTTP 响应及本轮异常文档，公共查询链仍不完整 |

BTID 成功路径只证明已知有效样本的解析。原库 `Btid.Create` 丢弃 sector CRC/HMAC 的布尔校验结果，且读取截断扇区的循环存在风险；本轮未改动该既有库。不能将“成功解析元数据”扩大解释为“所有损坏文件均可正确拒绝”。

## 耗时：分别看部署、交付等待和宿主回合

| 阶段 | WebUI | HTTP |
|---|---:|---:|
| 首次 start → 最终 submit（含恢复与等待） | 71 分 12.197 秒 | 40 分 10.918 秒 |
| 所有有持久记录的 running 窗口之和 | 4 分 20.901 秒 | 11 分 22.825 秒 |
| 最终 submit → main review.accept | 2 分 34.430 秒 | 16 分 40.338 秒 |
| 已完成宿主回合累计（含接入、推理、工具、协调及 06:17 收件补测） | 17 回合，68 分 9.535 秒 | 21 回合，55 分 2.530 秒 |

部署命令当时没有精确起止计时，无法补造 installer 时长。可验证的是：从用户报告的测试起点到 project genesis 为 **8 分 34.450 秒**，到稳定 daemon 为 **9 分 35 秒**；这两个数是观察到的上界，包含其他操作。

running 窗口不是实际写代码时间：Agent 曾在 Lease 到期后继续通过宿主写文件，因此这个数字会严重低估宿主实际工作。宿主回合累计也不是纯编码耗时，它包括协议操作与工具等待，且各 Worker 并行时不能相加当作总墙上时间。未记录可靠的逐任务 token 费用，不能从回合数量反推 token 消耗。原始分段见 [timing-record.json](timing-record.json) 和 [host-turn-timing.json](host-turn-timing.json)。

## 复制即可查询记录

在任意 PowerShell 目录先设置本次项目：

```powershell
$env:TSUNAGOU_PROJECT_ROOT = 'D:\ALL.NET\SegaImageManageTool'
$env:TSUNAGOU_STATE_DIR = 'D:\ALL.NET\SegaImageManageTool\.tsunagou\local'
$projectId = '839bdb05-c7db-474c-9517-f0e837eb5096'

uv run --project D:\Tsunagou python -m tsunagou daemon status --coordination-root $env:TSUNAGOU_PROJECT_ROOT
uv run --project D:\Tsunagou python -m tsunagou project history $projectId --limit 200 --json
uv run --project D:\Tsunagou python -m tsunagou task history 0a28f9e6-52c8-4d80-b805-64807da75931 --project-id $projectId --limit 200 --json
uv run --project D:\Tsunagou python -m tsunagou task history ab418fd1-b3a8-48a9-9ac2-f595cd833f14 --project-id $projectId --limit 200 --json
uv run --project D:\Tsunagou python -m tsunagou audit event ac915295-7b96-4054-97f1-b4565a02d327 --project-id $projectId --include-evidence --json
uv run --project D:\Tsunagou python -m tsunagou project diagnostics $projectId --json
uv run --project D:\Tsunagou python -m tsunagou checkpoint list $projectId --verify
```

项目 history 是分页结果；用返回的 `next_cursor` 作为下一次 `--cursor` 参数。daemon 命令目前必须显式传 `--coordination-root`，不能假定它与 history 一样使用环境变量默认值。凭据由本地文件私下读取，无需复制 token。完整本轮查询快照见 [首次查询](public-query-record.json) 与 [重启后查询](public-query-after-restart.json)。

`live-protocol-check.py --queries-only` 可重复只读检查；不带该参数会创建新的测试消息。最终项目完成 checkpoint 等待用户确认；当前 checkpoint verify 验证的是 genesis，不能声称包含这次全部代码结果。

## 待复盘，当前不扩张实现

06:26 UTC 收尾：主 Agent 已对两项重复的早期任务发出取消请求，阻止再次领取；当前无非终态 Attempt、有效执行 Lease 或 attempt Grant。无 owner 的任务仍卡在 cancel_requested，和文档约定不符，已留档。逐项通过/缺失判定见 [交付收尾审计](completion-audit.md)；父总任务仍 open，等待用户确认。

用户指出的“初始阶段过度设计削弱效率”已记录为 `overdesigned_initial_execution_chain`，保留原始观察，不把本轮的 workaround 写成正式设计改变。后续优先讨论：准备链如何合并、Lease 从何时起计与自动续租、恢复是否需要重复 main 决策、契约 slot/proxy 状态、原生唤醒和最小必要诊断。全部异常见 [unexpected-deviations.md](unexpected-deviations.md) / [JSON](unexpected-deviations.json)。
