# `web/` —— 控制台前端（原 `Tsunagou 前端/`）

## 这是什么

Tsunagou 的**本机控制台界面**：零构建、零依赖（一个 `index.html` + 一个 IIFE 的 `behavior.js`），
由后端的 `tsunagou web start` 起一个本机小服务（`src/tsunagou/console/`）同源托管。

```
tsunagou web start        # 起中间层 + 托管本目录 + 打印地址
tsunagou web status       # 看它还在不在
```

## 数据只有一份来源

页面里**没有任何本地假数据**，也不认识“离线模式”：所有内容都来自中间层转发的 daemon 出口。

| 怎么开 | 会看到什么 |
|---|---|
| `tsunagou web start`，打开它打印的地址（推荐） | 真数据：本机项目列表 + 当前项目各屏的出口 |
| 直接双击 `index.html`（file://，不起任何服务） | 只有空骨架 + 拉取失败的提示 |

`console.config.js` 里只有两个字段：`baseUrl` 与 `poll_ms`。中间层托管时会**在同名路径上生成一份替换品**（见 `src/tsunagou/console/app.py`），所以不用改任何文件。

## 改样式时不想被刷新（地址栏开发开关）

改 CSS / 调界面时，那 5 秒一次的自动重拉会不断重画整屏。地址栏加参数即可停掉，
**只影响这一次打开，不改任何文件**：

| 参数 | 作用 |
|---|---|
| `?poll_ms=0` | 关掉**定时**重拉（`projects / tasks / agents / project`）。开项目、点标签、写操作后的即时重拉该刷还是刷 —— 那些是用户自己的操作 |
| `?shape=dag` | 总路径一进来就停在「DAG路径图」，省得每次刷新都去点一下那个选择框 |

两个一起用就是改 `dag.css` 时的姿势：`http://127.0.0.1:8791/?poll_ms=0&shape=dag`。
（`poll_ms` 与 `console.config.js` 里那个是同一个意思：`0` 或负数 = 不自动重拉；
生效时控制台会打一行 `[开发开关]`。）

## 怎么验收

```powershell
uv run python tools/dev/console_smoke.py --reset   # 一键冒烟：沙箱内起真 daemon + 真控制台，逐个出口断言
corepack pnpm exec vitest run web/tests            # 前端结构冒烟（不需要后端）
```

## 三条铁律（改这个目录时必须遵守）

1. **`assets/css/*` 绝对不能改。** 它相当于一套组件库，`behavior.js` 只是调用者。
   CSS 有独立的版权归属，改动必须先问人。两份都是这个规矩：`style.css` 是主页面那套组件库，
   `dag.css` 是**总路径 DAG 图**的样式（2026-09-29 从独立图页面 `DAG/` 搬进来，收在 `.dagArea` 里）。
2. **JS 不写布局类行内样式**：显隐只写 `display`（隐藏写 `'none'`，显示清成 `''` 交回 CSS）。
   唯一例外是侧栏拖拽的 `width`，那本身就是功能。
3. **渲染出来的 DOM 只能复用 `index.html` 里已有的元素与类名**，不要自造新元素/新类名。

## 目录

| 路径 | 说明 |
|---|---|
| `index.html` | 纯静态骨架：9 个标签页 + 6 个侧栏 + 窗口；`onclick` 全指 `Tsunagou.app.*` |
| `assets/js/behavior.js` | 整个应用（单文件 IIFE，`§0–§8` 分节，**改前先读 `method.md` §2 的分节索引**） |
| `console.config.js` | 前端可读的运行配置（接口前缀、轮询间隔） |
| `tests/behavior.smoke.test.ts` | 前端结构冒烟（vitest + jsdom）：断言总路径行的选择器层级、验收格的多行 `.colu-t` 结构 |
| `method.md` | **前端侧契约文档**：API 总览、dispatch 类型表、HTTP 接口表、字段对照、事件表、DOM 契约、改动清单。**改代码必须同步它。** |
| `assets/css/`、`assets/img/`、`assets/webfonts/` | 样式与素材（**不要改**，见铁律 1）。`assets/css/dag.css` 是总路径 DAG 图的样式（与 `style.css` 分开，不合并） |

## 来源与归属

- 本目录是从 `Tsunagou 前端/` **复制**进来的（2026-09-28），目的是让"后端 + 控制台"成为一个自足的项目。
- 原目录**保持不动**；其中 `备份20260926/`（改动前的整份快照）**没有复制进来**。
- 界面与 CSS 的设计权属于原作者（前端：陈林榕），后端与中间层由本项目维护；
  改动 HTML 结构或 CSS 之前必须取得同意。
