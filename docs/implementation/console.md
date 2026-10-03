# 本机控制台（中间层 + 页面）

本机控制台是**交付物的一部分**，不是一个演示壳：它把厂商无关的领域出口拼成人能读的一屏，也是唯一一条"人直接操作 daemon"的路径。本文给维护前端与中间层的人用。

## 组成与责任

| 部分 | 位置 | 责任 |
|---|---|---|
| 中间层 | `src/tsunagou/console/` | 读配置、发现项目、代发命令（补令牌）、聚合读取出口、同源托管页面 |
| 页面 | `web/` | 只显示：把出口形状翻译成界面形状（`BACKEND_SHAPE`），不自己造数据 |
| 活配置 | `.tsunagou-console.json`（随机器不同，**不入库**）；样例见仓库根 `.tsunagou-console.example.json` | host/port、项目根与扫描根、机器级索引、用户档案、轮询间隔 |
| 一键验收 | `tools/dev/console_smoke.py` | 建沙箱项目 → 起 daemon 与控制台 → 逐个出口断言 |
| 前端结构冒烟 | `web/tests/behavior.smoke.test.ts` | jsdom 载入真页面，断言选择器与多行格子结构 |
| 前端侧契约 | `web/method.md`、`web/README.md` | API 总览、dispatch 表、字段对照、DOM 契约 |

## 数据流与不变量

```text
浏览器页面（web/） ──同源──▶ 中间层（console/） ──HTTP + 令牌──▶ 项目 daemon（api/）
```

1. **一个 daemon 只服务一个项目**，所以"本机有哪些项目"只能由中间层回答（`/console/projects` 与机器级索引 `~/.tsunagou/projects.json`）。
2. **中间层只搬运，不解释领域**：一屏要的几个出口由它聚合（`CONSOLE_VIEWS`），领域→界面的翻译一律发生在页面里。少一个出口的表现就是"那一格空着"、且不报任何错，所以冒烟必须盯住每个视图的 `sources` / `missing`。
3. **页面没有本地假数据**：仓库里不存在演示后端或离线数据集；双击 `index.html` 只会得到空骨架，要看数据必须 `tsunagou web start`。
4. **样式归用户**：`web/assets/css/*` 是使用者的版权，实现方不改；JS 只写 `display`，不写布局类行内样式。

## 三件事怎么跑

```powershell
tsunagou web start                                 # 起中间层并托管页面（打印地址）
tsunagou web status                                # 看它还在不在
uv run python tools/dev/console_smoke.py --reset   # 一键冒烟：沙箱内起真 daemon + 真控制台
corepack pnpm exec vitest run web/tests            # 前端结构冒烟（不需要后端）
```

## 出口索引

| 需要的东西 | 从哪读 |
|---|---|
| 总览 / 任务 / 审计 / 冲突 / 验收 | `GET /api/v1/console/views/{view}?project_id=…`（聚合），再加页面自己拉的 `history`、`checkpoints`、`checkpoint-failures`、`reviews`、`intents`、`conflicts` |
| 项目列表与每个项目的负责人 | `GET /api/v1/console/projects`、`GET /api/v1/console/agents` |
| 用户档案（昵称/主题/Agent 昵称） | `GET`、`PUT /api/v1/console/profile` |
| 后端取值的中文对照 | `GET /api/v1/console/glossary` |
| 写动作 | `POST /api/v1/…`（中间层补令牌后转发；命令名与权限见[命令目录](command-catalog.md)） |

HTTP 侧的完整表格在 [CLI/HTTP 说明书](../overview/cli-http-manual.md)；前端侧逐字段对照在 `web/method.md` §6/§7。

## Codex 一句话接入

在控制台选好项目、昵称和主/子 Agent 后，在目标 Codex Desktop 对话中说 **“请接入 Tsunagou”**。已安装的接入 Skill 执行 `tsunagou agent join`；不要求用户重复输入目录、角色或会话 ID。

这一流程限定同一台机器、同一 OS 用户。控制台把接入申请存入用户私有的 `~/.tsunagou/console-enrollments`，跨控制台、跨项目最多只有一个有效申请。CLI 从该记录取得项目和角色，从实际 Codex 对话核验宿主身份，再复用 connect 完成签票、绑定和共享 MCP 登记。当前工作目录不会替代控制台的项目选择；无申请时明确报错，不初始化项目，也不默认为 worker。

| 阶段 | 后端回答与页面行为 |
|---|---|
| 准备 | `prepared`，`host_registration.status=deferred`；尚未签票或登记 MCP，页面继续等待 |
| 等待认领 | `waiting / pending`；提示在目标对话说“请接入 Tsunagou” |
| 正在接入 | `waiting / connecting`；实际对话已认领，其他对话不能领取 |
| 已登记 | `waiting / enrolled`；仍需原对话加载工具并调用 `context__project_read` |
| 接入失败 | `waiting / failed`；保留原认领，原对话可重试 `agent join`，页面显示后端 `note` |
| 完成 | `arrived`；本次绑定的 Agent、会话和角色已就绪，并有原宿主上下文读取回执 |

辅助进程的成功查询不产生原会话回执；别的 Agent 就绪也不能完成这次等待。同一对话重试复用原身份，重启控制台后仍可按 `enrollment_id` 查询旧申请。未认领申请可以取消或过期；已认领或已登记时取消返回 409，页面继续等待并说明原因，不注销全局共享 MCP，也不移除已经加入的 Agent。

页面启动时通过 `GET /console/enrollments/current` 找回公共申请状态并恢复等待/取消。遮罩标明原项目与角色；完成只刷新该项目相关数据，不推进丢失的旧向导或切换当前项目。prepare 对相同项目/角色幂等，保留原昵称；不同选择返回带公共申请引用和说明的 409。准备新申请前会先收取已完成回执，释放原申请占位。

