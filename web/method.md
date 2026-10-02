# method.md —— Tsunagou 前端 JS 结构说明

> 面向对象：写后端的同学、以及以后维护 `assets/js/behavior.js` 的人。
> 目标：**后端不需要知道任何 DOM 细节**，只要按本文的字段名下发数据、按本文的接口表收发请求即可驱动整个界面。

---

## 0. 三条铁律

1. **显隐只写 `display`**。隐藏写 `'none'`；显示要写 CSS 里那个真实的 display 值。
   注意 `.tabMain`、`.asideMain`、`.asideMain .contentNDP` 在 CSS 里的默认值就是 `none`，
   所以它们"显示"时必须显式写 `'flex'`，清成 `''` 只会继续保持隐藏。
   只有需要淡入的窗口/面板才额外写 `opacity`（两步法：落 display → 强制重排 → 写 opacity）。
   **JS 从不写宽高、背景、flex 等布局行内样式**（只有两处例外，都是功能本身：侧栏拖拽的 `width`、
   总路径 DAG 画布的 `min-height` 与图里节点的 `left` / `top`；画布**宽度不定**，
   由 CSS 决定，跟着 `.dagArea` 走，SVG 也不设 `viewBox` —— 边和节点用同一套像素坐标，
   所以窗口缩放、滚动条出现都不会让图跑偏）。
2. **CSS 不可改**。所有渲染出来的 DOM 都必须复用 `index.html` 里已有的类名。
   `assets/css/style.css` 相当于一套组件库，`behavior.js` 只是它的调用者；
   `assets/css/dag.css` 是总路径 DAG 图的样式（独立一份、不与前者合并，同样不能改）。
   层级也要照 CSS 的选择器对齐：**页面标题**（`.tabMain` 的直接子级）是 `.title > .left`
   （品牌色胶囊挂在 `.left` 上，右侧 `.right` 是工具区/选择框），JS 侧对应 `pageTitleHtml()`；
   卡片 / 窗口 / 侧栏里那些 `.title` 是另一套样式，仍然用 `titleHtml()`。
3. **对外只挂 `window.Tsunagou`**。旧的全局函数（`openWindow` / `closeWindow` / `setColorTab` 等）已全部删除，
   `index.html` 的 `onclick` 统一指向 `Tsunagou.app.*`。

---

## 1. 30 秒上手

```js
// ① 接后端：把地址指过去，然后拉一次数据
Tsunagou.config.setBaseUrl('http://127.0.0.1:8000/api'); // 默认 '/api'（同源）
await Tsunagou.refresh(['projects', 'agentsWindow', 'settings']); // 全局数据
await Tsunagou.app.openProject('p-xxx');                          // 开某个协作（会拉它的项目数据）

// ② 后端主动推数据（不需要刷新整页）
Tsunagou.dispatch({ type: 'task.list', payload: [ /* 任务数组，字段见 §7 */ ] });
Tsunagou.dispatch('notify.success', { title: '后端已同步' });

// ③ 想知道用户干了什么：订阅事件（例如表单被失焦提交）
Tsunagou.events.on('form:commit', e => console.log(e.key, e.value));
```

> 后端的**中间层**（`src/tsunagou/console/`）按 §6 的接口表应答页面：`tsunagou web start`
> 起它、托管本目录、并在同源下生成一份 `console.config.js`。
> 页面里**没有任何本地假数据** —— 直接双击打开 `index.html` 只会得到空骨架（§7）。

页面加载完成时会派发一次 `ready` 事件，宿主脚本可以：

```js
Tsunagou.onReady(() => { /* 现在可以随便调 Tsunagou.* 了 */ });
```

---

## 2. 文件结构（区段索引）

`assets/js/behavior.js` 是一个 IIFE 里的单文件，用 `§n` 分节，**直接搜 `§0`…`§8` 就能跳转**：

| 区段 | 内容 |
|---|---|
| `§0 基础工具` | 查询 / 显隐 / 转义 / DOM 构造 / 事件委托原语 |
| `§1 配置·事件·状态` | `config`（地址、端点表）、事件总线、`state`（数据模型） |
| `§2 UI 原语` | 工作区、左侧栏、模态窗口、标签页、区块标签组、设置标签、向导、侧栏面板、选择框、侧栏拖拽 |
| `§3 反馈组件` | `notify.*`（成功/提示/错误/加载）、`dialog.confirm`、`dialog.decision` |
| `§4 通信层` | `api`（fetch 封装、响应解包、错误对象）、`form`（收集、失焦提交、按钮提交） |
| `§5 渲染层` | 通用小件 + 11 个页面渲染器 + 侧栏详情渲染器 + 总路径的 DAG（它自己再用 `§D1`…`§D4` 分小段：数据→图 / 摆位 / 渲染 / 对外接口，**前缀 D 就是 DAG，别和上面这套 §0…§8 撞名**） |
| `§6 动作与分发` | 点击路由、`actions`（业务动作）、`app`（页面命令）、`dispatch`（反向通道）、`refresh`、主题 |
| `§7 初始（空）状态` | `EMPTY_STATE`：空骨架，保证渲染器不缺字段、也不编数据 |
| `§8 启动` | 绑事件 → 铺数据 → 摆初始状态，最后调用 `init()` |

加载方式没有变：`index.html` 底部 `<script src="./assets/js/behavior.js"></script>`，没有构建、没有依赖。

---

## 3. API 总览

### 3.1 `Tsunagou.util` —— 工具
| 方法 | 说明 |
|---|---|
| `show(el\|id)` / `hide(el\|id)` | 清空行内 display 交回 CSS / 写 `display:none` |
| `display(el, value)` | 显式指定 display（默认是 none 的元素要用这个） |
| `reveal(el, 'flex')` / `conceal(el)` | 带 opacity 的淡入 / 直接隐藏并归零 opacity |
| `isShown(el\|id)` | 真正可见性（能识破"祖先被隐藏、自身仍是 flex"的陷阱） |
| `byId` / `qs` / `qsa` / `closest` / `resolveEl` | 查询（`resolveEl` 同时接受元素与 id 字符串） |
| `esc(text)` / `nl2br(text)` | 转义 / 转义+换行转 `<br>`（**渲染器内部强制使用**） |
| `time(value, {precise, second})` | 时间显示：默认 `9月28日16:05:02`（本年不写年份、跨年才写、不带毫秒）；`{precise:true}` 才给到毫秒（详情用）；解析不了就原样返回 |
| `gloss(域, 值)` | 后端参数值 → 中文（查中间层词表，见 §7.3）：命中就给中文，没命中**原样返回**（不编） |
| `wait(ms)` / `clamp(v,min,max)` / `clone(v)` / `toArray(v)` / `getPath` / `setPath` | 杂项 |
| `make(tag, cls, text)` / `parseHTML(html)` / `fill(容器, html)` | DOM 构造；`fill` 是渲染器的出口 |
| `delegateClick(selectors, handler)` | 挂一个 document 级点击委托 |

### 3.2 `Tsunagou.config`
| 方法 | 说明 |
|---|---|
| `setBaseUrl(url)` / `setToken(t)` / `setHeaders({})` / `setTimeout(ms)` | 请求相关 |
| `Tsunagou.startPolling()` / `stopPolling()` | 自动重拉开关；间隔来自 `console.config.js` 的 `poll_ms`（0 = 不轮询），页面在后台时不发请求。改样式时不想被定时重画：地址栏加 `?poll_ms=0`；`?shape=dag` 则一进来就停在总路径的 DAG |
| `setPaths({...})` / `setPath(key, path)` / `path(key)` | 覆盖接口路径（端点表见 §6） |
| `get()` / `snapshot()` | 读当前配置（只读副本） |

### 3.3 `Tsunagou.events` 与 `Tsunagou.state`
| 方法 | 说明 |
|---|---|
| `events.on(name, fn)` → 返回退订函数 / `once` / `off` / `emit` | 事件总线（事件表见 §8） |
| `state.get('agents', [])` | 按路径读数据 |
| `state.set('project.name', 'x')` | 按路径写数据（会派发 `state:change`） |
| `state.patch({...})` | 深合并 |
| `state.replace(全量)` / `state.reset()` | 整体替换 / 回到空骨架（清空全部后端数据） |
| `state.hydrate()` | 补齐缺失字段、**保留已有数据**（`init()` 用的是它，不会冲掉启动前就 dispatch 进来的数据） |
| `state.watch(fn)` | 等价于 `events.on('state:change', fn)` |

### 3.4 `Tsunagou.ui.*` —— 界面原语（只操作界面，不含业务）
| 调用 | 说明 |
|---|---|
| `ui.workspace.home()` / `.project()` / `.show('home'\|'project')` / `.current()` | 初始工作区 ↔ 项目工作区 |
| `ui.sidebar.fold()` / `.unfold()` / `.toggle()` / `.isFolded()` | 左侧栏宽版 ↔ 折叠版 |
| `ui.window.open(id, {reset})` / `.close(id)` / `.closeAll()` / `.closeTop()` / `.isOpen(id)` / `.list()` | 模态窗口 |
| `ui.window.clearInputs(id)` / `.fillInputs(id, [v1,v2])` | 清空 / 回填窗口里的输入 |
| `ui.tabs.project(slug\|序号\|中文名)` / `.current()` / `.list()` | 项目八个标签页（slug 见 §7） |
| `ui.blockTabs.select(block, i)` / `.selectByText` / `.current` / `.conflict(i)` / `.audit(i)` | 区块内标签组 |
| `ui.settingTabs.select(key)` / `.personal()` / `.about()` / `.current()` | 设置窗口两个页（`personal` 个性化设置 / `about` 关于）。传别的键（含已删除的 `data`）返回 `''`，不报错 |
| `ui.wizard.open()` / `.go(n)` / `.next()` / `.prev()` / `.reset()` / `.current()` / `.collect()` / `.finish()` | 新建协作四步向导。`.next()` 在第 1/2 步会真的建项目 / 接入主 Agent（返回 Promise，成功才翻页），第 3 步只是翻页；`.finish()` 只收窗复位。`.collect()` 返回 `{name, mainAgent:{name,vendor,icon}, subAgents:[]}` —— **没有 `objective`**：目标是用户与主 Agent 确认过之后才存在的事实，不作为建项目时的输入（见 §12 的 2026-10-01 两条） |
| `ui.aside.show(slug, section?)` / `.load(slug, section, title?)` / `.fill(...)` / `.hide(slug)` / `.hideAll()` / `.clearAll()` / `.isOpen(slug)` | 右侧侧栏（**默认全隐藏**，见 4.3；启动时会 `clearAll()` 清掉 index.html 里的占位内容） |
| `ui.choosebox.open/close/toggle/closeAll/setValue/value/isOpen` | 下拉选择框。`setValue(box, 值, {silent:true})` 只改显示值、不派发事件（**代码回填必须加 silent**）。展开的面板由 JS 定位：**与选择框等宽、对齐其右边缘、贴框正下方**，窗口缩放/滚动容器滚动时会跟随；收起时清掉行内 `width/left/top` |
| 表单“清空”时回到哪一项 | `resetCsBox(box)`（窗口/向导每次打开都会调）：面板里带 `data-default` 的那一项，没标记才退回第一项。两个厂商面板（`#newXz2Vendor` / `#addSubAgentVendor`）的默认都标在 **Codex** 上（它有注册命令，也是最早接入的宿主），所以向导第 2 步与添加子 Agent 窗口打开时选的都是 Codex |

### 3.5 `Tsunagou.notify` / `Tsunagou.dialog` —— 反馈组件
这四个组件就是原来"设置 → DEBUG 选项"里那四个弹窗，现在参数化了：

| 调用 | 长什么样 | 备注 |
|---|---|---|
| `notify.success({title, sub, icon, duration})` | 右下角，带进度条 | 进度条动画固定 2s（CSS），`duration` 只决定何时滑走（默认 2600ms） |
| `notify.info(text, {duration})` | 顶部居中一句话 | 默认 2500ms |
| `notify.error(text)` / `notify.warn(text)` | 同上，换图标和时长 | 颜色由 CSS 决定（和成功同色），**靠图标/文案区分** |
| `notify.loading(text, {cancel})` / `notify.loadingEnd()` | 转圈遮罩 `#loadW` | 传了 `cancel` 回调才显示遮罩上的「取消等待」入口（`notify.cancelWaiting()` 就是它的点击处理：先 `dialog.confirm`，确认后执行回调）；`notify.cancelPending()` 回答"确认框是不是正开着" |
| `await notify.track(text, promiseOrFn)` | 自动开关遮罩 | 失败的 promise 也会收起遮罩并继续抛出 |
| `await dialog.confirm({title, text, description, okText, cancelText, danger})` | 通用二次确认 | 返回 `boolean`；点 × / 遮罩 / Esc 都算 `false` |
| `await dialog.decision({title, content, actions:[{label, kind:'important'}]})` | 底部"需要用户确认/决定"卡片 | 返回被点按钮的 `value`（默认是 label）；`dialog.hideDecision()` 收起 |

> **可重入语义**：`dialog.confirm` / `dialog.decision` 在同一张卡片上再次调用时，
> **上一次未完成的 Promise 会被自动收尾**（confirm 给 `false`，decision 给 `null`），
> 不会出现两个 Promise 吊死的情况。`notify.success` / `info` / `error` 也同样，重复调用会重播进度条并重置计时。
>
> 另外：组件用的是**同一块 DOM**，所以内容每次调用都会整体重写 —— 想同时挂多条通知需要等后续扩展。

### 3.6 `Tsunagou.api` / `Tsunagou.form`
| 调用 | 说明 |
|---|---|
| `api.request({method, path, query, body, timeout, silent, headers})` | 底层；返回**解包后的 data** |
| `api.get(pathOrKey, query, options)` / `api.post(pathOrKey, body, options)` | `pathOrKey` 既可以是 `/x/y`，也可以是端点表里的键名（如 `'tasks'`） |
| `api.path(key)` | 拿到某键最终会请求的真实地址（便于后端对齐路由） |
| `form.collect(root, {byKey})` / `form.fill(root, values)` | 收集 / 回填一组 input |
| `form.commit(input, options)` | 手动提交一个输入框 |
| `form.watch(root)` | 扫描并给"没有提交按钮"的 input 装上失焦提交 |
| `form.submitByButton(root, {path})` | 按钮提交：收集容器内所有 input 后 POST |

**响应解包**支持三种后端风格，任选其一：
1. `{code: 0, message: '', data: {...}}` → 取 `data`；`code` 非 0 视为失败
2. `{code: 0, result: {...}}` → 取 `result`
3. 裸 JSON / 数组 / 纯文本 → 原样返回

`code` 被认可为成功的值：`0` / `'0'` / `200` / `'200'` / `'ok'` / `'OK'` / `'success'` / `true`。
失败时抛 `Tsunagou.api.ApiError`（有 `message` / `status` / `code` / `raw` / `url` / `method`），
并且**默认自动弹一次错误提示**；传 `{silent: true}` 可以关掉。

### 3.7 `Tsunagou.app` —— 页面级命令（index.html 的 onclick 全指向这里）
`createProject()` `openProject(id?)` `openHome()` `openAgents()` `openAgentInfo(id)` `editAgent(id)` `saveAgentInfo()`
`deleteProject(id)`
`setAgentNetwork(id, online)` `clearAgentNetwork(id)`（跨机器协作那条，见下面的注与 §5.1）
`openSettings(key?)`
`settingTab(key)` `openWindow(id)` `closeWindow(id)` `addSubAgent({name,vendor,source}?)`
`cancelWaiting()`
`wizardNext()` `wizardPrev()` `wizardFinish()` `foldSidebar()` `unfoldSidebar()` `toggleSidebar()` `setTheme(mode)`
`app.demo.success() / .info() / .loading() / .decision()`（DEBUG 页那四个按钮，也是组件的现场演示）

> `openProject(id)` 是整个应用的入口动作：把 `currentProjectId` 切成 `id`、重绘左栏选中态、
> **把标签页切回主视图**（并顺手收起所有侧栏）、切到项目工作区，最后拉取十个项目作用域接口。
> 不传 `id` 时只切工作区（不改标签页、不拉数据）。
> "换项目就回主视图"这条是为了不让上一个项目停留的标签页带到新项目来。

> `addSubAgent({source})` 的 `source` 只影响"提交成功后结果回到哪里"（`'wizard'` → 向导第 3 步的
> 已接入列表；`'agents'` → Agent 列表并重拉）。页面上点加号会自动带上它，手动调用不传则沿用上一次的来源。

> `cancelWaiting()` 是加载遮罩上「取消等待」入口的落点（`#loadWCancel`）：只在**可以取消的等待**
> （接入 Agent）里露面，点击后先弹一次确认，再请求中间层取消；结果由服务端判断，409 时继续等。见 §7.1。

> `deleteProject(id)` 是左栏卡片右上角那个 `.edit`（CSS 里 hover 才露出来）的落点，也可以从宿主脚本调：
> 先 `dialog.confirm`（`danger` 样式），确认后 `POST /console/projects/{id}:forget` → 停 daemon →
> 注销该项目在宿主里的 bridge → 忘掉没到齐的票 → 删索引条目 → 删目录（只删 `projects_root` 底下的）。
> 删掉的是"整个项目"，不是分步后撤；报告里 `files.deleted === false` 时页面会多提醒一句为什么没删。
> 当前项目被删掉时会回到初始工作区，并忘掉 `localStorage` 里那个"上次打开的项目"。

> `editAgent(id)` / `saveAgentInfo()` 是「改昵称」的两个入口（2026-09-28）：前者开 Agent 详情窗口
> （`agent.edit:<id>` 的处理器，Agent 管理卡片上的「修改」按钮用它），后者是那个窗口「确定」的落点 ——
> 把**昵称**存进中间层的用户档案（`PUT /console/profile` 的 `{agents:{<id>:{nickname}}}`），
> **厂商从不上送**（它来自哪个宿主是接入时定下的，不让改）；值没变就只关窗、不发请求。
> 没有 `agent_id` 的记录（宿主自己 dispatch 的 `agent.info` 可能没带）会如实说改不了。

> `setAgentNetwork(id, online)` / `clearAgentNetwork(id)` 是**跨机器协作**里「这个 Agent 是从网络
> 接进来的」那个标记（2026-10-02）。中间层（控制台）知道一个**子 Agent** 的桥不在本机时调它：
> `online` 给 `true`/`false`（网络在线 / 网络离线），也可以给 `{network, online}` 两个都说；
> `clearAgentNetwork(id)` 等于撤回（回到“本机接入”）。**本机接入的不用调** —— 默认就不画徽标
> （「网络在线 / 网络离线」和右边那个 `<i class="fa-solid fa-circle-nodes">` **一个都不出现**）。
> 只动状态与徽标，**不发请求**；主 Agent 必须在 daemon 所在机器上，推了也不画。
> 接口里带 `network`/`online` 字段（随刷新到）也行，两条通道等价 —— 推来的优先于数据里的。

> `wizardPrev()` 现在**只提示未实现**（2026-09-28）：向导的「上一步」想做的事 = 撤回上一步的效果，
> 而项目建好不能删、接上的 Agent 也不能撤回。低层导航仍可用 `ui.wizard.prev()`（给宿主脚本），
> 页面按钮不再用它。

