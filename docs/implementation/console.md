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

## 已知边界

- 控制台只监听本机（`host` 默认 `127.0.0.1`），不做多人或远程部署，也不替代 daemon 自己的权限边界。
- 撤回类动作（删除 Agent、向导回退、归档）后端未装配，按钮点了只说明"尚未实现"，不算缺陷。
- `web/` 与 `src/tsunagou/console/` 属于本机工具面，不进 `protocol/` 的跨语言契约；唯一例外是它们**读**的那些 daemon 出口（见上表），那些出口仍是正式接口。
