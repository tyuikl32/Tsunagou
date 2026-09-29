# FX6 双 Worker 首次实测操作单

本文服务于 FX6 的实际双 Worker 实测。所有步骤都以本地安装的 `tsunagou`、各 Agent 自己当前的 Codex Desktop 会话和真实 BTID HTTP 服务为准；安装成功、ticket 已签发、消息已 ACK、构建通过或同项目存在多名 Agent 都不会自动令 A1–A8 通过。

本机固定环境为 Tsunagou 源码 `D:\Tsunagou`、隔离业务 checkout `D:\ALL.NET\SegaImageManageTool-fx20260928`、协调项目 `D:\Tsunagou-fx-live-20260928`。本轮独立 launcher 是 `C:\Users\Tyuikl\.local\bin\tsunagou.cmd`。在另一台机器上，只替换这四个文件系统路径；project_id、Agent、Attempt、宿主会话或 pipe 都从命令结果/CLI 查询取得，不让用户抄写或伪造这些身份。

## 1. 核对安装和项目

在 PowerShell 中设置目录并查看安装来源。`installation-info` 不需要 daemon 或项目凭据：

```powershell
$cli = 'C:\Users\Tyuikl\.local\bin\tsunagou.cmd'
$sourceRoot = 'D:\Tsunagou'
$projectRoot = 'D:\Tsunagou-fx-live-20260928'
$businessRoot = 'D:\ALL.NET\SegaImageManageTool-fx20260928'
$install = & $cli installation-info --json | ConvertFrom-Json
$install | Select-Object status, source_root, commit, python_version, bridge_version, install_started_at, install_finished_at, duration_ms
```

期望 `status` 为 `installed`、`source_root` 为选定的 Tsunagou checkout，并有安装 commit、Python/bridge 版本和安装起止 UTC 时间。路径或来源不符时先停止实测，修正安装来源后重新核对；不要从源码工作目录调用开发版来掩盖安装问题。

检查协调项目登记和 daemon 健康：

```powershell
$project = Get-Content -LiteralPath (Join-Path $projectRoot '.tsunagou/project.json') -Raw | ConvertFrom-Json
$doctor = & $cli --project-root $projectRoot --json doctor | ConvertFrom-Json
$doctor | Select-Object status, daemon, version, runtime
```

期望 `status=ok`、`daemon=reachable`，并且 `runtime.project_ids` 包含该项目的 `project_id`。若是一个明确的新项目，先用安装产物执行 `project init --coordination-root <项目目录> --name <项目名> --objective <项目目标>`，再执行 `project bootstrap --coordination-root <同一目录> --source-root <Tsunagou 源码目录> --host codex`。已存在的协调项目不要重复初始化。daemon 未运行时只在这个明确项目上运行一次 `daemon start`，确认该次启动的 health；不能仅凭端口响应认定 daemon 属于此项目。多个项目可登记在同一个 daemon，无需强制各开一个进程。

安装器参数已以本地 `install.py --help` 核实。需要在全新环境安装时，从确定的源码目录运行 `& $install.python 'D:\Tsunagou\tools\install\install.py' --source-root 'D:\Tsunagou' --project-root '<选定的协调项目目录>' --host codex --json`，成功结果应有 `status=installed`、实际 launcher、project root 和 installation timing；随后重读 `installation-info` 并检查 `doctor`。该操作会写用户级 launcher、宿主配置及项目集成；不要为已经可用的实测环境重复运行，也不要先卸载旧版。

## 2. 生成验收快照目录

每次实测都用一个新的 UTC 目录。准备操作只创建验收资料，不创建 Desktop 对话、不加入 Agent、不发送唤醒，也不改运行中的 daemon：

```powershell
$runId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$evidenceRoot = Join-Path $sourceRoot "docs\acceptance\evidence\live-repair-$runId"
$python = $install.python
& $python (Join-Path $sourceRoot 'tools\dev\live_repair_acceptance.py') prepare `
  --output $evidenceRoot --project-root $projectRoot --source-root $sourceRoot --cli $cli