### 3.8 `Tsunagou.actions` —— 业务动作（可单独调用）
`createProject(draft)` `addSubAgent({name,vendor,source})` `removeAgent(id)` `setMainAgent(id)`
`deleteProject(id)`
`acceptanceConfirm()` `acceptanceArchive()`
`checkpointRetry(id)`

每个动作的统一套路：**（必要时先 `confirm`）→ 发请求 → 成功提示 → 局部重绘**；
失败由 `api` 统一提示并抛出，不会出现"界面变了但后端没变"的情况。

几个例外/补充：
- `createProject({name, path?})` —— 中间层掌管的写入口（`POST /projects`：建目录、`git init`、
  登记进索引，并顺手把 daemon 起起来）。**返回后端那份项目**（`{project_id, name, objective, …}`），失败返回 `false` ——
  向导要靠这个 id 把"当前协作"切过去，才能接着接入 Agent。
  `objective` 仍然是可选项（脚本调用可以直接给），只是向导不再问它；不给时中间层写占位文本。
- `addSubAgent({name,vendor,source})` —— **不发任何"创建 Agent"的请求**（后端没有这个概念）：
  它走的是§7.1 那条"准备接入 → 等宿主连上"的完整路，两个入口只是收尾不同：
  `source:'wizard'` 把结果记进向导第 3 步，`source:'agents'` 成功后重拉名单/卡片/昵称。
  `vendor` 必须能在 `GET /console/hosts` 里对上（表在中间层），对不上就照实说、不发请求。

- `deleteProject(id)` —— 一次性删掉整个协作（中间层 `POST /console/projects/{id}:forget`，体 `{delete_files}`）。
  中间层按顺序做：**停 daemon**（读 `.tsunagou/local/endpoint.json` 的 pid，与 `tsunagou daemon stop` 同一套做法）
  → 枚举 `<project>/.tsunagou/bridges/<adapter>-<profile>/` 逐个 `host_registration.unregister`
  → 忘掉这个项目没到齐的票（并删它们的票文件）→ 删索引条目 → 删目录。
  报告字段：`daemon` / `host_registrations[]` / `enrollments_dropped[]` / `index.removed` /
  `files:{path,deleted,reason?}`。**文件只删 `projects_root` 底下的**（登记进来的外部项目只注销登记，保留目录并写明原因）。

另外两个通用动作：
`actions.saveSetting(key, value)` —— 把一条设置交给后端（现在只有颜色主题用它）；
`actions.detectMainAgent()` —— 向导第 2 步：把厂商选择框的当前值同步到"你所选的 Agent"预览框。

还有两个跟昵称有关的：
`actions.saveAgentProfile(agentId, {nickname})` —— 只写昵称（界面上不传 `vendor`）；成功后重拉
`agents / tasks / audits / conflicts / project / agentsWindow / projects`（名字是按 id 现算的，
所以左栏卡片与 Agent 列表也得跟着重画）。
`actions.removeAgent(id)` —— **暂不实现**（不是待做项）：按钮留着，点了只说一句
「撤回功能当前尚未实现」（`NOT_IMPLEMENTED_TEXT`，`notImplemented()`）。
**不再有 `GET /agents/detect` 探测请求**（后端没有"Agent 地址"这个概念）。

---

## 4. 交互规则

### 4.1 标签页
9 个标签按钮 `#tab-<slug>` ↔ 9 个主视图 `#pane-<slug>` ↔ 6 个侧栏 `#aside-<slug>`，
一一对应关系写死在 `PROJECT_TABS` 里（不再靠 DOM 顺序猜）。

**换协作项目时一律回到主视图**（`app.openProject(id)` 内做的事情），
上一个项目停在哪个标签页不会带到新项目来；引用同一个项目时也会回主视图。

### 4.2 内容渲染
每个页面渲染器都是"整体替换容器内容"：`render.tasks(list)` 会重写 `#pane-tasks` 的 `innerHTML`。
所以后端只管给数据，不用关心增量更新。

**空状态**：某个容器没有内容时，渲染器会往里放一个 `<div class="emptybox"></div>`
（"这里暂时还没有内容"这行字由 CSS 的 `.emptybox::before` 生成，JS 只负责决定放不放）。
现在的覆盖范围：

| 位置 | 空时的样子 |
|---|---|
| 表格（`.tablebox`） | 表头 `.th` 后面跟一个 `.emptybox`（与你给的示例一致） |
| 卡片组（`.boxerbox`）、键值表（`.table`） | 容器里就只有一个 `.emptybox` |
| 总路径（`.taskFlow`） | 表头那行下面一个 `.emptybox` |
| 侧栏 | `ui.aside.show()` 时，要显示的那一段如果是空的，也补一个 |
| 左栏协作列表 | **后端明确返回了空列表**时（`projectListLoaded` 为真）；数据还没来的那一下留空，免得开页闪一下 |
| Agent 列表窗口 | Agent 列表为空时 |

> 空判断是**每个容器各自做**的：一个页面可以好几个小标题各自空着、各自提示。
> 两处例外：主视图整体没数据时只给一个（否则五个小节会各占 240px）；
> "项目进度"那栏不放（`.statbox .inner` 有 `max-height:100px`，装不下 240px 的占位块）。
> `render.agents` 的空状态会和末尾那个大加号并存（没 Agent 时还能直接点加号建一个）。

### 4.3 侧栏默认隐藏，点内容才出现
切标签页时**所有侧栏一律收起**，只有点击"对应内容"才出现：

| 侧栏 | 触发 | 显示哪一段 |
|---|---|---|
| 任务区 | 点任务行 | 第 1 段（任务细节） |
| 冲突与协商 | 点分歧卡片 / 点**冲突行** / 点**Agent 间协商行** / 点契约卡片；「查看契约」按钮 | 第 1 段＝分歧详情，第 2 段＝契约详情，第 3 段＝冲突详情，第 4 段＝Agent 间协商详情（四段互斥） |
| 意图与权限审计 | 点表格行（按当前子标签） | 第 1 段＝意图声明，第 2 段＝权限租约（互斥） |
| 工作区 | 点工作区卡片 | 第 1 段 |
| 总路径 | 点某条记录行 | 第 1 段（路径详情） |

侧栏标题栏右上角的 × 收起自己。也可以直接调 `ui.aside.show('tasks', 0)` 由后端唤出。

### 4.4 表单提交
| 情况 | 行为 |
|---|---|
| input 所在窗口/区块**有**主按钮（如 `#addSubAgent`、向导每一步） | 点按钮才提交。向导的「下一步」在第 1/2 步会**真的做事**（建项目 / 接入主 Agent，失败就停在原地），第 3 步只是翻页；「完成」只收窗复位、不再发请求。**校验不过时窗口/步骤保持不动**，只弹提示 |
| `#mgrAgentInfo` 的输入 | **昵称可改**，项目/任务只读（2026-10-02 换版式）：窗口里已经没有 `.items/.item`，是「标签 + 值」一路排下来 —— `>.title2` 当标签、`.textbox2 > input` 是昵称、`>.dspText` 依次是项目名称与任务名称。所以回填**按位置**（`render.agentInfoWindow`：`form.fill(node, [昵称])` + 两个 `.dspText`），不再按标签文字，`keyOfInput` 在这里也用不上（没有 `.item .fword`）。窗口里**没有「厂商」那一栏** —— 标题与胶囊上的 logo 已经说明它来自哪个宿主，而那个值是按 id 从用户档案现算的。标题文字由 `setWindowTitleText` 替换，**保留**标题里那个 `<i>` 图标（直接写 `textContent` 会把图标擦掉）。窗口里的「确定」= `app.saveAgentInfo()`（存昵称再关窗），**不再是关窗按钮**；因为 `#mgrAgentInfo` 在 `AUTOCOMMIT_EXCLUDE` 里，昵称框失焦**不会**自动提交 |
| input **没有**提交按钮（`.textbox` / `.textbox2` 里、不在 `#addProj` / `#addSubAgent` / `#mgrAgentInfo` 中，且所在区块没有按钮 —— 目前 `index.html` 里没有这样的静态输入框，这是留给动态渲染/宿主注入内容的机制） | **失焦即提交**，并提示"改动已成功保存"；按 Enter 等效于失焦；值没变化不重复提交、不重复提示 |
| 设置里的"颜色主题"下拉框 | 选中即生效（立即换肤）。**选回同一个值不会重复提示**；程序化回填必须走 `{silent:true}` |

> ⚠️ **代码回填 vs 用户点选**：`ui.choosebox.setValue()` 默认会派发 `choosebox:change`，与用户点选完全一样。
> 所以凡是**由代码写值**的地方（如 `render.settings()` 回填、`app.setTheme()` 同步下拉框）都必须传
> `{silent:true}`，否则页面一加载就会被当成"用户改了设置"，弹出"改动已成功保存"。
> 后端用 `dispatch('ui.choosebox.set', …)` 设置值时属于"替用户操作"，默认**不**静默（会有反馈）。

失焦提交时会把 `{input, key, value, previous, window}` 通过 **`form:commit` 事件**抛出来；
默认还会按 `config.paths.settingSave` 发一次 POST。想完全自己接管，就监听这个事件并把 `config.mode` 设成 live 之前
用 `setPaths({settingSave: ...})` 指到你自己的地址。

### 4.5 点击路由
- 渲染出来的按钮都带 `data-tg-action="名字:参数"`，统一由动作表执行；
  **没注册的名字不会被吞掉**，而是以 `action:request` 事件抛给后端/宿主。
- 点卡片内的 `.listfieldbox` 胶囊不会误触发外层的行点击（选择器用 `>` 限定了层级）。

### 4.6 动作与"确认框"的分工
需要二次确认的动作自己弹 `dialog.confirm()`；**别和界面上已有的确认文案叠加**，否则会出现"点确定又弹一个一模一样的框"。

| 动作 | 触发处 | 确认方式 |
|---|---|---|
| `acceptanceConfirm`（确认完成）· `checkpointCreate`（立即存档）· `checkpointRetry`（重试）· `setMainAgent`（设为主 Agent） | 卡片/表格行上的按钮（那里没有确认文案） | 动作内先 `dialog.confirm()`（弹 `#delPmt`），确认后再发请求 |
| `deleteProject`（删除协作）· `cancelWaiting`（取消等待） | 项目卡片右上角 · 加载遮罩上 | 同样先 `dialog.confirm()`，并带 `danger:true` / 详细的后果说明 |
| `decisionResolve`（决定） | 「待用户决定」卡片 | 用 `dialog.decision()`：**选项本身就是二次确认**（没有重选的机会，所以不能叠一个确认框） |

**2026-09-29 把全部动作过了一遍**（结论写在这里，省得以后再猜）：
- **不加确认的**：向导第 1 步「下一步」（虽然会建项目目录 + 登记索引，但**向导本身就是多步表单**，
  “下一步”已经是一次明确动作 —— 你定的）；`checkpointVerify`（校验存档点）—— `CheckpointStore.verify`
  是**只读**校验（只读 manifest 与文件字节、不写状态）；`decisionLater`（稍后）—— 纯本地收起，
  跟后端无关；保存昵称/主题 —— 窗口「确定」或失焦提交本身就是第二步，而且都能改回。
- **已确认的**：确认完成 / 重试存档 / 立即存档 / 设为主 Agent / 删除协作 / 取消等待 / 取消接入 / 决定。

> 判断标准：**触发它的界面上已经写了"确定要…吗？此操作不可挽回"吗？** 写了就不要再确认一次。

---

## 5. `Tsunagou.dispatch` 类型表（后端 → 前端）

```js
Tsunagou.dispatch({ type: 'task.list', payload: [...] });
Tsunagou.dispatch('ui.tab', 'tasks');        // 也支持 (type, payload) 简写
```
返回值：同步类型为 `{ok, type, value}`；异步类型（如 `dialog.confirm`）返回 Promise<同结构>。
未知 type 返回 `{ok:false, error:'未知的 dispatch 类型：xxx'}`，并派发 `dispatch:error`。
`Tsunagou.types()` 可以列出全部 47 个类型（2026-10-02 在真页面上数过：`Tsunagou.types().length` —— 这句以前写 39，已经跟不上了）。

### 5.1 数据类
| type | payload | 作用 |
|---|---|---|
| `state.replace` / `state.patch` / `state.reset` | 全量 / 局部 / 无 | 改状态并整体重绘 |
| `render.all` | — | 按当前 state 重绘全部 |
| `project.list` | 数组 | 左栏协作列表 |
| `project.current` | 对象 | 主视图 |
| `agent.list` | 数组 | Agent 管理页 |
| `agent.window` | 数组 | Agent 列表窗口 |
| `agent.info` | 对象 | 打开并填充 Agent 详情窗口 |
| `task.list` | 数组 | 任务区 |
| `conflict.data` | `{dissents, conflicts, messages, contracts}` | 冲突与协商（4 个子标签） |
| `audit.data` | `{intents, leases, waiting}` | 意图与权限审计 |
| `workspace.list` | 数组 | 工作区 |
| `acceptance.data` | `{proposal, taskResults}` | 验收与存档点（段 1、段 2） |
| `checkpoint.list` | `{latest, history}` | 存档点（三个段落里的前两段） |
| `checkpoint.failures` | `{items:[{operation_id,status,error_code,reason,created_at,attempt_count}]}` | 存档点第三段「存档失败」（新的出口，2026-09-29） |
| `timeline.list` | `[{era, items:[]}]` | 总路径 |
| `task.detail` | 单条任务的额外详情 | 存进 `state.taskDetail`，点任务行时合并到侧栏（详见 §7） |
| `settings.data` | `{theme}` | 回填设置控件（现在只剩颜色主题） |
| `wizard.subAgents` | 数组 | 新建协作第 3 步的子 Agent 列表 |
| `agent.network` | `{agent_id, online}` | 跨机器：定一个 Agent 是“网络接入”（`online` 定在线/离线）并**立刻重画**徽标；`{network:false}` 等于撤回 |
| `agent.network.clear` | `{agent_id}` 或 id | 撤回：这个 Agent 是本机接入的（回到“不画徽标”） |

### 5.2 反馈类
`notify.success`（payload 同 `notify.success()` 的参数）、`notify.info`、`notify.error`、
`notify.loading`、`notify.loading.hide`、`dialog.confirm`、`dialog.decision`

### 5.3 界面类
`ui.window.open` / `ui.window.close`（payload 是 id 或 `{id}`）、`ui.window.closeAll`、
`ui.workspace`（`'home'|'project'`）、`ui.sidebar`（`true`＝折叠）、
`ui.tab`（slug/序号/中文名）、`ui.blocktab`（`{block:'conflict'|'audit', index}`）、
`ui.settingtab`、`ui.wizard.go`、`ui.aside.show`（`{slug, section}`）、`ui.aside.hide`、`ui.aside.hideAll`、
`ui.choosebox.set`（`{panel:'uSetCol1', value:'浅色'}`）、`theme.set`、
`ui.project.open`（`id` 或 `{id}`）、`ui.workspace.home`（回初始工作区，等价于 `app.openHome()`）

> 另外：渲染器写出的按钮若把 `data-tg-action` 写成 dispatch 类型名（如 `ui.workspace.home`），
> 点击时先在动作表里找，找不到就直接当 dispatch 执行 —— 这是机制，不代表页面上已经用了它。

### 5.4 `Tsunagou.refresh(keys?)`
- `live` 模式：并发拉取 §6 里所有"读取类"接口并逐项 dispatch，返回 `{results, failed}`；
  有失败项时统一弹一次错误提示。
- 传 `keys` 可以只刷新其中几项，例如 `refresh(['tasks','acceptance'])`。

---

## 6. 默认 HTTP 接口表

基地址：`config.baseUrl`，默认 `'/api'`（同源）。全部可用 `config.setPath(key, path)` 覆盖。
读取类都是 `GET`，写入类都是 `POST`（`Content-Type: application/json`）。

**路径里的 `{project}` 是“当前协作项目”的 id**（`state.currentProjectId`），请求时自动替换。
还没选项目时，这类请求会被直接跳过：`refresh()` 不发它们，`api.request()` 直接报“还没有选择协作项目”，
不会拼出 `/projects//tasks` 这种地址去打扰后端。

**读取类**（2026-09-28 接线后的真实表；说明见 §10）
| 键 | 路径 | 作用域 | 期望返回 |
|---|---|---|---|
| `projects` | `/projects?agents=1` | 全局 | `{items:[{project_id,name,objective,lifecycle,policy_revision,path,daemon,main_agent_id,agents,agents_fetched_at}]}`（中间层提供；daemon 没有这个路由。`agents=1` 才去问名单，见 §7） |
| `agentsWindow` | `/console/agents` | 全局 | `{items:[{agent_id,role,status,project_id,project_name,task}],unreadable:[project_id],fetched_at}`（**跨项目汇总**：一行 = 一个 (项目, Agent)；中间层提供，见 §7） |
| `settings` | `/console/profile` | 全局 | `{version,nickname,theme,agents:{<agent_id>:{nickname,vendor}}}`（中间层的用户档案） |
| `glossary` | `/console/glossary` | 全局 | `{version, domains:{<域>:{<token>:中文}}}`（后端参数值的中文对照表，中间层维护，见 §7.3） |
| `hosts` | `/console/hosts` | 全局 | `{items:[{adapter,label,mode,note}]}`（中间层能替哪些宿主办完接入；`mode` 三态，见 §7.2） |
| `project` | `/console/views/overview?project_id={project}` | 当前项目 | 主视图（同时驱动顶部导航条）：`{sources:{overview,tasks,agents,cognition,checkpoints,decisions},missing:{}}` |
| `agents` | `/projects/{project}/agents` | 当前项目 | `{items:[{agent_id,role,status,authority_epoch,session_status,connection_epoch,missing_admission,missing_operational,...}]}`（后四个是"这个 Agent 现在还缺哪几项能力"：有活动会话时给状态 + 缺项名单，没有活动会话时四个都是 `null`，见 §7） |
| `tasks` | `/console/views/tasks?project_id={project}` | 当前项目 | 任务表（`sources:{tasks,attempts,agents,results}`，适配层才会 join 成负责人/交付物） |
| `conflicts` | `/console/views/collaboration?project_id={project}` | 当前项目 | `sources:{cognition,contracts,messages,agents,conflicts}` → `{dissents,conflicts,messages,contracts}` |
| `audits` | `/console/views/audit?project_id={project}` | 当前项目 | `sources:{intents,resources,agents}` → `{intents,leases}` |
| `workspaces` | `/projects/{project}/workspaces` | 当前项目 | 工作区卡片 |
| `acceptance` | `/console/views/acceptance?project_id={project}` | 当前项目 | `sources:{overview,decisions,tasks,results,reviews,agents}` → `{proposal, taskResults}`（段 2 的验收结论来自 `reviews`） |
| `checkpoints` | `/projects/{project}/checkpoints` | 当前项目 | `{items,current,...}` → `{latest,history}`（卡片：摘要+时间+取档原因+校验态） |
| `checkpointFailures` | `/projects/{project}/checkpoint-failures` | 当前项目 | `{project_id,items:[{operation_id,status,error_code,requested_by,reason,created_at,updated_at,revision,attempt_count,max_attempts}]}` → 「存档失败」那一段（**记账**，不是存档点） |
| `timeline` | `/projects/{project}/history` | 当前项目 | 审计分页 `{items:[...]}`（`event_seq` **升序**，`action` 是去掉 `command.` 前缀的 command kind）→ 按**阶段**分代的 `[{era,items}]`，见 §7 |