首次安装必须让目标 Codex 加载接入 Skill 和共享 MCP；可能需要完整退出再打开一次。已加载的共享 bridge 每次调用读取路由，因此后续新对话绑定无需重建所有 MCP。自动化测试验证程序行为；真实 Desktop 原会话的成功必须另有现场记录，不能用模拟客户端代替。

## 非 Codex 宿主：先看它是哪一种

`GET /console/hosts` 每一项的 `mode` 直接回答"点下一步会发生什么"，只有三态：

| mode | 含义 | 页面行为 |
|---|---|---|
| `console` | 页面能替这个宿主办完接入 | 发准备请求，进等待（等票被兑换） |
| `in_host` | 只能在这个宿主自己的聊天里接入（DeepSeek Harness） | 发准备请求**只为记下"接哪个项目、什么角色"**（不签票、不写宿主配置），然后进同一块等待遮罩：盯着名单里出现它（`enrollments:observe`，判断在中间层） |
| `unsupported` | 还没做（Claude Code、ZCode） | 不发请求，照实说"还没做" |

只有 `console` 才签票：另外两种都不产生票据文件——给一个兑不了的宿主签票，看起来像有进展，最后只会等到"票过期"。`in_host` 那边的票是宿主聊天里的 CLI 以用户身份自己签的（身份来自宿主给的会话 id），页面既不签也不作废。

**三种宿主现在都写同一条机器级待接入记录**（`platform/enrollment_store.py`，每个 OS 用户同时一条）：`{adapter, project_id, project_root, role, nickname, 过期时间}`，不含任何凭据。它回答的是"聊天里被要求接入时，我该接哪个项目、什么角色"——聊天手上只有自己的会话 id 和工作目录，而工作目录常常不是协调仓库。读它有三个入口：Codex 的 `agent join`（认领后签票）、连接路径的解析回退（`agent connect`，工作目录推不出项目时用它）、以及只读的 `tsunagou agent pending --adapter <adapter>`。到达后由 `observe` / `status` 关掉这条记录，让下一个 Agent 接得上；页面的「停止等待」也会撤掉它。技术决定见 [接入时的项目从哪来](../decisions/2026-10-02-enrollment-record.md)。

**记录里的角色就是最终角色。** 页面上选主 Agent，那条聊天就只能以主 Agent 接入：`agent connect` 在没给 `--role` 时用记录里的角色，给了**冲突**的角色直接拒绝（`enrollment_role_conflict`，且在写任何桥材料之前）；`observe` 的到达判定也核对角色，席位角色不符时只报"连上了但角色不对"，绝不报"主 Agent 已接入"，且**不收掉记录**（真正该来的那个还能用它）。daemon 那层本来就保证了"角色只认票"。

两种 `console` 形态：

- **Codex**：只存选择，真实聊天认领后才签票（见上一节，技术决定见 [Codex 控制台接入](../decisions/2026-10-02-console-codex-join.md)）。
- **OpenCode**：控制台发一个会话名 `ses_<profile>` 并绑进票；页面把"用这个名字开会话"说给人，人用同一个名字打开会话，身份就对得上（此前控制台编的 id 与真实会话 id 对不上，bridge 会把票丢掉）。名字记在 bridge 目录的 `host-identity.json` 里，重试沿用同一个。

控制台**照抄**中间层给的 `next` 作为等待提示，不自己编文案。技术决定见 [控制台接入](../decisions/2026-10-02-console-enroll-modes.md)。

## 跨机器：主机发邀请（第四种"形态"）

除了上面三种本机接入，页面还能发一张**给另一台机器**的邀请（`位置＝网络`）。这一条与前三种的区别只有一句：
**主机这边什么都不写** —— 不写桥材料、不登记宿主，只签一张一次性票并把内容交给人转递；票、身份与桥配置
都由远端在自己的机器上写（`tsunagou agent import`），项目仍然只有主机上那一份。

- 入口：`agents:prepare` 带 `place=network`（以及 Codex/DSH 需要的 `conversation_id`），走
  `enrollment.py::_prepare_network()`；回答 `{status:'invited', invite, enrollment_id, url, expires_in_seconds}`。
- 身份：OpenCode 的会话名由主机起（`ses_<profile>`）；Codex / DeepSeek Harness 的会话名只有宿主自己知道，
  必须先由远端 `agent whoami` 报号（页面为这一格只在"网络 + 这两个厂商"时显示）。
- 等待：仍然复用 `enrollments:observe` 与那条机器级记录（角色核对也照旧），所以"到了"的判定与 `in_host`
  完全同一套；取消邀请会撤掉记录。
- 主 Agent 不跨机器（必须与 daemon 同机），所以 `place=network` 一律子 Agent。
- 与既有约定的一处**有意**例外：票的明文本来"永不进页面"，而邀请必须以内容形式交给人。缓解手段是票本身的
  限制（一次性、10 分钟、只能子 Agent）。技术决定见 [跨机器邀请](../decisions/2026-10-03-cross-machine-invite.md)。

## 已知边界

- 控制台只监听本机（`host` 默认 `127.0.0.1`），不做多人或远程部署，也不替代 daemon 自己的权限边界。
- 撤回类动作（删除 Agent、向导回退、归档）后端未装配，按钮点了只说明"尚未实现"，不算缺陷。
- `web/` 与 `src/tsunagou/console/` 属于本机工具面，不进 `protocol/` 的跨语言契约；唯一例外是它们**读**的那些 daemon 出口（见上表），那些出口仍是正式接口。