```

期望返回 `status=prepared`，A1–A8 全为 `not_run`。此目录应包含 `manifest.json`、`review.json`、`timeline.json`、`deviations.md` 和 `summary.md`。不指定已存在的验收目录；当前原始 `spans.ndjson` 持续采集文件保持只读。

## 3. 检查 bootstrap 与独立会话身份

用户选定 main 和两名手动创建的 Worker Desktop 对话。先在每个原对话中实际调用 `context__project_read`，确认 project root 正确且 MCP 工具能工作。本机 Codex 设置没有刷新按钮；已经加载的共享 bridge 会根据每次调用的 thread metadata 读取新绑定路线，不因加入一个 worker 而重复重启其他 bridge。每次 connect 会清理同项目、同一 bridge 的旧固定-session MCP 注册，保留其他项目和仍运行的 bridge。

若 connect 后原对话第一次实际检查仍返回 `not_enrolled:no_ticket_or_session_file`，它可能仍持有已启动的早期固定-session bridge；先新开一个 Codex 对话并调用 `context__project_read`。只有新对话也没有加载共享 MCP 时才完全退出并重新打开 Codex 一次，然后复查。不要重新 connect、重新 enrollment 或填写任何 ID。若工具已存在但查询失败且错误不同，保存具体错误并检查 daemon/bridge 日志，不循环刷新或重启。当前原 main 与 Worker 会话已 MCP ready，应从 `context__project_read` 和 `agent list` 核实，不执行上述重载。

在 main 及每一个 Worker 自己的会话中运行：

```powershell
& 'C:\Users\Tyuikl\.local\bin\tsunagou.cmd' --project-root 'D:\Tsunagou-fx-live-20260928' agent prepare --adapter codex --role main
```

Worker 将 `--role main` 换成 `--role worker`。Agent 自己运行该命令可私下观察当前宿主会话，并返回一条实际填好的 `agent connect` 命令。获准的 Agent 应在自己的会话里直接执行；需要用户执行时，把工具返回的完整命令原样交给用户。不要填 ID，不要把 request-file 路径里的宿主信息粘贴到共享任务或提示中，也不要由 main 读取 Worker 的 session 文件替它证明 ready。

预期 connect 返回 `status=enrolled` 及本项目 `project_id`、本会话 `agent_id`、选定 `role` 和 session 状态。随后由这个原对话调用 `context__project_read` 确认其为 `ready` 且项目正确，再查看：

```powershell
tsunagou --project-root 'D:\Tsunagou-fx-live-20260928' agent list --json
```

预期是一名用户选定的 main 和两名不同 `agent_id` 的 worker，三者 session 均为 ready。`agent list` 只给已授权视图中的脱敏会话摘要；“三名成员存在”不能证明两个 Worker 是不同的真实 Desktop 原会话，A1/A2 仍须依据各原会话实际观测记录。

## 4. 做原会话空闲唤醒和真实任务

让两位 Worker 完成当前回合并空闲。main 使用自己的原会话和 MCP `context__project_read`、收件箱、`coordination__plan` 和 `message__send` 工具，发布两个 scope 不重叠的实际业务任务，随后向各 Worker 发出与任务关联的消息。不要由测试组织者或 main 在 Codex 对话之外补发“继续”。

预期是各自原 Worker 会话收到 daemon 自动触发的新回合，并处理原消息。记录发生时间、观察时间、触发来源和结果；分别保留 daemon 自动唤醒的失败与之后的人工恢复。`message/send` 已接受、inbox fetch/ACK、presented 或新的宿主回合中的任一单项都不独自等于“原回合已自动开始”。失败诊断查 `project diagnostics`； daemon 日志位置以本次 `daemon status`/`doctor` 返回的 runtime 信息为准。

每个 Worker 对自己实际领取的范围调用一次 `task__begin`，在返回的 Attempt/scope 中完成真实修改或真实 HTTP/UI 验证，再调用一次 `task__submit`。有实际阻塞时保存进展并 `task__block`。main 复核交付、处理发现的真实分歧。daemon 重启和显式回收只在没有非本场景任务正由共用 daemon 执行时安排，并在隔离验收 run 中验证；重启会影响该进程登记的所有项目，不要在其他 Worker 正在写入时做。由拥有工作区的 Agent 检查正常、损坏和截断 BTID 样本。不要把测试范围扩大成共同写入，也不要将无法观察的提交/审查时间补估为精确数值。

FX7 的当前实测脚本在隔离业务目录执行，会实际启动该业务服务并发送 HTTP 文件上传：

```powershell
Set-Location 'D:\ALL.NET\SegaImageManageTool-fx20260928'
$resultPath = Join-Path $evidenceRoot 'btid-http.json'
pwsh -File tests/Http/btid-integrity.ps1 -ResultPath $resultPath
```

当前清单对合法样本期待 HTTP 200；CRC/HMAC 错误、截断签名/CRC 表/扇区及非法 offset/size 期待明确 4xx，并逐个核对 `requestId`、响应头和页面可观察结果。期望最后无失败项。结束后先向隔离服务的标准输出/错误日志和 `btid-http.json` 查异常，再归属到业务/FX7 修复；不把单元测试结果代替 HTTP 和页面证据。

## 5. 查询并导出脱敏证据

每个重要阶段结束后采集一次只读快照。命令只调用本地真实 CLI 的安装登记、doctor、agent list、项目 diagnostics、timings 和逐页 history：

```powershell
& $python (Join-Path $sourceRoot 'tools\dev\live_repair_acceptance.py') check --output $evidenceRoot
```

期望健康查询均成功时返回 `status=captured` 和 `criteria=requires_operator_review`；任一查询、分页、项目身份检查失败则返回 `incomplete`，退出码 2，并仅保留错误类别，不写入或显示 CLI 私密错误正文。确认 `snapshots/<编号>/facts.json`、`agents.json`、`timeline.json` 可读，检查每个 Attempt 的 begin/submit/review 时间及各自来源。提交事件因显式私信证据不可见时，timings 可以使用已有公开 Result.created_at，标注 `submitted_source=result_created_at` 且保留实际可见 `submit_events=0`；这没有公开隐藏事件。若两种来源都未提供可靠时间，仍保持 null。上次失败、被替代 Attempt 和唤醒失败不能被新成功覆盖。

直接查询本轮 parser 时间，无需打开数据库：

```powershell
& 'C:\Users\Tyuikl\.local\bin\tsunagou.cmd' --project-root 'D:\Tsunagou-fx-live-20260928' project timings '450286e4-8d1b-4220-840c-e540fe696913' --task-id '74f34f37-f3df-44ef-a5f0-8991de6243b7' --json
```

本轮实际返回开始 `13:58:12.337Z`、提交 `14:10:33.066Z`、审查 `14:21:50.715Z`（均 2026-09-28 UTC），工作经过 740729ms、审查等待 677649ms。这是服务端记录的业务边界时间，不是纯编码时间或 fsync 完成测量。timings 由多个只读 HTTP 查询组成，不保证原子快照。

本机 collector 的原始 `spans.ndjson` 只作 export 输入，export 将读取每行并只复制真实有效的 5 个已登记 span 边界和安全属性；不会修改输入文件，不会把任意 OTLP 内容复制出去：

```powershell
$traceFile = Join-Path $sourceRoot 'docs\acceptance\evidence\live-repair-20260928T125752Z\spans.ndjson'
& $python (Join-Path $sourceRoot 'tools\dev\live_repair_acceptance.py') export --output $evidenceRoot --trace-file $traceFile
```

省略 `--trace-file` 时只导出 CLI 时间线。核对 `trace.json` 和 `summary.md`：A1–A8 仍是 `not_run`，项目确认是 `unverified`，用量为 `unavailable`。export 会过滤 access token、thread/session/pipe、私信及消息正文、span 属性中未登记的字段，并只接收当前 project_id 的 span。`check` 能记录状态，不能证明 Worker 的 LLM 实际执行任务或原会话自动唤醒。

## 6. 记录人工事实和结束条件

只在查看具体证据后，才手工编辑 `review.json` 中对应 A 项的 `status`、UTC `observed_at` 和相对证据文件 `evidence_refs`。有效状态为 `pass`、`fail` 或 `not_run`；pass 缺少可读的本地证据引用或有效观测时间时，export 会降为 `not_run`。脚本将结论标为人工复核，不根据 Agent 成员数、ACK、diagnostics 或 trace 自动通过 A 项。保持完整失败记录，重新运行 `check` 后再次导出。重大项目完成确认单独记录，worker 任务 completed 不表示用户已确认项目完成。

未执行或证据不足的项保留为未完成；只有 A1–A8 均有审阅过的充分真实证据、FX3 原 Desktop 自动唤醒真实通过、业务 HTTP/页面正反样本通过，并由用户作出重大交付确认后，main 才能如实汇报最终完成。之后运行 `python tools/docs/validate_docs.py` 检查文档链接与结构。