**写入类**（全部走 `POST /commands/{command_kind}`，只有 `settingSave` / `projectCreate` 由中间层掌管）
| 键 | 命令 / 路径 | 请求体（payload） |
|---|---|---|
| `agentSetMain` | `authority.appoint` | `{agent_id, expected_authority_epoch, reason}`（代次由 `agents` 出口的 `authority_epoch` 带上） |
| `checkpointRetry` | `checkpoint.create.user` | `{reason:'user_retry_after_failure', retry_operation_id}`（`durability.reconcile` 是 M 权限，控制台会 403） |
| `acceptanceConfirm` | `project.completion.confirm` | `{proposal_id, proposal_digest, expected_project_revision, expected_revisions}` |
| `decisionResolve` | `user_decision.resolve` | `{decision_id, choice, expected_revisions, proposal_digest, reason}`（`choice` 取待决定项的 `payload.choices` 原文） |
| `settingSave` | `PUT /console/profile` | `{theme}` 或 `{agents:{<agent_id>:{nickname,vendor}}}`（主题与 Agent 昵称不属于协作事实，存中间层） |
| `projectCreate` | `POST /projects` | `{name}` 在中间层配的 `projects_root` 下新建（不传 objective 时中间层写占位文本；目标不由建项目的人填，见 `docs/decisions/2026-10-01-objective-from-dialogue.md`）；传 `{path}` 则登记一个已存在的项目。**新建**时中间层会顺手写项目的 Agent 入口（`AGENTS.md` / `.tsunagou/agent-context.md` / 项目 skill），结果放在回答的 `project.bootstrap` 里；**登记**已有项目不动它的文件，所以没有这个键 |
| `projectForget` | `POST /console/projects/{project}:forget` | `{delete_files}`（默认 false）。**一次删掉整个项目**：停 daemon + 注销该项目的 bridge + 忘票 + 删索引条目 + （可选）删目录；路径里带的是**卡片那个** id，所以页面直接拼字面路径，不走 `WRITE_COMMANDS` 的 `{project}` 模板 |
| `acceptanceArchive` | —— | **已从界面撤掉**（决定 11）：`project.archive` 未装配，留着按钮只能弹「尚未实现」；`WRITE_COMMANDS` 里那条 `null` 还在，用于“后端没这个能力”的报错文案 |
| `agentRemove` | —— | **暂不实现**（决定 11）：`agent.retire` 未装配；同上 |
| `pathRecord` | —— | 后端无此概念 |

> **哪些真能发出去**（2026-09-29 更新）：`settingSave`（`PUT /console/profile`）与
> `projectCreate`（`POST /projects`）由**中间层**掌管，已接通（无设置表单时可用
> `Tsunagou.actions.saveSetting` / `saveAgentProfile` / `app.registerProject` 调）；
> 走 daemon 命令通道的 `agentSetMain` / `checkpointRetry` / `acceptanceConfirm` / `decisionResolve`
> **四个都接通了**（payload 与命令名都按 handler 的真实读法写过，实测有回应）。
> `agentRemove`（退席）、`acceptanceArchive`（归档）、`pathRecord` 后端根本没有。

> **没有通用的"创建 Agent"领域命令**：页面通过中间层的 `agents:prepare` 准备接入（§7.1）。
> Codex 保存待真实聊天认领的申请，由 `agent join` 复用 connect；其他宿主沿用中间层签票/登记。
> 最终身份都由真实宿主 bridge 兑换票据取得，前端不直接创建或伪造 Agent。

---

## 6.1 页面没有“演示后端”

页面里没有任何本地假数据，也没有“离线数据集”：所有内容都来自中间层转发的 daemon 出口。

| 怎么开 | 数据来自 | `console.config.js` |
|---|---|---|
| `tsunagou web start`（推荐） | 真项目：daemon 的查询出口（中间层代发 + 补令牌） | 中间层在同名路径上生成一份 |
| 直接双击 `index.html`（file://，不起任何服务） | 没有：只有空骨架 + 拉取失败的提示 | 仓库里那份（`baseUrl` + `poll_ms`） |

`tsunagou web start` 默认监听 `127.0.0.1:2812`：端口固定是为了人能把页面**收藏**下来；被占用时会
另取一个空闲端口，并在启动那行说明"默认端口被占用、改用 X，要收藏的是这个地址"。它**只允许监听回环地址**
（控制台自身没有任何认证，转发用的是各项目的控制令牌），要从别的机器看页面请走隧道。

以前这里有一份 `assets/js/mock-backend.js`：拦 `window.fetch`、按 §6 的接口表造样例数据。
它已在 2026-09-29 删掉 —— 它的代价是“页面看起来能用”与“后端真的能用”分不清，
而本仓库要交付的是后者。要看页面在真数据上的样子，用 `tsunagou web start`（真 daemon），
或跑一次 `uv run python tools/dev/console_smoke.py --reset`（沙箱里起真 daemon + 真控制台）。

---

## 7. 数据模型字段对照

> 通用约定：`agent` 是 `{ name, icon }`，`icon` 取 `'deepseek' | 'codex' | 'claudecode'`
> （也可以直接给图片路径，只要以 `-l.png` / `-d.png` 结尾就会跟着主题自动切换）。
> 向导 / 添加子 Agent 里"厂商"是选择框的选项文字：`Claude Code` / `DeepSeek Harness` / `Codex` /
> `OpenCode` / `ZCode`（面板顺序就是这个），字段名用 `vendor`（**不是 `api`**）；
> 图标按 `vendor` 文字映射（`agentIconFor()`）。**默认项是 `Codex`** ——
> 面板里 Codex 那项带 `data-default`，`resetCsBox()` 认这个标记（见 §3.4）。
> 凡是多行的文本字段（如"改动的文件"）直接用 `\n` 分隔即可。

| `render.navbar(project)` | 项目页顶部导航条（名称 + 状态胶囊）。输出标记与原 index.html 的静态写法**完全一致**，只是改成由数据驱动；**由 `render.overview` 顺带调用**，所以 `project.current` / `refresh` 会一并更新它 |

### 左栏协作卡片 `render.list`
```
{ id, name, status:'working'|'preparing'|'finished', statusText, time, group:'done'?,
  selected?, mainAgent:{name,icon}|null, agents:[{name,icon}], extra:<其他 Agent 数量> }
```
> `agents` 是**其他** Agent（不含主 Agent），`extra` 也是它们的数量 —— 卡片的
> `+N` 就是它的原写法；最多摆 4 个头像。
>
> **选中态一列最多一张**（`projItemSelected` → CSS 把 `.title` 涂成品牌蓝）：由 `render.list`
> **整列一次算清**，优先"当前项目"（`state.currentProjectId`），没有再看第一条自称 `selected` 的
> （演示模式下新建的那张会自带 `selected`）。卡片自己不再各判各的 ——
> id 为空的条目一律不算：空 id 对上"还没选项目"会让**整列标题都变蓝**。
>
> 数据来自中间层的 `GET /projects?agents=1`：`main_agent_id` + `agents:[{agent_id,status,role}]`
> （只有 id，**名字/厂商仍由用户档案解析**，与 Agent 管理页同一套）。
> **名单由中间层维护**（`console/agents.py`）：首次读到（“打开”）与 daemon 存储
> 变动时才去问项目，其余时候是内存里的缓存 —— 左栏每轮轮询不会打 N 个请求。
> 因此卡片上的名字/图标是**渲染时按 id 现算**的（`cardAgent`）：项目列表与用户档案
> 是并发拉的，先到的那份不能把名字烘死成 id 缩写。
> 读不到时 `agents` 为 `null`（不能写成 `[]`，那会看起来像“这个项目没有 Agent”）；
> 想强制重读：`POST /api/v1/console/projects/{id}/agents:refresh`。

### Agent 列表窗口 `render.agentWindow`
```
[{ id, agent_id, project, task, network, online }]
```
> 行是 **(项目, Agent) 这一对**，不是 Agent：同一个 Agent 在两个项目里干活就出现两行，
> 所以 `id` 是 `项目号/Agent号`（详情窗口按它找）。
> `network` / `online` 与 Agent 管理页同一个口径（只有网络接入的才画那个右侧标记；
> 本机接入不画），见 `render.agents` 那条。
>
> 数据来自中间层的 `GET /console/agents` —— 一个 daemon 只答自己那一个项目，
> “谁在哪干活”只有中间层能汇总（它拿已有的名单缓存拼，不额外问项目）。
> **名字与图标不在数据里**：渲染时按 `agent_id` 现算（`agentDisplayName` / `agentIconFor`），
> 道理和左栏卡片一样 —— 名单、用户档案、术语 是并发拉的。
> 标题是「昵称（短号）」（静态样例就是「DeepSeek Harness（054）」），
> 短号取 `agent_id` 的**尾部**几位：ULID 前缀是接入时间戳，尾部才有区分度。
>
> `任务` 列来自任务与 Attempt 的 join（`attempts.owner_agent_id` → 任务标题，只算未结束的），
> 那部分要问 daemon，所以**只在窗口被打开时取一次**、不跟着 5 秒轮询；
> 没在干活就是空字符串（不编一句“空闲”填进去）。
> 名单读不到的项目会列在 `unreadable` 里（daemon 起着但没答）；
> 没启服务的项目压根没端点，不在名单里 —— 那是“未启动”，不是“读不到”。

### 7.1 添加一个 Agent（中间层准备申请，页面负责等）
「添加子 Agent」窗口的名称是昵称。前端提交的项目、角色、昵称是本次接入的选择，不从 Agent 当前目录或提示词重新推断。

```text
POST /console/projects/{project}/agents:prepare   {vendor, nickname, role, profile?, start_daemon}
   → {status:'prepared', enrollment_id, profile, nickname,
      host_registration:{status,label,name,commands,note}, next, …}
GET  /console/enrollments/{enrollment_id}
   → {status:'waiting'|'arrived'|'expired'|'cancelled', phase?, agent_id?, note?, …}
GET  /console/enrollments/current
   → 当前申请的公共状态，或 {status:'none'}
POST /console/enrollments/{enrollment_id}:cancel
   → {status:'cancelled', …}，或 409（已开始接入，不能取消）
```

- **Codex 先准备申请**：`host_registration.status=deferred` 是正常等待，不是注册失败。中间层此时不签票、不生成虚拟聊天、不写独立 MCP。用户在目标 Codex 当前对话中只说 **“请接入 Tsunagou”**，Skill 执行 `tsunagou agent join`，由程序读取申请中的项目/角色并核验真实聊天身份。遮罩不再要求输入目录、声明主/子身份或在指定目录重开窗口。
- **唯一申请与同会话重试**：同机、同 OS 用户在所有项目和控制台间只有一个有效 Codex 申请。记录保存在私有的 `~/.tsunagou/console-enrollments`，按 `enrollment_id` 独立查询并跨重启保存。并发认领只有一个聊天成功；认领后的失败保留归属，由原聊天重试，不自动变成新 Agent。没有申请就报错，不新建项目。
- **等待进度**：每 2 秒查询一次。Codex 的 `waiting` 带 `phase=pending|connecting|enrolled|failed`，分别表示等待认领、认领后接入中、已登记但未取得原会话确认、可由原聊天重试的失败。`joiningNote()` 优先显示后端 `note`；旧宿主的 `pending.missing_admission` 仅作兼容提示，不再承诺“再读一次上下文就能完成”。
- **严格完成**：页面只在后端返回 `arrived` 后报成功。Codex 中间层须同时核对本次绑定的 Agent/会话、项目、角色与就绪状态，以及原聊天成功调用 `context__project_read` 的回执。名单里多出一个人、辅助进程查询成功或另一个 Agent 就绪都不能完成这次等待。
- **刷新恢复**：启动全局数据与上次所选项目恢复后，查询 `enrollmentCurrent`，使用原 `enrollment_id` 重接等待和取消，绝不再次 prepare。遮罩一直标明原项目与角色；即使当前选了别的项目也不自动切换。完成只刷新全局名单和匹配的当前项目数据，不推进已经丢失的旧向导。同项目/角色重复 prepare 复用原记录和昵称；其他选择的 409 显示 `detail.enrollment` 的项目/角色与 `detail.note`，停在原步骤。仅允许一个页面等待流程，避免初始化查询与用户点击并发重复轮询。
- **取消等待**：`notify.loading(text, {cancel: fn})` 使原有入口出现；点击仍用现有 `dialog.confirm` 二次确认。拒绝确认保留取消入口；确认后等待后端结果。未认领的 Codex 申请可取消，已认领/登记返回 409，页面显示原因并继续等，不报告“已取消”，也不注销共享 MCP 或已接入 Agent。准备请求未完成时点击取消，会等取到申请 ID 再发取消请求。其他宿主保留自己的撤票/注销流程。
- **关闭遮罩与取消申请不同**：遮罩被其他操作关闭只停止本次页面轮询，不能据此声称申请已作废。未认领申请过期后需重新准备；认领后的接入不因准备期限到时自动换人。
- **首次加载边界**：Codex 需预先安装接入 Skill；共享 MCP 第一次配置后若原聊天还没有工具，可能需要重开宿主。已经加载的共享 bridge 每次调用读当前路由，后续 Agent 不需要反复重建全部 MCP。
- **其余宿主看 `mode`**：`mode=console` 才是"页面能办完"，可以发准备请求；`mode=in_host` 表示只能在这个宿主自己的聊天里接入（页面照实说那句 `note`，不发请求）；`mode=unsupported` 表示还没做（同样照实说、不发请求）。`registered` 表示已登记，页面**照抄后端 `next`** 作为等待提示（OpenCode 的 `next` 里带着要用的会话名），没有 `next` 才退回"打开/重载窗口"那句通用提示。`executable_missing|failed` 则按 `host_registration.note` 进入手动接入提示。`profile` 是显示/私有材料标签，不是聊天身份；重试保留它。票据仍只在服务端私有文件，页面永远拿不到 secret。

### 7.2 宿主表：哪个厂商能接入、跑什么命令（表在中间层）
协议里的值一旦要显示给人看，页面就得有一份词表（§7.3）。宿主也一样：
“Codex 怎么注册、Claude Code 支不支持”只有一份事实，在
`src/tsunagou/platform/host_registration.py`（一张表，一个厂商一行），经 `GET /console/hosts` 送到页面。

- 页面**不维护第二份厂商表**：`hostFor(vendor)` 拿界面上选的厂商名（或 adapter 名）去这张表里对上，
  点下一步会不会发准备请求，由表里的 `mode` 决定。
- 加一个厂商 = 加一行（写它的可执行文件探测 + 注册命令，或注明它只能在宿主里接入），前端与接口都不用改。
- 三态：`console`（页面能办完，发请求）、`in_host`（只能在这个宿主自己的聊天里接入，照实说 `note`）、
  `unsupported`（还没做，照实说 `note`）。后两种都由 `hostEnrollBlocker()` 在"下一步"处挡住：
  `in_host` 给指路提示，`unsupported` 报错；两种都**不发请求、不假装排队**。

### 7.3 后端参数值的中文（词表在中间层）
协议里的值是给机器比的短英文 token（`open` / `holder_released` / `superseded`）；
界面要的是**短中文**。词表只有一份，在中间层：`src/tsunagou/console/glossary.py`，
经 `GET /console/glossary` 取回（启动时随 `projects` / `settings` 一起拉）。

- **怎么用**：`util.gloss(域, 值)` —— 命中给中文，**没命中原样返回**（宁可难看，不编）。
  域是*展示域*，不是字段名：`message_status` 是“消息那一栏读给人看的答复状态”，
  不关心是哪个出口给的。当前 22 个域：`lifecycle` `agent_status` `agent_role` `session_status`
  `task_status` `attempt_status` `lease_status` `workspace_status` `message_status`
  `obligation_status` `delivery_status` `contract_status` `decision_status`
  `discrepancy_status` `discrepancy_severity` `checkpoint_status` `isolation` `mode`
  `conflict_resolution` `capability_admission` `capability_operational` `denial_reason`。
- **其中两张表不是查一个值，而是"整栏有哪几项"**：`capability_admission`（4 项准入）与
  `capability_operational`（7 项运营）就是「Agent 管理」那两栏本身 —— 后端只说缺哪几项
  （`missing_admission` / `missing_operational`），页面上每一项叫什么、按什么顺序排，全从这两张表来
  （`BACKEND_SHAPE.agents` 用 `glossTags(域, missing)` 一下子展开成 `{text, ok}` 的一栏）。
  它们与 `shared_kernel/baseline.py` 的 11 项一一对应，改一边就得改另一边（有单测盯着）。
- **拒绝原因码**（`denial_reason`）：总路径里 `resource.acquire.denied（资源被占用:file:src/x.py）`
  括号里那句中文。码可能带参数，所以**只查冒号前那截**（`reasonText()` 干这件事），
  查不到就把整串原样写出来 —— 宁可难看，也不编一个中文。
- **两条纪律**：
  1. **只用在显示处**。判断逻辑一律拿原值（`status === 'active'`、`w.status !== 'failed'`）——
     中间层不翻译数据本身，转发出去的响应体一个字节都没改，否则页面自己就没法比了；
  2. **词要短**：「已答复」不写成「已经得到答复」，「等待中」不写成「正在等待中」；
     实在压不下去的（如「重试后拿到」）就保留。
- 已有几处中文文案**不在**词表里，因为它们是界面自己的状态机，不是后端 token 的翻译：
  左栏卡片的「进行中/未启动/已完成/已归档/演示中」、任务徽章的文字（CSS `.st-N` 的 `::after`）。
  任务表那个徽章用的是类名，所以 `task_status` 这一域目前只供详情/别处要用文字时取。

### 主视图 `render.overview`
```
{ name, description,
  basics:   [{label, value, active}],          // active=true 时值用高亮色
  progress: { total:'12%', plan:[{text, state:'done'|'doing'|'todo'}] },
  versions: [{label, value}],
  stats:    [{label, value}],
  storage:  [{label, value}] }
```

### Agent 管理 `render.agents`
```
{ id, role:'主 Agent'|'子 Agent', name, icon, statusText, statusOk,
  desc, currentTask, network, online,
  basic: [{text, ok}], ops: [{text, ok}],
  actions: [{text, kind:'active'|'', action}] }   // action 为空则是纯占位按钮
```
> **右上角那句「网络在线 / 网络离线」（跨机器协作，2026-10-02）**：只有**网络接入**的 Agent
> 才画 （`network:true`），`online` 定在线还是离线；**本机接入的什么都不画** —— 连右边那个
> `<i>` 图标也不出现，所以本机接入的卡片和加这个功能之前一模一样。
> 主 Agent 永远不算网络接入（它必须与 daemon 同机）。判断值来自接口字段，或中间层随时推的
> `app.setAgentNetwork(id, online)` / dispatch `agent.network`（推来的优先），见 §3.7。
> `basic` / `ops` 是 `agents` 出口里那 11 项能力的现场快照（`session_status` +
> `missing_admission` / `missing_operational` + 词表两栏，见 §7.3）。`ok:true` 用 `.tagZOK`（勾），
> 否则 `.tagZ`（灰杠）。**读不到会话（那三个字段是 null）时两栏都返回空数组**，
> 页面就不画 —— 不把"不知道"画成"都没有"。没有活动会话的 Agent（与 `status` 无关）走的就是这一支。
>
> **「当前状态」那一格分两层写，说话的是会话**：`session_status` 是 `degraded` / `ended` 时写
> 会话那一层（词表 `session_status`：「降级中」/「已结束」，灰），其余时候还是席位那一层
> （词表 `agent_status`：可用 / 接入中 / 已退役）——**座位还在不等于会话能干活**，
> 而 "座位可用但会话已经不能干活" 正是降级。没有会话（`session_status` 为 null）、或会话 `ready` 时，
> 界面口径不变（仍旧只看 `agent.status`）。

### 任务区 `render.tasks`
```
{ id, title, detail, status: 1..13, agent, time,
  conditions: [{text, ok}, ...], scope }
```
> **开工条件**回答的是"**现在**具备哪几件"，不是"任务要求哪几件"（任务自己声明的
> `preconditions` 后端没落库）：四件 = 认知报告（`cognition.reports` 里有这个任务）
> / 契约（有 `payload.task_id` 指向它的契约提案）/ 工作空间（它的 attempt 有工作区）
> / 租约（它的 attempt 有 `active` 租约）。**四件都画**，有就 `.tagZOK`、没有就 `.tagZ`。
>
> **改动范围** = 这个任务的**活跃**租约涉及的资源键之和（真出口给的是 `repo:x/**` 这种
> 资源键字符串；旧演示数据里的 `{key,mode}` 也认）；一条活跃租约都没有时退回任务自己声明的
> `execution_scope`；另外还有过期的租约时，末尾补一句「（另有 N 条租约已过期）」，不把它们混进范围里。
> `status` 直接对应 CSS 的 13 个任务状态，文字由 CSS 生成，不用传：
> 1 草稿 · 2 已就绪 · 3 待认领 · 4 已认领 · 5 执行中 · 6 卡住了 · 7 待验收 ·
> 8 被打回 · 9 取消中 · 10 执行者丢失 · 11 已完成 · 12 失败 · 13 已取消
>
> 这一串号是**照 `style.css` 的 `::after` 文案数的**（CSS 只认类名，文字全在它那儿）。
> JS 的 `TASK_STATUS_NUMBER` 必须照这个顺序排 —— **2026-09-29 修过一处错位**：原来那份表
> 从 `submitted` 起就按"后端自己的枚举顺序"排，结果是 `submitted` 显示成「卡住了」、
> `blocked` 显示成「取消中」、`cancel_requested` 显示成「已完成」…… 演示数据里就看得见。
>
> **「负责 Agent」那一格下面的小字是当前 attempt 什么时候开的工**：任务自己**没有时间字段**，
> 时间挂在 Attempt 上（`attempts` 出口的 `started_at`，**epoch 秒**）——这一格从同一次视图里
> 拖的那个出口取，`epochSecondsTime()` 把秒换成时间；没开工过的 attempt 没有值，就不画那一行。

### 冲突与协商 `render.conflicts`
```
{ dissents:   [{id, title, agents:[], time, scope,
                understandings:[{agent, text}], actions:[{text,kind,action}]}],
  conflicts:  [{id, title, detail, scope, agents:[], time, solution}],
  messages:   [{id, from, to, content, answered, answeredOk, progress:[{text,ok}]}],
  contracts:  [{id, title, time, proposers:[], scope, text, confirmed:[], unconfirmed:[], action}] }
```
> 「状态」那一格读 `m.status`（词表 `message_status`：已答复 / 等待中 / 无需答复 / 未知），
> 「消息处理情况」那几颗标签读 `m.obligations[].status`（词表 `obligation_status`）。
> **这两个字段是 daemon 在 `messages` 出口里给的**（2026-09-29 接通）：消息本身没有 status，
> 它只有一条投递记录 + 发件方要了答复时才有的回应义务，所以判决在出口里派生
> （`bootstrap/container.py` 的 `message_status()`：没有义务 → `none`；有 `open` → `pending`；
> 其余 → `answered`）。页面不自己从一个空数组里猜“没人欠答复”。
> 四个子标签各自对应 `#aside-conflict` 里的一段：分歧 → 第 1 段，契约 → 第 2 段，
> 冲突 → 第 3 段，Agent 间协商 → 第 4 段（见 §4.3）。

### 意图与权限审计 `render.audit`
```
{ intents: [{id, agent, target, mode, reason, version, lease:{text, ok}}],
  leases:  [{id, agent, scope, version, lease:{text, ok}}] }
```
> 原来的 `waiting`（等待租约的 Agent）已按决定 11 砍掉：daemon 没把等待队列做成出口。
> 租约冲突账本不在这里 —— 它在「冲突与协商 → 冲突」那一栏（形状就是上面 `render.conflicts` 的 `conflicts`）。

### 工作区 `render.workspaces`
`[{ id, name, agent, isolation, files:[字符串或带\n的整段], states:[{text,ok}], patch }]`

### 验收与存档点 `render.acceptance`（slug 仍是 `acceptance`）
```
{ proposal: {title, time, text, actions:[{text,kind,action}]},   /* actions 里只有「确认完成」 */
  taskResults: [{agent, task, result, reviewed, decision, round, reviewer, reason}] }
```
> 这一屏是**三件事一条链**：主 Agent 提收尾（段 1，卡上的「确认完成」走 `project.completion.confirm`）、
> 任务级的交与验（段 2）、收尾一确认就落成一个存档点（段 3）。
> 所以它同时读三份数据：`acceptance` / `checkpoints` / `checkpointFailures`（后两份从 state 取）。
> 段 2 的结论来自 **`reviews` 出口**（`task.review.*` 写的轮次，最高轮次为准）：没验过就写“还没验收”，
> "已提交 <摘要>" 只当次要一行 —— 不能拿提交充当通过。
> 已删掉的东西：遗留问题（前端从 tasks 推算的）、验收标准（后端没这个概念，恒空）、
> 侧栏「详细信息」（只读那个恒空的 standards，所以永远白板）、「忽略」（纯本地假动作）、「归档」（死按钮）。

### 存档点三段（同一屏里） / 总路径 `render.timeline`
```
checkpoints: { latest:[{id,title,time,reason}], history:[{id,title,time,reason}] }
checkpointFailures: { items:[{id,time,reason,error,attempts}] }
timeline:    [{ era:'初始化 · 9月26日18:41:17 – 23:41:17',
                items:[{id, at, time, timePrecise,
                        actor:{ref, name, id?, icon?, user?, mainAgent?}, task, action}] }]
```
> `actor` 里给 `user:true` 就用用户图标代替头像，`mainAgent:true` 加主 Agent 的配色类。
> 存档点这一屏要两份数据：存档点本身（`checkpoints`）与“没存成”的记账（`checkpointFailures`），
> 后者是**另一个出口** —— 没存成的存档从来没产出 manifest，所以不可能出现在存档点列表里。
> 卡片上的 `title` 由适配层拼（`存档点 <摘要前8位>（已校验）`），摘要要先去掉 `sha256:` 前缀。
> 行里的 `actor` 只是**适配那一刻**算的，渲染时按 `actor.ref` 再算一遗
> （总路径与 `agents` 出口是并发拉的，谁先回来不定）。
>
> **「任务」那一列写标题，不写 id**：`subject_ref` 是 `类别/<id>` 的形状，`task/<id>`
> 在任务名单里找得到就写任务标题、`project/<id>` 找到就写项目名；找不到（跨代、别的项目、
> 任务已不在名单里，或本来就是指向 Agent 的裸 id）才退回 id 缩写 —— 对得上时别拿 id 糊人，
> 对不上时也不编一个名字。**「操作」那一列**在动作名后面的括号里补一句"为什么被拒"
> （`reason_code` 经 `denial_reason` 词表，只查冒号前那截；没有原因码就不加括号）。
>
> **会话事件再补一句"当时缺什么"**：审计行上还有两个字段 `session_status` 与
> `missing_admission`，但**只有做会话判定的命令才带**（`agent.enroll` / `session.rebind` /
> `session.reconnect`，出口在结果里有 `baseline_status` 时才记）；别的行动一律是 `null` / `[]`。
> 于是 `agent.enroll（降级：缺 身份续接）`、`session.reconnect（已恢复：能力全通过）`
> 这么写：降级写缺的项（能力名经 `capability_admission` / `capability_operational` 两栏词表），
> 通过写"能力全通过"（第一次入会话是「已就绪」，重接/重连是「已恢复」——同一个人再进来才叫恢复）。
> 老事件没有这两个字段，就不补、也不猜。

**总路径的阶段**（蓝条上的字）：协议里没有"阶段"这个字段，它是展示口径 ——
把行动按发生先后排好，命中里程碑就进入下一段。

| 阶段 | 从哪条行动开始 |
|---|---|
| 初始化 | 起点（不必命中任何行动） |
| 正式开工 | 第一条 `task.publish` / `task.claim` / `task.start` |
| 开始总验收 | 第一份 `project.completion.propose.*` |
| 结束 | `project.completion.confirm` 或 `project.archive` |

- 两条例外：`project.reactivate.*` 让阶段**退回**"正式开工"（结束后又复工，会如实再出现一段）；
  `*.denied` 不算里程碑（没通过的 `task.publish` 不能假装已开工）。
- 顺序：真后端给的是 `event_seq` 升序，**原样显示** —— 从上到下就是从"一开始"排到"最后"，
  最早的那一段（初始化）在最上面；段内同样是先发生的在上。
- 只有出现过的阶段才有蓝条：还没收尾的项目就只有"初始化 / 正式开工"两条。
- 蓝条后面跟这一段的起止时间（同一天只写一次日期）。

### 侧栏详情
各侧栏的详情由点击对象的字段直接渲染（例如任务行的详情就取这一行本身）；
后端另外想发额外详情时可以 `dispatch('task.detail', {id, report, …})`，
点这条任务时它会合并进去（**只在 id 对得上时合并**，不会把别的项目的详情串进来说）。
其余侧栏同样可以直接调 `render.dissentDetail` / `render.contractDetail` /
`render.conflictDetail` / `render.messageDetail` /
`render.intentDetail` / `render.leaseDetail` / `render.workspaceDetail` /
`render.acceptanceDetail` / `render.pathDetail`，然后 `ui.aside.show(slug, 段号)`。

> 启动时会调一次 `ui.aside.clearAll()`：把 `index.html` 里那些占位文案清掉，
> 避免出现“没被填过就露出旧文字”的情况。

---

## 8. 事件表（前端 → 后端）

用 `Tsunagou.events.on(name, fn)` 订阅；启动时 `init()` 会依次绑好所有委托。

| 事件 | detail | 何时 |
|---|---|---|
| `ready` | `{version}` | 初始化完成 |
| `ui:tab` | `{slug, index}` | 切主导航标签 |
| `ui:blocktab` | `{block, index}` | 切区块内子标签 |
| `ui:aside` | `{slug, visible, section?}` | 侧栏显隐 |
| `ui:window` | `{id, open}` | 窗口开/关 |
| `ui:workspace` / `ui:sidebar` / `ui:settingtab` / `ui:wizard` / `ui:choosebox` | 相应上下文 | 对应控件变化 |
| `form:commit` | `{input, key, value, previous, window, label}` | input 失焦提交（核心事件） |
| `form:submit` | `{window, values, valuesList}` | 点主按钮提交整表单 |
| `api:success` / `api:error` | `{method, url, data\|error}` | 请求结果 |
| `state:change` / `state:reset` | `{reason, path, value?}` | 数据变化 |
| `config:change` | 当前配置快照 | `setBaseUrl` / `setPath` 等改了配置 |
| `theme:change` | `{mode, resolved:'dark'|'light'}` | 主题切换 |
| `render:all` | `null` | 整页重绘完成 |
| `action:request` | `{name, id}` | 点了没注册处理函数的动作（后端可以在这里兜底） |
| `dispatch:error` | `{type, error}` | dispatch 收到未知类型或抛错 |
| `project:open` / `project:select` / `agent:select` | `{id}` | 进项目 / 卡片选中 / 点 Agent |

---

## 9. DOM 契约（`index.html` 里新增的 id）

| id | 位置 |
|---|---|
| `#projList` | 左栏"协作项目列表"容器 |
| `#tab-<slug>` ×9 | 项目标签按钮 |
| `#pane-<slug>` ×9 | 项目主视图面板 |
| `#aside-<slug>` ×6 | 右侧侧栏（原来都是重复的 `asideMainProj`，已改成唯一 id） |
| `#block-conflict` / `#block-audit` | 两个区块标签组的容器 |
| `#uSetCol1` | 设置里"颜色主题"的下拉面板（原来叫 `uSetCol`；重复 id 已拆开） |
| `#newXz2Vendor` / `#addSubAgentVendor` | 向导第 2 步 / 添加子 Agent 的"厂商"下拉面板（**不能重复用 `uSetCol2`**，否则选择框事件会串台） |

> `#aside-conflict` 里有 4 段 `.content`：分歧 / 契约 / 冲突 / Agent 间协商；
> 后三段带 `.contentNDP`（CSS 里默认隐藏），由 `ui.aside.load(slug, 段号)` 互斥切换。

`<slug>` 取值：`overview` 主视图 · `agents` Agent 管理 · `tasks` 任务区 ·
`conflict` 冲突与协商 · `audit` 意图与权限审计 · `workspace` 工作区 · `acceptance` 验收与存档点 ·
`path` 总路径

窗口 id：`setPanel` `mgrAgent` `mgrAgentInfo` `delPmt` `addProj` `addSubAgent` `loadW`（`delDat` 已删）；
反馈组件 id：`AnnounceMent`(+`secApgr`) `AnnounceMent2` `rightGetWin`。

**渲染器可用的类名词汇表**（都来自现有 CSS，不要再自造）：
`.emptybox`（空状态占位）、
`.boxerbox > .item/.itemL/.itemAdd`、`.tablebox > .th/.tr > .colu(.colu-l/.colu-m/.colu-cdt) > .citem1/.citem2/.citem3`、
`.table > .item > .itemTh/.itemTd(.itemTdActive)`、`.tags`→`.tagZ(.tagZOK/.tagZS)`、
`.listfieldbox > .item(.itemS/.itemC/.itemJ)`、`.st.st-1…13`、`.title/.title2/.title3/.bgTxt/.textArea/.textZ/.textZbox/.textN/.textTime/.bgTitle`、
`.option > .buttonbox2(.buttonbox2active/.buttonbox2important)`、`.buttonbox`、`.uiBlock`（其内 `>.title2` 当标签、`>.dspText` 当长文本值）、`.textbox/.textbox2 > input`。

---

## 10. 本次改动清单

**`index.html`**（只动了 `id` 与 `onclick` 两个属性，结构与文案未动）
- 新增 §9 里列出的所有 id（含把 7 个重复 id、2 个重复 id 改成唯一）。
- 43 处 `onclick` 全部改名为 `Tsunagou.app.*`，映射关系：
  `openWindow(x)`→`app.openWindow(x)` / `closeWindow(x)`→`app.closeWindow(x)`、
  `openProj()`→`app.openProject()`、`sidebarToNarrow/Wide()`→`app.foldSidebar()/unfoldSidebar()`、
  `toSetTab('uSetN')`→`app.settingTab('personal'|'data'|'debug'|'about')`、
  `newXzNext/Prev/Finish()`→`app.wizardNext/Prev/Finish()`、
  `openWindow('addSubAgent')`→`app.addSubAgent()`、`openWindow('addProj')`→`app.createProject()`、
  `openWindow('mgrAgent')`→`app.openAgents()`、`openWindow('setPanel')`→`app.openSettings()`、
  `debug()`→`app.demo.success()`、`debug2()`→`app.demo.info()`、
  `openWindow('loadW')`→`app.demo.loading()`、`openTST()`→`app.demo.decision()`。
- 新增一行 `<script src="./assets/js/mock-backend.js">`（模拟后端，接真后端时删掉）。
- 去掉 `#addSubAgent` “确定”按钮的内联关窗：改由 JS 提交成功后再关，
  这样校验不过时窗口会留在原地。（`#mgrAgentInfo` 的“确定”相反：那个窗口当时只展示、
  没有可提交的东西，那两个输入是 `readonly`，“确定”内联关窗；2026-09-28 起昵称可改、“确定”= 保存，
  见 §4.4 与 §11。）

**新增文件**
- `assets/js/mock-backend.js` —— 模拟后端（拦 `fetch`，两个完整协作项目的写死数据）。
- `备份20260925/` —— 接模拟后端之前的整份备份（含 `index.html` / `method.md` / `assets/js/behavior.js`）。

**`assets/js/behavior.js`**：整文件重写（旧版备份在 `%TEMP%\tsunagou-behavior-legacy-20260925.js`）。
**`assets/css/*`**：未改动。

> 2026-09-29 更新：`assets/js/mock-backend.js` 与 `index.html` 里那一行 script 都已删除，
> 页面不再有“演示后端”（见 §6.1）。本节其余内容是当时的迁移记录，按历史保留。

**已补齐的逻辑缺陷**
- Agent 管理页那个大加号（`.itemAdd`）现在会打开「添加子 Agent」；向导第 3 步的小加号同样有效。
- 冲突「查看协商/查看契约/查看详情」、验收「确认完成」、存档点「立即存档/校验/重试」、
  存档点「重试」—— 全部接成"确认 → 请求 → 提示 → 局部重绘"。
- 死代码 `mgrAgentDB()` / `mgrAgentDDB()`、僵尸窗口逻辑已随重写消失；
  `#delPmt` 现在是通用的二次确认框，能被真正打开。

**收尾复查（第二轮）又修掉的三处**
1. **`#addSubAgent` 的结果串了页面**：这个窗口有两个入口，提交后却一律写进向导草稿 ——
   从 Agent 管理页添加的子 Agent 在界面上完全看不到（只弹一条提示），还顺手污染了向导草稿。
   现在按来源分流（见 §3.7 的 `source`）。
2. **`init()` 里的 `state.reset()` 会冲掉启动前的数据**：改成 `state.hydrate()`
   （补骨架、不覆盖已有值），宿主脚本在 `init` 之前 `dispatch` 过的数据不会再被清掉。
3. **`app.addSubAgent({source})` 只传 `source` 时会清空输入框**：回填改成"真给了名字/地址才写"。

**复查时确认过、没有问题的**：全部 41 处 `onclick` 都能解析到实际存在的函数；
43 个 dispatch 类型全部可用；7 个侧栏的 7 类内容点击都能唤出对应侧栏并填上数据；
向导四步（校验/探测/加子 Agent/核对/提交）通畅；11 个主视图面板全都有渲染器且无空面板；
未注册的动作/未定义的窗口都不会静默失败（前者走 `action:request`，后者返回 `null`）。

**给「冲突与协商」补齐另外两个子标签的侧栏**（`index.html` + `behavior.js`）
- 原来只有「分歧」和「契约」有侧栏；「冲突」和「Agent 间协商」点行**毫无反应** ——
  既没有 HTML 段，也没有点击绑定（`bindContentClicks` 里 `#pane-conflict` 只匹配卡片 `.boxerbox > .item`，
  而这两个子标签渲染出的是表格行 `.tablebox .tr`）。
- 现在 `#aside-conflict` 有 4 段：分歧（第 1 段）/ 契约（第 2 段）/ 冲突（第 3 段）/ Agent 间协商（第 4 段），
  新段沿用同一套小件（`.bgTitle` / `.title` / `.textN` / `.listfieldbox` / `.tagZ`）与 `.contentNDP` 互斥机制。
- 新增 `render.conflictDetail`（描述 / 影响范围 / 相关 Agent / 时间 / 处理方案）与
  `render.messageDetail`（发件 Agent / 收件 Agent / 内容 / 状态 / 消息处理情况），字段来自主面板那一行。
- `bindContentClicks` 补了 `#pane-conflict .tabContent .tablebox .tr` 的处理。

**接入 `emptybox` 空状态**（只改 `behavior.js`）
- 三个通用小件内脏判断：`tableBoxHtml`（表头后跟一个）、`boxerHtml`、`keyValueTableHtml`；
  另外单独处理的：`render.timeline`（`.taskFlow`）、`render.list`（左栏）、
  `render.agents`（与加号并存）、`render.acceptance`（提案/存档卡里没字也算空）、
  `render.agentWindow`（Agent 列表窗口）、`render.aside`（传空字段数组时）。
- `ui.aside.show()` 里多一步 `fillAsideEmpty()`：要显示的那一段没被任何渲染器填过时补一个，
  免得露出"只有标题栏"的空壳。**它必须在 `revealEl` 之后调** —— `isShown` 会看祖先 display，
  侧栏还藏着的时候判断不出来。
- 主视图整体没数据时只给一个空状态，不是五个（见 §4.2）。

**2026-09-27 增补（AI 协助；只改 `behavior.js` 与本文）**
- **向导第 2 步 / 添加子 Agent 的"厂商"改成选择框**：Agent 字段由 `api`（API 地址）改为 `vendor`
  （`Claude Code` / `DeepSeek Harness` / `Codex`），图标按文字映射（`agentIconFor()`）。
  `DEFAULT_PATHS.detectAgent` 与 `GET /agents/detect` 一并删除——后端没有"Agent 地址"这个概念。
- **下拉面板的定位与尺寸由 JS 管**：展开时与选择框等宽、对齐其右边缘、贴框正下方；
  窗口缩放或滚动容器滚动时跟随；收起时清掉行内 `width/left/top`。
  设置窗口的面板有定位祖先，不参与（位置与尺寸仍归 CSS）。
- **"调度数据管理"页删除**（保存地址 / 协作记录自动清空 / 抹除全部数据）：该设计与后端的
  "领域历史永久保存"直接冲突。JS 侧同步清掉 `SETTING_TABS.data`、`ui.settingTabs.data()`、
  `render.settings` 的对应分支、`actions.wipeAllData`、`WRITE_COMMANDS.dataWipe`、`#delDat` 的提交绑定、
  `state.settings.savePath/clearDays`；`#delDat` 窗口本体也已从 `index.html` 删除。
- **左栏协作卡片的"编辑"入口删除**：卡片模板不再生成 `<span class="edit"></span>`（`projectCardHtml`），
  `bindProjectCards` 的 `.edit` 分支、`app.editProject()` 与 `project:edit` 事件一并移除 ——
  现在点卡片就是"选中并进入项目"。
- **不再有"创建 Agent"的写路径**：`actions.addAgent`（发 `agentCreate`）删除。
  `WRITE_COMMANDS` 里的 `agentCreate` / `subAgentCreate` 两个键一并删除。
  （当时 `addSubAgent` 还只发一条提示；现在它走真接入，见 §7.1 与 §12 的记录。）

**2026-09-28：「我的收件箱」整页删除（只改 `index.html` 与 `behavior.js`，CSS 未动）**

- **为什么删**：这个页面的定位是"把需要用户处置的事集中起来"，但**消息通道里用户没有处置权** ——
  `message.send` / `message.respond` / `message.waive_response` / `inbox.ack` **全部是 Agent 权限**，
  "豁免回应义务"还只允许原发件人。而真正会**拦住等人**的用户介入路径只剩两条（用户决定、项目完成确认），
  其中"完成确认"已经在「验收与存档点」页里（2026-09-29 由「项目验收」合并而来）。留一个长期接近空的页面不划算。
- **删掉的东西**：
  - HTML：`#tab-inbox`、`#pane-inbox`、`#aside-inbox`；
  - JS：`PROJECT_TABS` / `ASIDE_SLUGS` / `DEFAULT_PATHS.inbox` / `WRITE_COMMANDS.inboxHandle|inboxRevoke` /
    `EMPTY_STATE.inbox` / `render.inbox` / `render.inboxDetail` / `actions.moveInbox|inboxHandle|inboxRevoke` /
    `openMessageTarget` / `DETAIL_VIEWS.inbox` / `dispatch('inbox.list')` / `REFRESH_ROUTES` 里那一项 /
    `bindContentClicks` 里 `#pane-inbox` 的点击分支 / `inbox:open` 事件。
- **标签页 10 → 9、侧栏 7 → 6**。⚠️ **按序号**调 `ui.tabs.project(n)` 的调用方要留意序号整体前移。
- **`assets/css/*` 未动**：与收件箱相关的 CSS 规则仍在，只是不再有元素用到它们（可接受的死样式）。
- **要恢复**：`备份20260926/` 里有删除前的整份前端。

---

## 11. 已知限制 / 待你决定

| 项 | 说明 |
|---|---|
| Agent 卡片上的三个按钮 | 2026-09-28 定稿：**「修改」真能用**（开详情窗口改昵称，存中间层用户档案）、**「设为主 Agent」真能用**（`authority.appoint`；主 Agent 自己的卡片不显示它）；**「删除」= 暂不实现**，点了只弹「撤回功能当前尚未实现」。按钮由 `agents[].actions[]` 驱动：后端在那一项里给 `action` 就出现（可用名：`agent.setMain:<id>` / `agent.edit:<id>` / `agent.remove:<id>`，未注册的名字会以 `action:request` 事件抛给宿主兜底）。 |
| 「改昵称」的两个入口 | Agent 管理卡片上的「修改」→ `app.editAgent(id)`；Agent 列表里点某一行 → `app.openAgentInfo(id)`。两者开的是**同一个** `#mgrAgentInfo`：昵称可改，项目/任务只读，**不列厂商那一栏**（logo 已经标出厂商）。窗口「确定」= 保存昵称（值没变就只关窗，不发请求）。 |
| 向导的「上一步」与子 Agent 的「×」 | **暂不实现**（2026-09-28 你定）：按钮留着，点了只弹「撤回功能当前尚未实现」。理由：上一步想做的事 = 撤回上一步的效果，而分步后撤不在本轮范围内（子 Agent 那个 `×` 是 CSS 画的 `.itemC::before`，点它就是"删掉这个 Agent"）。低层导航 `ui.wizard.prev()` 仍在，只是页面按钮不再用它。 |
| 「添加子 Agent」的两个入口 | 已区分：两个入口都走同一条真接入（见 §7.1），只是收尾不同 —— 向导第 3 步的小加号把结果记进向导第 3 步的列表；Agent 管理页的大加号成功后重拉名单/卡片/昵称。 |
| 向导第 2 步的"你所选的 Agent" | 厂商由选择框决定（**默认 Codex**，见 §3.4 的“表单清空时回到哪一项”）；这个预览框显示的是**你在名称输入框里填的 Agent 名字**（图标才是厂商），名字为空就留空。**不再有 `GET /agents/detect` 探测请求**（后端没有"Agent 地址"这个概念）。<br>**整块（标签 + 预览框）的显隐**：名字与厂商**两样都给了才显示**，否则一块空板子不占位置（`actions.detectMainAgent()` 里顺带定，只动 `display`）。 |
| 向导遇到接不了的宿主 | **Codex 与 OpenCode** 能从网页接入（表在中间层：`mode=console` 才是"页面能办完"）。**DeepSeek Harness 属 `in_host`**：它只能在它自己的桌面聊天里接入，页面把这句话（后端 `note`）照实说给人，不发准备请求。**Claude Code / ZCode 是 `unsupported`**：选了点"下一步"会**报错**并停在第 2 步（项目已经在第 1 步建好了，不会白费）。宿主 CLI 不在 PATH、注册命令执行失败同理。OpenCode 注册完要在那边**用页面给的会话名开会话**（`opencode --session <名字>`）并 reload 一次，配置才生效 —— 等待提示就是后端 `next` 那句话 |
| 删除协作 | 左栏卡片右上角的 `.edit`（hover 才露出来）→ `dialog.confirm` → `POST /console/projects/{id}:forget`。中间的 daemon / 宿主登记 / 票 / 索引条目 / 目录一起清；登记进来的外部项目只注销登记、保留目录 |
| 没有“返回初始工作区”的界面入口 | `Tsunagou.app.openHome()` / `dispatch('ui.workspace.home')` 都已就绪，但**页面上没有入口——这是原设计就没做的按钮，属于你的设计范围**，需要时自己加一个（我这侧不自行添加元素）。 |
| 错误提示的颜色 | 成功与失败用的是同一个品牌色（CSS `--brand-col`），目前只靠图标/文案区分。要有独立配色就得加 CSS。 |
| 浅色模式的黑洞 | CSS 里几处硬编码 `white`（如设置窗口的"颜色设置"标题、`.agentbox .right`、`.freebox .title`、`.mainAgent p`）在浅色背景下不可见 —— 不改 CSS 无解。 |
| 窄窗口下标签条竖排换行 | CSS 层问题（`.tabS` 的 `flex-shrink` / `white-space`），JS 未干预；需要的话你自己加两行 CSS。 |
| ~~演示数据~~ | **已移到模拟后端**：`behavior.js` 里只剩一份空骨架 `EMPTY_STATE`（页面内容一律由后端给）。 |
| 项目作用域 | 切换协作 = 重新拉十个项目接口；左栏列表是全局的，切项目时只重绘本地选中态，不重新请求。 |
| 写操作的乐观更新 | 验收完成后前端会先改本地 state 再重绘（不等重新拉取）；真后端如果返回不一致，以刷新为准。 |
| dispatch 的数据容错 | 类型不匹配（例如 `task.list` 收到字符串）不会抛错，会渲染出空行；严格校验需要额外约定。 |
| 主视图的 `.st` 状态色 | 任务状态的 13 个中文名与颜色都写在 CSS 里，JS 只给 `st-<n>` 类名 —— 想改文案请改 CSS（我不动）。 |

---

## 12. 中间层接线（2026-09-28）

2026-10-02 更新：Codex 改为前端保存唯一待认领申请，原聊天一句“请接入 Tsunagou”执行 `agent join`。`deferred` 正常等待；遮罩优先显示后端 `note`，只认精确身份和原会话回执的 `arrived`。取消请求被 409 拒绝时继续等待，不注销共享 MCP。以下 2026-10-01 的目录提示、提前签票/注册描述是历史记录，Codex 当前契约以 §7.1 为准；OpenCode 保持原流程。HTML/CSS 未改。

> 2026-09-29 注：本节及其子节里提到的“演示数据 / `mock-backend.js`”是当时的做法，
> 那个文件与 `--demo` 开关都已删除（见 §6.1）；`Tsunagou 前端/` 也已并入 `web/`。
> 以下按日期保留原记录。

本日把页面从"演示后端"接到了"中间层 + daemon"。这一节是那次接线的真实记录；
上面 §5 / §6 的表已按接线后的实际路径改过，以它们为准。

### 12.1 页面现在是这么跑的

```
浏览器 ──同源──> tsunagou web start ──带控制令牌──> 各项目的 daemon
                 (src/tsunagou/console)      （一个 daemon 服务一个项目）
```

- **令牌只留服务端**：daemon 的 `control.token` 由中间层读取并注入 `Authorization: Bearer`，
  页面永远拿不到它（所以页面不需要 `config.setToken()`）。
- **同源**：页面、`/api/v1/*`、`/console.config.js` 都来自同一个地址，没有 CORS。
- **页面怎么知道自己连哪儿**：`index.html` 在 `behavior.js` 之前引了 `console.config.js`（铁律：不改布局）。
  - 直接双击打开页面 → 用仓库里那份（`baseUrl` + `poll_ms`）；
  - 由中间层托管 → 中间层在同一个路径上生成替换品（`baseUrl`、`poll_ms`）。
- **`Tsunagou-Project` 请求头**：项目作用域的路径里已经有 id，但 `/commands/*`、`/decisions`、
  `/checkpoints` 这类路由没有，所以 `api.request` 统一带一个头，中间层靠它知道这次请求属于哪个项目。
  daemon 自己会忽略这个头。
- **轮询**：`poll_ms`（默认 5000，`0` = 不轮询）只重拉 `projects / tasks / agents / project`，
  页面在后台（`document.hidden`）时不发请求。`Tsunagou.startPolling()` / `stopPolling()` 可手动控制；
  改样式时用地址栏开关更省事：`?poll_ms=0` 不自动重拉、`?shape=dag` 直接停在总路径的 DAG
  （两个都只影响本次打开，由 `applyUrlOverrides()` 在 `init()` 最开头读，比 `console.config.js` 优先）。
- **上次打开的项目**：只把项目 id 存在 `localStorage`（键 `tsunagou.console.lastProject`），
  刷新后自动接回去；不存任何协作数据。

### 12.2 一屏读多个出口：`/console/views/*`

daemon 一个查询出口只回答一类东西，而一屏往往要好几类。中间层提供四个**只搬运不解释**的聚合视图：

| 视图 | 聚合的出口 | 谁来解释 |
|---|---|---|
| `overview` | `overview` · `tasks` · `agents` · `cognition` · `checkpoints` · `decisions` | `BACKEND_SHAPE.project` |
| `tasks` | `tasks` · `attempts` · `agents` · `results` · `cognition` · `contracts` · `workspaces` · `resources` | `BACKEND_SHAPE.tasks` |
| `audit` | `intents` · `resources` · `agents` | `BACKEND_SHAPE.audits` |
| `collaboration` | `cognition` · `contracts` · `messages` · `agents` · `conflicts` | `BACKEND_SHAPE.conflicts` |
| `acceptance` | `overview` · `decisions` · `tasks` · `results` · `reviews` · `agents` | `BACKEND_SHAPE.acceptance` |

> 出口的地址规则在 `console/app.py` 的 `exit_path()`：默认是
> `/api/v1/projects/{project_id}{出口名}`，**顶层出口**则直接用 `/api/v1{出口名}`。
> 顶层出口用 `GlobalExit("/decisions")` 显式标出来 —— 现在只有 `decisions` 一个
> （它答的是这个 daemon 自己那个项目的待定项）。为什么不能硬拼：拼错的后果不是 500
> 而是 404，看上去像“这个项目没有待决定的事”；验收页的收尾提案与主视图「待用户决定」
> 就是这样静默空着的（2026-09-29 修）。

`tasks` 那一屏多拖四个出口，是为了凑齐**开工条件**（认知报告 / 契约 / 工作空间 / 租约）与
**改动范围**（活跃租约）——中间层照旧只搬运，怎么对到任务上是页面的事（见 §7）。

返回体固定是 `{project_id, view, sources:{<出口名>:<原样回答>}, missing:{<出口名>:{status,code}}, gathered_at}`。
**某个出口读不到（4xx）只让那一块留空，并在界面上写明原因**；daemon 整个不在则整屏报"未启动"。
把后端回答翻译成界面形状的活全部在 `§7 BACKEND_SHAPE`，只有那一处。

### 12.3 本轮按定稿砍掉 / 改接的东西

| 项 | 现状 |
|---|---|
| 「冲突与协商」的**冲突**子标签 | **改用它装租约冲突账本**（2026-09-28 按你的要求从「意图与权限审计」挑回来）：这一栏本来就叫冲突，四个列名（冲突/影响范围/相关 Agent/处理方案）与账本字段一一对得上，没动 CSS |
| **等待租约的 Agent** | 已删：daemon 没把等待队列做成出口，不放一个永远为空的表 |
| 建项目向导 | 语义改成「登记已有项目」/新建：`POST /projects`；`Tsunagou.app.registerProject(path)` 给宿主办调用，界面上不加控件 |
| 主题保存 | 改走中间层用户档案 `PUT /console/profile`（daemon 没有"主题"这个概念） |
| 存档点「重试」 | 接 `checkpoint.create.user` + `retry_operation_id`（已接，2026-09-28）：`durability.reconcile` 是 M 权限，控制台发会 401。**2026-09-29**：失败那条记账现在有出口了（`checkpoint-failures`），所以按钮终于会出现在真数据上 |
| 存档点「立即存档」/「校验」 | **2026-09-29 接通**：`checkpoint.create.user` **不带** `retry_operation_id` 就是新建一个存档点（同一条命令的两种语义）；「校验」走 `GET /checkpoints/{digest}/verify`（会真去比对 manifest 与 git 锚点，失败是 409）。以前两个都只有后端能力、没有入口 |
| 验收「确认完成」 | 四件套原样转发（已接，2026-09-28）：`expected_project_revision` 用**当前** `policy_revision`（后端拿它与当前值做 CAS）；以前 mapper 回 `{}`，后端必然回 400 `proposal_id_required` |
| 设为主 Agent | 本来就能用：`appoint_main` 只读 `agent_id`，白名单里的 `ceiling_template`/`expected_authority_epoch` 运行时没人读（旧注释说“缺代次”是错的，已改） |
| 归档 / 退席 / 路径记录 | **暂不实现**（归档按钮已于 2026-09-29 从验收页撤掉）：`project.archive` / `agent.retire` 未装配；路径记录后端没这个事实
| 存档点回退 | **不做**（2026-09-28 你定的，撤掉）：没有 restore 命令，界面也不做"假装回退"；存档点只读不漏 |
| Agent 删除 / agent 地位变更（完整版） | **暂不实现**（不是待做项）：`agent.retire` 未装配；「撤销主 Agent / 代次上限」那一整套没人实现 —— 「设为主 Agent」本身仍然能用 |
| 「网络在线 / 离线」徽标在真数据下还不会出现 | 页面这一侧已经就绪（`network`/`online` 字段 + `app.setAgentNetwork` 两条通道），但**中间层还没给这两个字段**，所以真项目里所有 Agent 都按"本机接入"处理 —— 不画徽标（这本来就是对的本机行为）。要让它真出现，中间层得先知道自己管的 Agent 里哪些是网络接入的（见 `跨机器协作可行性.md`） |

### 12.4 新补的界面

- **改昵称 + 三处"保留但未实现"**（2026-09-28，只改 `index.html` 与 `behavior.js`）：
  Agent 管理卡片多了「修改」与「删除」（子 Agent 卡片仍多一个「设为主 Agent」）：
  「修改」开详情窗口 → 存 `PUT /console/profile` 的 `{agents:{<id>:{nickname}}}`（**厂商从不上送**），
  成功后重拉用到名字的地方（含 Agent 列表与左栏卡片）；「删除」按你的要求留着，点了说清原因。
  `#mgrAgentInfo` 也因此从"整窗只读 + 确定=关窗"变成"昵称可改、项目/任务只读 + 确定=保存"
  （原先多摆过一栏只读的「厂商」，后来去掉了：logo 已经说明厂商，不用再写一遍）。
  向导的「上一步」与第 3 步子 Agent 胶囊上的 `×`（CSS 的 `.itemC::before`）同样保留；
  **所有撤回类动作都标成“暂不实现”**（不再算待做），点了只弹一句「撤回功能当前尚未实现」
  —— 统一走 `notImplemented()` / `NOT_IMPLEMENTED_TEXT`，不摆原因、不假成功、不静默。

- **时间显示统一走 `util.time()`**（2026-09-28）：表格/卡片里是 `9月28日16:05:02`——本年略去年份、
  跨年才写年份、不带毫秒；**毫秒只在详情（侧栏）里给**（`timePrecise` 字段 + 各 `*Detail` 渲染器）。
  后端给的时间本身是 RFC3339 UTC，显示按本地时区换算；解析不出来的值原样显示，不编造。

- **「待用户决定」**：主视图里多一节（`render.overview` 的 `data.pending`，复用 `boxerbox`/`option`/`buttonbox2` 等已有类）。
  这一节的容器是**裸 `.boxerbox`** —— 不套 `.dataArea`、也不加 `boxerboxC`（使用者定的写法，别自作主张补外层容器）。
  卡片上那颗按钮写「决定」（原来叫「拍板」，2026-09-29 按你的说法改名），弹的是页面本来就有的 `#rightGetWin`
  （`dialog.decision`），选中的选项**原文**当 `choice` 回给 `user_decision.resolve`。
  后端把选项原文放在 `decisions` 出口的 `payload.choices` 里；没有 `choices` 就只提示、不发请求（不自己编选项）。
  选项可能是字符串，也可能是 `{value,label}` 成对结构 —— **给人看的与回传的是同一句话**（成对取 `value`，
  没有就取 `label`），两边共用同一份词表算一次，不会一边显示 `[object Object]`、另一边却回传得好好的。
  **可答值就是提案方给的词表**（2026-09-29）：`lifecycle.resolve_decision` 先看这条决定自己的
  `choices`（字符串或 `{value,label}` 行都认），只在**没给选项**时才退回 `approved`/`rejected` 这两个
  机械兜底（完成提案不带 `choices`）。所以答一个提案方没给过的词是 `invalid_decision`，不会把
  "用户没选过的东西"记成他选的。决定只负责**记账**：`decision` 记下选的那个词、卡片从待办里消失、
  审计一行（`reason_code` 机械记 `user_decision`、`evidence_level` 是 `user_confirmed`）；
  **任务不会因此解封** —— 被 `user_decision_pending:<id>` 卡住的任务要 owner 自己 `task.resume`
  （设计口径，集成测试里就这么断言的）。
  收尾提案走"验收页的「确认完成」"（`project.completion.confirm`）才是正路：它**不带 `choices`**，
  所以主视图那张卡只会提示"没有可选答复"，不会发一个注定被拒的请求。
- **「冲突」子标签（租约冲突账本）**：就在「冲突与协商」里（四个子标签：分歧 / 冲突 / Agent 间协商 / 契约）。
  它读的是新出口 `conflicts`——每一次租约被拒一条，含请求方、占用方、涉及的资源键，以及后端**机械推断**的应对情况
  （`retried_and_won` / `gave_up` / `holder_released` / `open`，显示在「处理方案」列）。
  列名、行结构与原设计里那个冲突表一致，只是数据从“认知冲突”换成了真发生过的租约拒绝；
  一开始我把它放在「意图与权限审计」的第三个子标签，你要求挑回这里，已改回（审计页仍是两个子标签）。
- **「每个项目由谁负责」接通**（2026-09-28）：`GET /projects?agents=1` 每条项目带上
  `main_agent_id` / `agents`（只有 id/status/role）/ `agents_fetched_at`。
  **名单由中间层维护**（`console/agents.py`）：第一次读到就拉一次（“打开”），之后只在
  daemon 自己的 SQLite 文件（`state.sqlite3` 及其 WAL）变动过才重拉 —— 因为 Agent 是
  经 bridge 直接接入 daemon 的，**根本不经过中间层**，没人能通知它；看文件比猜命令可靠。
  左栏每轮轮询因此几乎不产生额外请求（实测：连读两次只问 daemon 一次；碰过库后才再问）。
  想强制重读：`POST /api/v1/console/projects/{id}/agents:refresh`。
- **Agent 列表窗口接通**（2026-09-28）：新出口 `GET /console/agents`（中间层）把"谁在哪干活"
  汇总成**一行一对 (项目, Agent)**；名字/图标照旧渲染时按 id 从用户档案现算。
  任务列要问 daemon（`attempts.owner_agent_id` → 任务标题，只算未结束的），所以
  **只在窗口打开时取一次**（`app.openAgents()` 里 `refresh(['agentsWindow'])`），不跟着 5 秒轮询。
  同时把渲染器对齐回 `index.html` 的静态写法：列表只有「协作 / 任务」两行，
  详情窗口只有「项目名称 / 任务名称」两个输入框（原来多出来的"API"行是接不了的：
  后端没有"工位地址"这个概念，已删）。
  已知达不到的：`unreadable`（daemon 起着但没答的项目）名单里带了，但窗口没有能写这句话的
  标记位置，所以那种情况下窗口只会少几行 —— 要区分得先有位置。
- **等待接入的提示里写明项目目录**（2026-10-01）：遮罩上那句话从「请打开（或重载）X 窗口…」改成「请在「`<项目目录>`」下打开（或重载）X 窗口…」。原因是上面那条缺口：Agent 是按**它自己的工作目录**去找项目的规矩文件的，而 skill 里写的是相对路径、措辞又是"存在就读"——窗口开错目录它既不报错也不知情，于是照自己的"安装并初始化"说明去别处新建一个项目。目录只有一个来源：中间层的项目列表（`projects[].path`；daemon 的概况出口不含文件路径），取不到就换成不含路径的说法。两个入口（向导第 2 步 / 第 3 步与添加子 Agent）共用 `openWindowHint()` 这一句，不再各自拼。
- **等待接入时改说"已连上但还没就位"**（2026-10-01）：中间层的 `enrollments/{id}` 不再把"名单里多了一个人"当成成功 —— 要**会话就绪、而且角色已经落到票要求的那个**才算（见 `console/enrollment.py`）。没就位时它回 `waiting` + `pending`（还缺哪几项准入能力），页面用 `joiningNote()` 把缺哪几项、该在哪个目录做哪件事写到遮罩上。为什么必须分开：主 Agent 的任命发生在"就绪"那一步，而首次接入天然还不就绪，于是老逻辑会把一个还没有角色、也没有基础授权的普通成员报成"主 Agent 已接入"（真实发生过）。票过期时的提示也分成两句：从未来过 → "重新添加"，已连上但没就位 → "让它读一次项目上下文，不用重新添加"。
- **新建协作补写 Agent 入口**（2026-10-01）：中间层建完项目后顺手跑一次项目的 `bootstrap`（只写 host-neutral 入口：`AGENTS.md` 受管区块、`.tsunagou/agent-context.md`、项目 skill、`.gitignore` 区块）。原因是**接入这条链本来就要它**：向导第 2 步马上请一个宿主会话接入，而那个 Agent 的第一条指令是"存在就读项目的规矩文件"——不存在它不会报错，只会没有任何线索，然后照它自己的"安装并初始化"说明去**别处新建一个项目**（真实发生过）。只写 host-neutral 入口，不要求宿主文件：中间层在准备接入时已经把 bridge 注册进宿主自己的配置了，再让 bootstrap 写一份会把同一个会话登记两次。写失败**不会**让建项目失败（项目本身已经建好），失败原因会放在回答的 `project.bootstrap` 里，页面会提醒一句。**登记已有项目不动它的文件**——那属于把项目放这儿的人。
- **项目目标改由「对话 + 用户确认」产生**（2026-10-01，缺口清单里那条"项目目标只写不读"的收尾）：
  向导第 1 步不再问目标（只问名字），中间层在调用方没给 objective 时写占位文本
  `待主 Agent 与用户确认`（常量在 `src/tsunagou/modules/projects.py` 的 `PENDING_OBJECTIVE`，
  `project init` 的默认值也用它）—— 原来那种"没填就等于项目名"的写法会让人读到一句看起来像目标、
  其实只是名字的话。项目记录里那个字段不能为空（`project.initialize` 的 schema 是 `minLength: 1`），
  所以占位句是**真的写进 `.tsunagou/project.json`** 的，不是界面兜底。
- **主视图那句目标改读「用户确认过的决定」**（2026-10-01）：主 Agent 与用户谈定目标后提一条
  `user_decision.propose`（`kind=project.objective`、`summary` 写目标本身、`choices` 给可选项），
  用户在「待用户决定」里答过之后，主视图的 `.textArea` 才显示那句；没确认过就显示项目记录里那句占位。
  取**最后一条** `status=resolved` 的（已答的决定不能被撤回，只能再提一条，所以"最后一条"就是最新那版理解）。
  **`coordination.plan` 的抬头故意不算数**：那是"这一批任务要干什么"，换个阶段就会变。
  这一条没有新增命令或字段 —— `kind` 本来就是自由字符串，而 `summary` 是唯一的自由文本位；
  完整的取舍写在 `docs/decisions/2026-10-01-objective-from-dialogue.md`。
- **「添加 Agent」接通**（2026-09-28，见 §7.1）：`POST /console/projects/{id}/agents:prepare` 由中间层做
  「本机那半」——签一张一次性票据、写私有票据文件、写 bridge 启动说明、**按厂商注册进宿主**
  （表在 `platform/host_registration.py`，现在 Codex 与 OpenCode 有注册路径，其它厂商照实说"还没实现"）；
  `GET /console/enrollments/{id}` 回答"到了没有"，页面据此把加载遮罩一直挂着，**等宿主真连上才报成功**。
  同时 CLI 那边不再自己实现这套：`agent connect` / `agent enroll` 也改用同一份
  `platform/bridge_files.py` + `platform/host_registration.py`（一份实现，两个调用者）。
  边界（改不动的部分）：**票准备好了 ≠ Agent 存在** —— 宿主必须自己重载配置、拉起 bridge 才会兑换；
  这一步只能由人在宿主里操作，中间层做不了也不假装做了。
- **新建项目顺手起 daemon**（2026-09-28）：`POST /projects` 建完（或登记完）后调 `ensure_daemon(autostart=True)`，
  把 daemon 状态写回响应；起不来不算创建失败（条目的 `daemon` 字段照实写"未启动"，左栏本来就会显示）。
  理由：刚建好的项目如果打不开，卡片点进去全是"未启动"，看起来像没建成。
- **中间层掌管的两个写入口接通**（2026-09-28）：
  `WRITE_COMMANDS` 里新增两种"按路径直接发"的写法（`path` + `method`，不是命令通道）：
  `settingSave` → `PUT /console/profile`（主题、Agent 昵称/厂商），
  `projectCreate` → `POST /projects`（在 `projects_root` 下新建，或传 `path` 登记已有项目）。
  保存后 `profile` 与 `settings` **两份 state 都更新**（设置面板读 `settings`，名字显示读 `profile`）。
  向导里的 `mainAgent` / `subAgents` 现在也是真接入（见 §7.1、下面的"向导四步各有各的实事"）；
  项目建好之后的「添加子 Agent」走的是同一条路。
- **向导四步各有各的实事**（2026-09-28；2026-10-01 起第 1 步只问名字）：原来是"前四步只填表，只有「完成」发一条命令"，
  现在拆成：① 创建一个新的协作 —— 点「创建」就真建（目录 + `git init` +
  登记 + 顺手起 daemon），建完那个输入框**只读**、按钮从此只是"下一步"（再点不会建第二个）；
  ② 连接到主 Agent —— 真准备接入并等它连上；③ 连接到子 Agent —— 同上，可多个也可一个都不接；
  ④ **接入结果**（标题「请确定以下配置」）—— 只列出已经发生的事（项目名/描述 + 接上了谁），
  不发任何请求，「完成」只收窗复位。
  这个改法是因为原来第 4 步的"核对"是假的：项目那时还不存在，列出来的是草稿。
  第 2/3 步的遮罩上多了「取消等待」（见 §7.1 最后两条）。
  演示模式的边界：中间层不在时 `connectAgent` 直接说"演示模式没有中间层"，不假装成功，
  所以演示模式下向导会停在第 2 步。
- **向导第 2 步的厂商默认值 + 预览块的显隐**（2026-09-28，只改 `index.html` 与 `behavior.js`）：
  两个厂商选择框默认选 **Codex**（面板里 Codex 那项带 `data-default`，`resetCsBox()` 认标记，
  面板顺序没动）——它是目前唯一能自动注册进宿主的厂商；
  「你所选的 Agent」那一整块（标签 + 大图标的预览框）**名字与厂商两样都给了才显示**，
  所以刚打开向导、或把名字清空时它不占位置（`init()` 里也先摆成隐藏）。
- **Agent 昵称 / 厂商**：不属于协作事实，存在中间层档案里；`Agent 管理`页优先用档案昵称，
  程序接口是 `Tsunagou.app.saveAgentProfile(agentId, {nickname, vendor})`（界面上不新增输入框）。
- **总路径按阶段分代**（蓝条从"按日期"改成「初始化 / 正式开工 / 开始总验收 / 结束」，规则见 §7）。
  顺带修了两件：
  · **操作人**不再是一串 `0192c7f1`：Agent 显示昵称（主 Agent 带 `.id-mAgent` 配色）、
    用户显示「用户」、`runtime` 这类只能给缩写；
  · 中间层档案（`GET /console/profile`）原来只落进 `settings`，而名字查询读的是 `profile` ——
    等于"在档案里改昵称"从来没生效过；现在两份都写，`agentProfileEntry` 与总路径都读得到。

- **一次性删除整个项目**（2026-09-28，中间层 + 页面）：左栏卡片右上角补了一个 `.edit`
  （与 `.title` / `.content` 平级，位置与 hover 动画都在 CSS 里）→ 确认框 →
  `POST /console/projects/{id}:forget`。中间的实现按顺序做五件事：停 daemon（复用
  `endpoint.json` 里的 pid）→ 按 `bridges/<adapter>-<profile>/` 逐个注销宿主登记 →
  忘掉这个项目没到齐的票（连票文件一起删）→ 删 `~/.tsunagou/projects.json` 的那一条 → 删目录。
  **文件只删控制台自己 `projects_root` 底下的**；登记进来的外部项目只注销登记、
  保留目录并在答应的 `files.reason` 里写明为什么。没有分步后撤 —— 这是唯一一个"摆脱它"的动作。
  `platform/project_index.forget_project` / `console.enrollment.forget_project` / `console.projects.forget`
  是新增的三块；`.edit` 的点击不会顺带打开项目（`bindProjectCards` 先让路）。

- **能力两栏 / 开工条件 / 改动范围 / 被拒原因**（2026-09-28，本轮五件事一起接完）：
  · **Agent 管理的基本能力 4 项 + 运营能力 7 项**：会话在准入时把宿主的那份自报留下来
    （`authority.baseline_rows` 收成有界的行：11 项以内、每条 ≤8 个引用、每个引用截到 200 字符、
    空引用丢掉），`agents` 出口再按 `shared_kernel.baseline` 那条**与准入闸门同一条**规则
    算出 `missing_admission` / `missing_operational` + `session_status` + `connection_epoch`。
    页面上每一项叫什么、按什么顺序排从词表两栏来（§7.3），所以后端只说"缺哪几项"。
    **降级的连锁反应要一起看**：会话不 ready ⇒ `agent.status` 变 `provisioning` ⇒ 卡片「当前状态」
    显示**「接入中」**（不是「可用」），缺的那几项就是灰的那几个勾 —— 这三件事出自同一个判定，
    演示数据也照这个自洽（主 Agent：可用 + 全勾；子 Agent：接入中 + 1 项准入 + 2 项运营缺）。
    **两个例外照实写**：没有活动会话 → 四个字段都是 `null` → 两栏都不画（不知道 ≠ 都没有）；
    会话降级（`rebind` 带回一份更差的自报）会如实把勾变回灰，并像准入那样撤掉已有的授权。
  · **任务区的开工条件**从"前端编的四个词"改成**四件现场状态**（认知报告 / 契约 / 工作空间 / 租约），
    靠 `tasks` 视图多拖的四个出口算出来（§12.2）。**契约与任务的边只认契约内容里的 `payload.task_id`**
    —— 后端 `cognition.linked_contracts()` 就是这么连的；不写就是项目级契约，不归任何任务，
    那一格就是灰的（不是"没有契约"）。
  · **改动范围**改成**活跃租约涉及的资源键之和**（真出口给的是 `repo:x/**` 这种资源键字符串），
    没有活跃租约才退回任务自己声明的 `execution_scope`；有过期的另外补一句，不混进来。
  · **「交付结果」那一列删掉**：它是从 `results` 出口硬凑的，与"任务现在能不能开工"不是一回事。
  · **「为什么被拒」**：拒绝的原因码本来落在事件的 `payload.code` 上（`resource_conflict:file:…`），
    而 `audit` / `history` 出口只投影 `reason_code` —— 于是那一行只有动作名、括号是空的。
    现在投影出口**在 `reason_code` 为空时回填事件的 `payload.code`**，页面再把码的前半截（冒号之前）
    过一遍 `denial_reason` 词表，写成 `resource.acquire.denied（资源被占用:file:backend/api/user.py）`。
  · 演示数据（`mock-backend.js`）跟着对齐：词表替身补上这三个域、`subject_ref` 写成
    `task/<id>` / `project/<id>`（真后端的形状）、被拒那条**输入只有 `payload.code`、输出必须有
    `reason_code`**（走的就是上面那条兜底），契约内容里写上 `task_id` 好让「契约」那一格亮起来。

- **顶层出口的取法修对了**（2026-09-29）：跑真后端冒烟（`tools/dev/console_smoke.py`）才发现
  `acceptance` 那一屏一直是 `missing=['decisions']` —— daemon 的 `decisions` 不挂项目
  （`/api/v1/decisions`），而中间层把每个出口名都拼上了 `/api/v1/projects/{id}` 前缀，
  拼出来的是 404。后果不是报错而是两处**静默空着**：验收页的收尾提案卡与「确认完成」拿不到东西；
  主视图「待用户决定」那一节永远不出现（`overview` 视图根本没读 `decisions`，连"读不到"都不说）。
  现在 `CONSOLE_VIEWS` 里可以用 `GlobalExit("/decisions")` 标出"不挂项目的出口"，
  地址规则收在 `exit_path()` 一处；同时把 `decisions` 补进 `overview` 视图（页面那一节本来就
  等着读它）。冒烟复验：五个视图全部 `missing=[]`。
  **边界（当晚已解）**：「决定」按钮当时不通（`decisionResolve` 是 `null`，`resolve_decision` 只收
  `approved`/`rejected`）—— 卡片会显示了，点下去仍是明确的一句"还没接通"。这个洞当天晚上就补上了
  （可答值改成提案方自己的 `choices`，见 §7 与下面那条）。

- **「Agent 间协商」的答复/义务两列接通**（2026-09-29）：`messages` 出口原来只发
  `message_id`/收发方/`kind`/`subject_ref`/`summary`，而页面那两列读的 `status` 与 `obligations`
  在真后端一直是空的（演示数据里是手写上去的）。后端现在把它们发出来：
  `obligations` 就是每条消息的回应义务行（`obligation_id` + `status`），`status` 则是
  **出口里派生**的（`bootstrap/container.py` 的 `message_status()`）——
  没有义务 → `none`（无需答复），有 `open` → `pending`（等待中），其余（`responded`/`waived`/`superseded`）
  → `answered`（已答复）。词表 `message_status` 因此多了「无需答复」这一词（版本 → 3），
  演示后端也跟着派算同一个规矩（不再手写 status）。
  **投递状态（`pending`/`leased`/`acked`）仍然不发**：那一屏没有它的位置，等真要用再加。

- **降级那一块：卡片怎么说、总路径记什么、会话怎么自己回来**（2026-09-29 晚）：
  · **卡片说会话那一层**：词表加了 `session_status`（`ready`/`degraded`/`ended` → 已就绪/降级中/已结束，
    版本 → 4）。「当前状态」在会话降级或结束时写会话的词，其余时候照旧写席位那一层
    （`agent_status`：可用/接入中）—— "座位还在"与"会话能干活"是两件事，降级正是后者坏了。
    没有会话（`session_status` 为 null）或会话 `ready` 时，页面口径一个字都没变。
  · **总路径记"当时缺什么"**：审计行新增 `session_status` + `missing_admission`，
    但**只有做会话判定的命令才带**（`agent.enroll`/`session.rebind`/`session.reconnect`，
    由出口结果里有没有 `baseline_status` 决定），别的行动是 `null`/`[]`。于是
    `agent.enroll（降级：缺 身份续接）`、`session.reconnect（已恢复：能力全通过）`；
    降级写缺哪几项（名字经 `capability_admission`/`capability_operational` 词表），
    通过写"能力全通过"（第一次入会话叫「已就绪」，重接/重连叫「已恢复」）。老事件没有这两字段就不补。
  · **降级的会话能自己回来**（后端）：`session.reconnect` 现在接受一份**新的能力报告**
    （`api/auth.py: authenticate_reconnect_refresh` 是唯一一扇对降级会话开着的门：不查 ready，
    但必须真带 `probe_payload`），重判由 `handlers.session_reconnect → authority.rebind(baseline=…)`
    用**与准入同一条**规则做 —— 所以这条门自己升不了谁。桥接端只在"上一次已知状态不是 ready"
    时才把报告交上去（`packages/bridge-server/src/credential-handoff.ts`）：ready 的会话交一份差的
    报告也会被如实降级，而启动时探针偶发抖动不该把正在干活的宿主打下去。页面侧不用改任何东西，
    因为"改没改好"本来就只看 `agents` 出口的 `session_status`。
  · 验证：`tests/unit/test_degraded_recovery.py`（四条：缺项补齐才 ready / 空报告与坏凭据 401 /
    ready 交差报告会被降级 / 审计行记着当时的缺项）+ 桥接端两个用例；浏览器里子 Agent 卡片显示
    「降级中」、总路径那行显示 `agent.enroll（降级：缺 身份续接）`。

- **「决定」接通 + 两处只有真后端才会暴露的取值错**（2026-09-29 晚，接在降级那批之后；
  按钮名当晚从「拍板」改成「决定」）：
  · **写侧接上**：`WRITE_COMMANDS.decisionResolve` 不再是 `null`，四件套原样发给
    `user_decision.resolve`（`decision_id` / `choice` / `expected_revisions.decision` /
    `proposal_digest`）。界面上仍然是"点哪个选项就把哪个词的**原文**当 `choice`"，
    一个字都不自己编 —— 改的是后端那一条判断。
  · **后端那条判断改成提案方说话**：`lifecycle.resolve_decision` 原来把答复钉死成
    `approved`/`rejected`，而设计口径是"按该决定 `choices` 中的真实值填写，`approved` 只用于
    该选项确实存在时"（`docs/standalone/debugging-runbook.md` B5）。现在先读这条决定自己的
    `choices`（字符串与 `{value,label}` 两种形状都认）作为**唯一**词表，只在没给选项时才退回
    `approved`/`rejected`（完成提案就是这一类）。答一个提案方没给过的词 → `invalid_decision`，
    不会把"用户没选过的东西"记成他选的。
  · **收尾提案的 `kind` 名对不上（真后端才犯）**：真后端 `handlers.py` 写的决定 kind 是
    `project.complete`，而验收页筛的是子串 `completion` —— 演示数据恰好用的 `project.completion`，
    于是真后端那张完成提案卡**永远不显示**。两个名字都认了。
  · **`proposal_id` 回退取错对象（真后端才犯）**：`payload` 里没有 `proposal_id` 时原来退回
    `subject_ref`（那是 `objective_ref`），而 `completion_confirm` 是拿它去 `lifecycle.decisions`
    里查的 → 必然 404。现在退回 `decision_id`（命令响应里的 `proposal_id` 本来就是它，
    集成测试传的就是这个值）。顺带：主视图那张卡的标题也认 `outstanding_summary` 了，
    不然收尾提案会显示成裸 kind 字符串。
  · 验证：`tests/unit/test_lifecycle.py`（词表规则：选项内可答、选项外拒答、无选项退回兜底）、
    `tests/integration/test_m1_runtime_flow.py`（真 dispatcher 上用提案方的词答一次）；浏览器里
    演示数据那张卡现在会真发请求（演示替身对写命令一律 501，如实报错，不假装成功）。

- **任务行的两处修正与三个"保持现状"**（2026-09-29 晚，你点头的那一批）：
  · **「负责 Agent」下面那行小字终于有值了**：那一格本来取的是任务自己的 `started_at`/`updated_at`，
    而任务**没有时间字段**（时间挂在 Attempt 上）—— 所以真后端与演示数据下它都是空的（你说
    "没在前端看见"就是这个原因）。时间从同一次视图里拖的 `attempts` 出口取（`started_at` 是
    **epoch 秒**，新增 `epochSecondsTime()` 换算），演示数据也跟着补上这个字段。**不用改后端。**
  · **状态徽章对上了**：`TASK_STATUS_NUMBER` 原来从 `submitted` 起就按"后端自己的枚举顺序"排，
    而徽章文字全在 `style.css` 的 `.st-N::after` 里（1 草稿 … 6 卡住了 · 7 待验收 · 8 被打回 ·
    9 取消中 · 10 执行者丢失 · 11 已完成 · 12 失败 · 13 已取消）—— 结果 `submitted` 显示成
    「卡住了」、`blocked` 显示成「取消中」、`cancel_requested` 显示成「已完成」。现在照 CSS 文案
    重排（CSS/HTML 未动）。
  · 你定的三条：**用户昵称不需要**（用户不必有昵称）、**Agent 图标不用再弄**（创建协作时选厂商
    就定了，页面按厂商现算）、**计划进度保持现状**（不加注释）；**演示模式那个英文提示码也不补中文**。
    **DAG 画面**：原型已交（见 §12.5）。

- **标题栏改多级结构 + 选择框错位修正**（2026-09-29 深夜，接在“任务行”那批之后；两个临时措施一并收回）：
  · **页面标题统一成 `.title > .left`**（CSS 不动）：你把 `#pane-path` 的标题改成多级结构后，
    其余页面的标题还停在旧写法（`<p class="title">任务区</p>`）—— 旧 CSS 的胶囊色块现在挂在
    `.title > .left` 上，所以那几个页面都会变成“没底色的大字”。JS 侧新增 `pageTitleHtml()`
    专供页面标题（`主视图`/`Agent 管理`/`任务区`/`工作区`/`验收与存档点`/`总路径`），
    静态的 `冲突与协商`、`意图与权限审计` 两个标题也照同一结构改了；
    **卡片 / 窗口 / 侧栏里的 `titleHtml()` 一个没动**（主视图那张“总进度/计划进度”小标题就靠这个）。
  · **选择框错位的原因**：面板在 CSS 里是 `position: absolute`，而标题栏这条链上**一个定位祖先都没有**，
    abspos 的“静态位置”会被算到 flex 容器（`.title > .right`）的起点 —— 两个框的面板都叠在
    **第一个**框下面（实测两个框打开后都是 left=515）。修在 JS 里：这种连 `.secWindow` 都没有的地方
    改用 `position: fixed` + 视口坐标（与框等宽、右缘对齐、钉在框正下方 4px），收起时清干净；
    容器滚动 / 窗口缩放由原来的捕获监听兜住（`scheduleCsReanchor`）。测量：两个面板各自落在自己框下，
    右缘误差 0px、间距 4px。
  · **两个临时措施收回**：`FREEZE_PATH` 三处删掉（`render.timeline` 的重画拦截、`startPolling` 的不轮询），
    `index.html` 的 `#pane-path` 清回空 div —— 那一屏重新由 `render.timeline()` 画，标题里那两个选择框
    也由它发出来（**顺带解决一个 id 撞车**：静态快照里那两个面板抄了设置窗口的 `#uSetCol1`，
    页面上出现了两个同名 id，现在改成 `pathViewPanel` / `pathShapePanel`）。
  · **选择框的值不会丢**：`pathChoice` 记着选过的值，`render.timeline` 每次重画照值渲染标签，
    并把原来展开的那个重新展开（所以轮询刷屏不会把正在挑的菜单弹掉）。**但“切换看法/图形态”的
    实际效果还没接**（见 §12.5）。
  · 验证：`node --check`；浏览器实测（两个框的面板各自对齐、选「主 Agent 视角」后重画仍是它、
    重画后菜单仍开着、九个页面的标题都是 `.tabMain > .title > .left` 且拿到品牌色胶囊）。
    **还是那条：`assets/js/*` 与 CSS 没有 cache-busting，改完 JS 要 Ctrl+F5 强刷。**

- **DAG（依赖图）并入主页面 + 总路径「图形态」切换**（2026-09-29 深夜，接在标题栏那批之后）：
  · **搬进来的是什么**：原独立页面 `DAG/` 只取那张画布 —— `index.html` 里 `#pane-path` 下多了
    `.dagArea > .canvas#canvas > svg#edges`（结构写死在 HTML 里；图里的节点/边是 JS 攒的，
    所以 `render.timeline` 每次重画都先把它摘下来、画完再挂回末尾，它的内容与行内尺寸不受影响）；
    样式拆成独立一份 `web/assets/css/dag.css`（**不与 style.css 合并**），行为并进 `behavior.js`
    的「总路径 · DAG」一节（`§D1` 数据→图 / `§D2` 摆位 / `§D3` 渲染 / `§D4` 对外接口）。
  · **dag.css 只动了三处结构，设计值一个没改**：① 所有选择器收进 `.dagArea`（主页面里 `.t/.m/.s`
    这类短类名满地都是，不收窄会串味）；② **尺寸**变量从 `:root` 挪到 `.dagArea`（不给页面添
    十来个全局变量，JS 改成从 `.dagArea` 读尺寸—— 找不到会退回 `:root`）；③ 丢掉独立页面的 `body` 规则。
    原来那个两列栅格（右列就是被删掉的详情侧栏）收成一列。
  · **`.st` 徽章那段留着没删**（独立页面的注释写着"接进主页面可以不用抄"）：主页面那份 `.st`/`.st-N`
    嵌在 `.tablebox` 里（只服务表格），画布不在表格里，不自带一份就没有徽章文字。两处文案要一起改。
  · **数据从哪来**：`BACKEND_SHAPE.tasks` 里顺手调一次 `dagSetData(sources)`，把 `view=tasks` 的
    **原样** `tasks` / `attempts` / `agents` 交给图 —— `blocks`、`current_attempt_id`、`block_reason`、
    `parent_task_id` 在界面形状里都被丢掉了（表格用不到）。适配层仍是唯一一处"后端形状 → 界面形状"。
  · **切换**：`applyPathMode()` 按 `pathChoice.shape` 二选一，两个都只写 `display`
    （`.taskFlow` 清成 `''` 交回 CSS，`.dagArea` 显式写它在 dag.css 里的真实值 `block`）。
    `render.timeline` 重画后也会调它 —— 所以轮询刷屏不会把用户选的图形态刷回去，选中的任务也留着
    （`dagSetData` 只在任务真的不在名单里时才清 `sel`）。
  · **详情用主页面现有的侧栏**：点节点 → `dagSelect(任务号)`（高亮上下游、其余变暗）+ 
    `openDetail('path', 任务号)`。`DETAIL_VIEWS.path` 现在认两种 id：行动号 → 原来的「路径详情」，
    任务号（图上的节点）→ 新增的 `render.dagTaskDetail`，标题换成「任务详情」。
    **状态词走中间层词表**（`glossText('task_status', …)`）—— 注意它与徽章文字不是同一份：
    CSS 写的是「卡住了」、词表写的是「受阻」，同一个值两种说法，要统一得改 CSS 或词表（你定）。
  · **画不出来就如实说**：成环（后端不许 `blocks` 成环）、指向名单外的依赖这两件用 `notify.warn` 提一次
    （同一句话不重复刷屏），一个任务都没有则在画布上写一句实话。
  · **演示数据补了 `blocks`**：`mock-backend.js` 里「统一用户返回字段」挡着「调用方适配层」
    （A running → B blocked，正好是"前置还没满足"那道虚线），「契约回归测试」是独立任务 ——
    真出口 `/tasks` 本来就带 `sorted(task.blocks)`，这是把替身补得更像。
  · 验证：`node --check`；浏览器实测（切图形态后 `.dagArea` block / `.taskFlow` none、3 节点 1 条
    `edge pending`、4 个箭头 marker、点节点后侧栏「任务详情」+ 选中高亮 + 那条边变 hot、
    再重画一次图形态与选中都保住、切回时间图 15 行照旧）。
  · **画布不定宽 + 不按容器缩放**（2026-09-29 深夜，接在上一批之后）：原来我给画布写死了
    `width = 图宽`，同时 SVG 是 `width:100%` + `viewBox` —— 边会被**按画布尺寸缩放**，
    于是画布一换尺（窗口缩放、画布内滚动条出现）边就偏几像素（边框/滚动条那 1~7px 全算进去了）。
    现在：① 画布**不写 width**（块级元素自然跟着 `.dagArea` 走，图比画布宽就靠 `.canvas`
    自己的滚动条，节点的绝对定位会把滚动区撑出来）；② 只写 `min-height`（图多高就多高）；
    ③ SVG **不设 viewBox**，边的坐标就是像素，和节点 `left/top` 同一个原点（都是 .canvas 的
    padding box）—— 实测窗口 844→1500→620 来回缩、以及画布内滚动到最右，边的起点/终点
    与源节点下边中点 / 目标节点上边中点的偏差都是 **0.00px**。
  · **配色收口：DAG 不再自带一份颜色**（2026-09-29 深夜，接在上一批之后，你点的）：
    `dag.css` 原先自己定义了一套 `--panel/--line/--dim/--accent/--edge/--edge-ok/--edge-dead`，
    现在全部删掉，改成直接引用主页面 `style.css` 的 `:root` 变量（JS 的箭头颜色也跟着改成读同一批）：
    画布 `.canvas` = `--col-2` 底 + `--col-3` 边（与 `.asideMain` / `.boxerbox > .item` 同款）；
    节点 = `--col-3` 底 + `--col-4` 边，hover 提成 `--col-4`（照表格行 `.tablebox .tr` 的做法）；
    次要文字 = `--col-6`；选中 = `--brand-col-2`（与激活标签下边线、卡片选中态同一个色）；
    相关节点 = `--brand-col-0`（品牌色暗档）；边：还没满足 = `--col-5`、已满足 = `--col-7`、
    失败/取消 = `--active-col`（主页面里"要人注意"的橙）、选中串 = `--brand-col-2`。
    `.st-N` 徽章的四个色也照 `.tablebox` 那份对齐（1–4 品牌亮色 / 5–10 橙 / 11、13 灰）。
    **主页面没有绿色**，所以"已满足"用亮灰（表格里 `.tagZOK` 的"亮=通过"同一套口头）。
    改配色只改 `style.css` 的 `:root`，DAG 这边不再有第二份颜色。
    实测（getComputedStyle）：画布 `rgb(29,29,31)`、节点 `rgb(44,44,46)`/`rgb(48,52,53)`、
    边 `rgb(89,89,89)`、徽章 `rgb(255,121,61)`、选中 `rgb(17,141,223)` —— 全是 style.css 那几个值。

- **节点折叠/展开 + 「看法」按 Agent 过滤 + DAG 真后端联调**（2026-09-29 深夜，接在配色那批之后）：
  · **折叠/缩放（你留的那个圆点）**：点节点标题左边那个圆点 = 折叠/展开。折叠时只画
    标题条（`.m`/`.s` 不画）、节点高度交给摆位算，于是**整张图跟着变矮**。折叠高度从哪来：
    ① dag.css 里写了 `--node-h-fold` 就用它；② 没写就量一个"只有标题条、高度交给内容"的临时
    节点（量完就摘）。想调高度就在 CSS 里写 `--node-h-fold`，不用改 JS。折叠的节点带 `fold` 类
    （给 CSS 用：想给折叠态换个样子就写 `.node.fold .t::before`）。
  · **点一下是「连锁」的**：下游连着的（顺着 down 递归到底）一起折/展 —— 点中间那个，它挡着的
    那一串跟着收；**不碰上游、也不碰其它分支**（A→B、A→C、B→D 的图上点 B 只折 B+D，C 不动；
    点 A 才折 A+B+C+D，孤立任务 E 永远不动）。只想动一个节点就传第二个参数：
    `Tsunagou.dag.toggleFold(任务号, false)`。成环也不怕（seen 挡回边）。
  · **圆点是 `::before`，不占 DOM**，所以只能按位置认：横向落在「标题行左内边距 + 圆点那一小段」
    之内（圆点宽按它的 `font-size` 估）就算点到它 —— 点它只折叠，不选中、也不换右侧详情；其余
    地方照旧是"选中 + 开详情"。**圆点长在每个节点的标题行上**（`dag.css` 的 `.node .t::before`，
    原来是 `.sel .t::before`，按你的要求挪出来）—— 选没选中都能折，不必先点一下节点。
    （副作用：标题文字在圆点右边，比下面那行 `.m`（左内边距 9px）多缩进约 28px —— 这是 CSS 的
    事，要对齐就把 `.t` / `.m` / `.s` 的 `padding` 调成一样，JS 不管。）
  · **摆位改成逐节点高度**：同一层里可能有的折了、有的没折，所以每层的"主方向厚度"取这一层里最高
    的那个、起点逐层累加（LR 方向同理，竖着排时按各自高度累加）。
  · **「看法」按 Agent 切**：选项**按当前项目的真实 Agent 现算**（`pathViewOptions()` = 总视角 +
    主 Agent（角色名）+ 其余用昵称），存的是 **agent id**（选择框里写的是文字，回写时查表）。
    切了视角后：**时间图按操作人（`actor.ref`）过滤**，整段（阶段）没他就不画那一段（阶段名与起止
    是项目自己的，不跟着某个 Agent 变）；**DAG 按负责人（`ownerId`）过滤**（过滤放在摆位那一层，
    于是边、居中、空状态都自动跟着变）。空状态说清楚是哪种：「这个视角没有任务：主 Agent 视角
    没有负责的任务。」选的 Agent 不在了（换项目/名单变了）就静默退回总视角。
  · **真后端联调（真 daemon + 真命令通道）**：用 `tools/dev/console_smoke.py --keep` 起一个沙箱
    （项目 + daemon + 中间层控制台），再用它的 `control.token` 在真命令通道上
    `agent.ticket.create.user` → `agent.enroll` → `authority.appoint` → `task.create` ×3
    （后两个各带 `blocks`）建出一条 A→B→C 的依赖链。页面（live 模式）实测：视图出口里
    `sources.tasks[].blocks` 就是真 id，DAG 画出 3 个节点 + 2 条边（都是"前置还没满足"，因为任务
    还是 draft）、点节点侧栏给的是真前置/下游、折叠后图从 508px 矮到 448px（后来改成连锁：
    点这条链最上游那个圆点，3 个一起折，画布 508 → 328px）。
    **结论：`task.create` 带 `blocks` 在真 daemon 上是通的**（协议 schema 的 required 比运行时白名单
    严，但服务端不卡这个）—— 图的依赖数据不靠演示数据也能有。
  · 顺带给 `dag.css` 第一行加了 `@charset "UTF-8";`：浏览器偶尔会把没声明编码的 CSS 按 cp1252 解，
    于是 `::after` 里的中文变成 `æ‰§è¡Œä¸`（文件本身是合法 UTF-8，强刷也能好）。声明之后不再靠猜。
  · 验证：`node --check`；浏览器实测（折/展高度 100↔40、图高跟着变、边端点仍然严丝合缝；
    演示数据下「看法」三个视角时间图 15/5/5 行、DAG 3/3/0 节点；真后端上时间图 10/3 行、DAG 3/0 节点）。
  · 连锁折叠另外用一棵分叉图验过（`Tsunagou.dag.setData({tasks:{items:[…]}})` 喂进去，形状就是
    出口那套）：A→(B、C)、B→D、外加孤立 E —— 点 B 的圆点只折 B+D（C 不动），点 A 的圆点折
    A+B+C+D（E 不动），`toggleFold(id,false)` 只动 A；喂完再 `Tsunagou.refresh(['tasks'])` 就回到真数据。
  · **时间图多一层 `.inner`**（2026-09-29 你要求）：`render.timeline` 现在画的是
    `.taskFlow > .inner > (.header / .eraTitle / .item × n)` —— 外层只管外框，表头与行都在 `.inner` 里。
    受影响的 JS 只有一处：行的点击选择器从 `.taskFlow > .item` 改成 `.taskFlow > .inner > .item`
    （**两级 `>` 都不能少**：行里面还有 `.listfieldbox > .item` 的胶囊（操作人那一列），少一级就会
    先命中胶囊，而胶囊上没 `data-row-id`）。样式归 style.css。
    一个坑：`.inner` 这个类名页面里到处在用（style.css 187 / 378 / 741 / 992 / 1032 / 1055 / 1904 /
    2707 …），其中 741 那条是**全局** `.inner`（`display:flex; flex-direction:row; gap:5px`）——
    不在 `.taskFlow > .inner` 里显式写方向的话，那些行会**并排**（实测每行 474px 高）。

- **存档点这一屏补完（新出口 + 三个动作 + 两个显示 bug）**（2026-09-29 深夜，接在上面那批之后）：
  · **为什么动后端**：页面上「存档失败」那段读的是 `raw.failed`，而 daemon 的存档点出口
    （`CheckpointPageModel`，`extra="forbid"`）**根本没有这个字段** → 那段永远空、「重试」按钮永远不出现。
    真实的失败记账在 `operations` 表（`kind='checkpoint.create'`、`status IN ('failed','retry_wait')`、
    `error_code`），而 daemon 只有"按 id 取单条"的 `/operations/{id}`，**没有列表出口** —— 所以
    先补出口：`GET /api/v1/projects/{project}/checkpoint-failures`（`container.query` 的
    `checkpoint_failures` 分支：左连 `jobs` 取 `attempt_count`/`max_attempts`，`reason` 从**作业的
    payload**里取 —— 失败原因在 `request_checkpoint` 写进 job 的那份 payload 里，`operations` 行里没有）。
    `reason` 让“项目收尾时没存成”和“用户自己点了一下没存成”在界面上能分开。
  · **前端两个显示 bug**：① 卡片标题原来是 `'存档点 ' + shortId(digest)`，而 `shortId` 只截前 8 个
    字符 —— digest 带 `sha256:` 前缀，于是最新那张卡永远显示成 **`存档点 sha256:b`**；现在加了
    `shortDigest()`（先去前缀再截）。② 「（已校验）」原来只在历史卡上出现：最新那张读的是 pointer
    （只有 `digest/status/through_event_seq`，没有 `verified_at`），现在按 digest 回到 `items` 里拿
    manifest 的校验态。卡片顺带带上**时间**与**取档原因**（出口一直有，只是没人显示）。
  · **补上两个"有命令没入口"**：「立即存档」= `checkpoint.create.user` **不带** `retry_operation_id`
    （`checkpoint_create_user` 据此走"新建一个存档点"分支，带了 id 才是重试 —— 两种语义共用一个
    kind，所以 `WRITE_COMMANDS` 里分成 `checkpointCreate` / `checkpointRetry` 两条写清楚）；
    「校验」= `GET /checkpoints/{digest}/verify`（daemon 会真去校验，失败是 409；回包里带
    `git_anchors`，本机没有锚点就如实说"没有对应的 git 锚点"）。
  · 中间层没改：`console/app.py` 本来就有 `/api/v1/projects/{project_id}/{rest:path}` 与
    `/api/v1/{rest:path}` 两条**转发一切**的路由，新出口自动可用；`api.request` 对任何路径都会带上
    `Tsunagou-Project` 头（这也正是 `/checkpoints` 这类不带项目 id 的路径能被路由到项目的原因）。
  · 验证：`uv run python -m pytest tests -p no:warnings -o addopts="" -q`（455 passed；新增的
    `tests/integration/test_checkpoint_failure.py::test_checkpoint_failures_exit_lists_what_never_materialized`
    用 monkeypatch 把 `checkpoint_store.materialize` 弄挂，走 完成提案 → 确认 → 失败 → 出口能列出来 →
    用户令牌带 `retry_operation_id` 重试同一条记账）＋ `ruff` / `mypy` / `check_architecture` /
    `validate_docs` / `codegen`（新路由已进 `protocol/openapi.json`）。浏览器实测真后端：新出口 200
    `{items:[]}`（沙箱里真没有失败记账，如实空）、标题不再是 `sha256:b`、最新卡也有（已校验）、
    点「立即存档」多出一个存档点（`reason = console:manual_checkpoint`，旧的落到历史段）、
    点「校验」回「校验通过 · 封存到事件 15 · 本机没有对应的 git 锚点」；演示数据（mock-backend）
    同步补了历史存档点、失败记账与新路由，页面把「存档失败」渲染成
    `checkpoint_materialization_failed（user_requested）· 已试 2 次 · 重试`。

- **「项目验收」与「存档点」合并成「验收与存档点」一屏 + 主视图那张卡改成指路**（2026-09-29 深夜）：
  · **为什么合并**：这两样本来就是一条因果链 —— 主 Agent 提收尾、用户「确认完成」，而确认完成
    **顺手就建一个存档点**（`completion_confirm` → `request_checkpoint("project_completion")`）。
    拆成两栏反而要人在两张卡之间自己找关系。合并后 slug **仍是 `acceptance`**（`#pane-acceptance`
    还在，省得为改 id 动一堆东西），页签文字与页面标题改成 `验收与存档点`；
    `#tab-checkpoints` / `#pane-checkpoints` 从 `index.html` 删掉，`PROJECT_TABS` 少一项
    （顺序仍与 `.tabS`/`.tabMain` 一一对应）。
  · **一屏只留三样**（你定的）：① 项目完成提案（卡里含「确认完成」—— 提案与它的答复是一件事的两半，
    正文是"还差什么"、按钮是答复；没有待决定的提案时整段空，因为后端也要 `proposal_id`）；
    ② 任务验收情况；③ 存档点三段（最新 / 历史 / 存档失败，带「立即存档」「校验」「重试」）。
    删掉：遗留问题（前端从 tasks 推算的，不是后端对象）、验收标准（`standards` 恒空）、
    侧栏「详细信息」（只读那个恒空的 `standards`，所以永远白板）、「忽略」（纯本地假动作，刷新就回来）、
    「归档」（死按钮）。`render.acceptanceDetail` / `DETAIL_VIEWS.acceptance` / `ASIDE_SLUGS` 里的
    `acceptance` / `#aside-acceptance` 一并删掉；`render.checkpoints` 并入 `render.acceptance`
    （它现在从 state 里取 `checkpoints` + `checkpointFailures`，三个出口谁先到谁先重绘）。
  · **任务验收结论接真数据（你选的方案 a）**：新出口 `GET /projects/{project_id}/reviews`
    （`container.query` 的 `reviews` 分支读 `tasks.reviews`：轮次 + 结论 + 验收人 + 理由），
    并加进中间层 `CONSOLE_VIEWS["acceptance"]`（一次刷新就把结论带回来，不用多一个刷新键）。
    前端每份结果取**最高轮次**的结论：`通过`（绿）/`打回`/`拒绝`/`还没验收`，下面再补一行
    "已提交 <摘要> · 第 N 轮 · 验收人 X · 理由 Y"。**原来这里恒为绿色「已提交 <摘要>」**，
    等于替后端宣布了一个它没说的结论。结论词走中间层词表（新域 `review_decision`，
    替身同步进 `mock-backend.js` 并把词表版本 4 → 5）。
    ⚠️ **表格的一格里叠多行必须套 `.colu-t`**（你指出的 bug）：那一格是 flex 行容器
    （`.colu-m` 宽 200px），把几个块直接当兄弟节点丢进去会被挤成竖排、字都错位；`.colu-t` 的
    `flex-direction:column` 才是"格内多行"的写法（主行 `.citem1`、次要行 `.citem2`，与
    `agentTimeCell` 同一套，CSS 未动）。
  · **主视图那张收尾提案卡只留「查看详情」**（你定的）：点了切到「验收与存档点」（`ui.tab:acceptance`）。
    理由是它本来就没有可选答复 —— 原来那个「决定」只会弹"这条决定没有可选答复"。
    有 `choices` 的其它决定仍保留「决定/稍后」（那是它们唯一的答复入口）。
  · 验证：`pytest`（455 passed；`test_m1_runtime_flow` 里加了 reviews 出口的断言、`test_console_relay`
    的 acceptance sources 断言加了 `reviews`）+ `ruff`/`mypy`/`check_architecture`/`validate_docs`/`codegen`。
    浏览器实测：真后端上页签变成 8 个、「验收与存档点」五段齐全（提案段空、验收表空都是实情）、
    存档点三段照旧、`acceptance` 视图的 sources 里已经有 `reviews`；演示页上主视图卡片只剩
    「查看详情」→ 点它跳到 `acceptance` 且激活按钮是「验收与存档点」，
    任务验收情况显示「打回 · 已提交 3c9f21aa · 第 1 轮 · 验收人 [演示] 主 Agent · 理由：缺一组边界用例」。

- **「立即存档」那张卡补了标题/说明与二次确认；写动作的确认情况整体过了一遍**（2026-09-29 深夜）：
  · 那张卡以前只有一个悬空按钮（你指出“太空了”）。现在与其它卡一个形状：`headerHtml('立即存档')`
    + `textZHtml('立即将当前状态存档，而不必等待自动存档。')` + 按钮（全部复用现有渲染器，没动 CSS）。
  · 「立即存档」也改成**先弹确认再发命令**（`confirmThen`：标题/正文/后果说明/「取消·存档」两个按钮），
    与「重试」「确认完成」一个口径 —— 不再一点就落一份快照。
  · **写动作确认审计**（结论见 §4.6 的表述）：会写后端的动作里，向导第 1 步「下一步」、
    「校验存档点」、「稍后」三处**都不加**（前两个你定的：向导本身是多步表单；校验是只读的；
    稍后是纯本地收起）—— 其余写动作（确认完成 / 重试 / 立即存档 / 设为主 Agent / 删除协作 /
    取消等待 / 取消接入）都已确认。中间我一度给向导第 1 步加过确认，按你的话已撤回。
  · 验证：浏览器实测（真后端）——「立即存档」弹「要把当前状态存成一个存档点吗？」，点「取消」
    后存档点数不变（4 → 4）、也没有任何成功提示；向导第 1 步填好名字点「下一步」**不弹框**、
    照原样继续建项目。

### 12.5 仍未接线 / 已知缺口（如实记）

| 项 | 说明 |
|---|---|
| 依赖图（DAG）里"有接口没控件"的三个开关 | **2026-09-29 并入主页面**（见 §12.4）。折叠/展开已经接到图上那个圆点了；但 `Tsunagou.dag.options` 里另外三个开关**还没有控件**：`.dir`（上→下 / 左→右）、`.focus`（只看选中那一串）、`.showIso`（独立任务显不显示）—— 要加按钮就直接改 `Tsunagou.dag.options` 再 `Tsunagou.dag.render()` |
| Agent 列表窗口的「任务」列 | 只在窗口打开时取一次；不打开就不取（不跟着轮询） |
| 总路径标题栏的「看法」选择框 | **2026-09-29 晚接通**：选项按当前项目的真实 Agent 现算（总视角 / 主 Agent 视角 / 「<昵称> 视角」），选中后**时间图按操作人过滤、DAG 按负责人过滤**（见 §12.4）。两个仍不做的东西：① 只分「这个 Agent / 全局」，不做"上游下游一起看"（那是 `Tsunagou.dag.options.focus`）；② 不过滤其它屏（它只属于总路径标题栏） |
| 非 Codex 宿主的接入 | 表里已经有了，但**没有注册命令**：现在只能在中间层准备好票与 bridge 配置，由人自己把那个宿主接上。加一个厂商 = 在表里加一行 |
| 宿主重载 | 必须人做：中间层无法让 Codex / Claude Code 重新读配置 |
| 「添加 Agent」的昵称 | 要先有 `agent_id` 才能落档，所以昵称是在 Agent 到位那一刻才写进用户档案（期间换了名字它不跟进） |
| 「决定」的写侧 | **2026-09-29 接通**：可答值由提案方自己的 `choices` 决定（没给选项才退回 `approved`/`rejected`，见 §7）—— 但仍有两个不做的东西：① 完成提案的 `payload` 里**没有 `choices`**，所以主视图那张卡答不了（只留一个「查看详情」跳到验收与存档点，见 §12.4）；② 决定**不解封任务**（owner 要自己 `task.resume`，设计与集成测试都是这个口径） |
| 收尾提案的 `choices` | **保留现状（你定的）**：收尾提案不带 `choices`。2026-09-29 起主视图那张卡不再放一个点不动的「决定」，而是只留「查看详情」→ 验收与存档点；想让主视图也能答，就得让它带 `choices`，或让卡识别 `kind` 改走 `project.completion.confirm` |
| 「验收标准」 | **这一段已经从界面撤掉**（2026-09-29）：后端没这个概念（`standards` 恒空），而“任务的验收条件”目前只在 `coordination` 的 assignment 里存着、没出口 —— 见 `Tsunagou-前端接入-尚未实现清单.md` §7。等后端补了出口再谈怎么显示 |
| Agent 详情窗口 | 项目 / 任务两栏是协作事实，**只读**；**昵称那一栏可改**（存中间层用户档案），窗口「确定」= 存昵称再关窗。**不列厂商**（logo 已经标出） |
| 工作区隔离方式 | 只显示后端真有的 `driver_kind`（`shared`）；worktree / external 未接 |
| 主视图的"计划进度" | 形状照 §7 的 `progress:{total:'12%', plan:[{text,state}]}`：左边是百分数（已完成/全部，没任务就是 0%），右边是可滚动的任务清单（✓ 已完成 / ● 在做 / 无图标 未完成）。**后端没有"计划"这个对象**，这份清单是从任务列表推出来的，不是真计划。**2026-09-29 你定：就这样保持现状（不加"据任务推算"之类的注释）** |
| 用户档案里的另两项 | **2026-09-29 你定：都不算缺口**。**用户昵称**：用户不必有昵称（档案里那个 `nickname` 就让它空着）；**Agent 图标**：创建协作时选厂商就定了，页面按厂商现算（`agentIconFor(agentVendor(a))`），不拿档案里那个 `icon`。能改的仍是主题（设置窗口）与 Agent 昵称（Agent 管理「修改」） |
| 降级会话的另外两条路 | `session.reprobe`（原地重出证据）与 `session.end`（自行退场）**只在 registry 里声明、`handlers.py` 没装配**；现在能走的仍只有"带报告重连"（`session.reconnect` + `probe_payload`）与"拿新票重接"（`session.rebind`）。另外降级**不动正在跑的活**（只撤已有 grant），在跑的 Attempt 只由租约到期那条独立机制回收 |
| 一键演示 / 冒烟 | `uv run python tools/dev/console_smoke.py --reset`（建沙箱项目 + 起 daemon + 起控制台 + 逐个接口与视图源断言） |
| Agent 卡片的「说明」 | **2026-09-30 改**：以前写「厂商：xxx」，现在写**后端代号**（`agent_id` 的短号）—— 厂商交给胶囊上的 logo 说（§7「Chat agent 图标」那条也是这个口径）。胶囊本身写**昵称**；昵称还没起时退回代号，免得是一个没字的胶囊 |
| Agent 图标 | **2026-09-30 修**：厂商未知时不再冒充 DeepSeek，改摆 Tsunagou 自己的小标（`TSUNAGOU_CARD_ICON`）。三处保证档案里有厂商：①中间层到达登记时**即使没有昵称也记下厂商**（`console/enrollment.py`）；②前端接入成功那一刻再写一次（`rememberAgentProfile`，人没等就关掉遮罩也能盖上）；③**中间层读名单时按桥文件回填**（见下一行）|
| CLI 接入漏下的厂商 | **2026-09-30 补**：`agent connect` 自己写 `.tsunagou/bridges/<adapter>-<profile>/` 下的文件，**从不碰用户档案**，所以那样进来的 Agent 没有厂商。档案里缺厂商时，中间层在**读名单那一步**从本机已有的桥文件里把厂商认回来：`connection.json`（`agent connect` 写的，直接给出 `agent_id`）优先；只有 `host-identity.json` 时，用它的 `conversation_id` 算 `canonical_digest({"conversation_id": …})`，与 daemon 已公开的 `conversation_digest` 对齐。**只补缺失的厂商、只认文件不猜**：人设过的值不动，认不出来就保持保底（Tsunagou 小标）；昵称**不落档** —— 没昵称就显示后端代号 |
| Agent 昵称与厂商 | **2026-09-30 定**：界面接入必须两者齐备 —— 向导第 2 步的名称、`#addSubAgent` 的名称+厂商、详情窗口的「确定」都拒绝空昵称（`saveAgentInfo` 里那句 `昵称不能为空`）。CLI 接入不走这些表单，它漏下的厂商由中间层的桥文件回填补上，**不需要任何人手工登记** |
| DAG 画布的「都是独立任务」 | **2026-09-30 修**：`.empty` 是画布里流转内的块、节点是绝对定位的，两者同时存在就叠在一起（那句话曾经正好压在第一个节点上）。现在 `.empty` 只在真的没有节点时出现，"有任务但彼此没有依赖"改用通知说（`notify.info`，同一句话不重复） |
