# Tsunagou 用户手册

> 这份文档写给**用 Tsunagou 的人**，不写给改代码的人。目标是：照着做能在一台机器上跑起来，
> 也能让第二台机器加入同一个协作。
>
> 文中的命令在 **Windows + PowerShell** 下实测过（最近一次 2026-10-05）。要更细的背景与
> 逐屏说明，看 [详细使用手册](docs/overview/user-guide.md)；要接口级细节，看
> [CLI/HTTP 说明书](docs/overview/cli-http-manual.md)。
>
> **两份文档的分工**：这一份是"上手 + 日常 + 排错"的实操手册，讲到够用为止；
> [docs/overview/user-guide.md](docs/overview/user-guide.md) 讲得更细（每个词、每一屏、
> 虚拟机那台的具体步骤）。两者冲突时以那份为准，并且请把冲突告诉我。

---

## 1. 它是什么，谁做什么

一句话：**让多个 Coding Agent 在同一个项目上协作，并且让冲突在动手之前就被看见。**

| 谁 | 负责什么 |
|---|---|
| **你** | 定目标、决定谁能加入、拍板重大决定、验收成果 |
| **主 Agent** | 拆任务、划每项改动的文件范围、验收；必须在**主机**上 |
| **子 Agent** | 真正干活；可以在本机，也可以在别的机器 |
| **Tsunagou** | 替你盯住：谁在负责什么、做到哪一步、谁的活会撞车、断线换人后怎么接着做 |

三个词先认一下：

- **协调中心**（daemon）：这个项目的"唯一真相"，所有 Agent 都向它汇报。跑在**主机**上，默认端口 `2810`。
- **控制台**（console）：你打开的那个网页：建协作、接入 Agent、看进度、验收。只跑在**主机**上，默认 `http://127.0.0.1:2812`，只监听本机。
- **桥**（bridge）：每台机器上把 Agent 接上协调中心的小程序。在界面上点接入时自动配好，不用手写。

---

## 2. 装一次

前提：Python **3.13**、Node、pnpm。

```powershell
# 仓库根目录下执行；它会装依赖并准备环境
powershell -ExecutionPolicy Bypass -File tools\dev\bootstrap.ps1
```

如果你的机器连不上 GitHub（常见于内网虚拟机），**不要把主机的 `.venv` 直接拷过去** ——
里面写死了主机的绝对路径。把仓库打包成一份压缩包或 Git bundle 带过去更可靠。

装完可以自检：

```powershell
python -m tsunagou --version
python -m tsunagou doctor
```

---

## 3. 五分钟上手（只在一台机器上）

### 第 1 步：建一个协作

```powershell
python -m tsunagou project init --coordination-root "E:\Tsunagou\projects\我的协作" --name "我的协作"
```

`--coordination-root` 是**协作目录**（项目文件放这里），必填。

> 也可以不敲命令：先起控制台（第 2 步），在页面的"新建协作"向导里建。第一次用推荐走页面。
> 向导会问一屏：**协作根目录、端口号、绑定地址、对外地址**。只在主机上用就保持默认；
> 要让别的机器连，见第 4 节。

### 第 2 步：起控制台

```powershell
python -m tsunagou web start          # 前台运行，Ctrl+C 结束
python -m tsunagou web status         # 另开一个窗口看：Tsunagou console: running at http://127.0.0.1:2812
```

浏览器打开它打印的地址即可（默认 `http://127.0.0.1:2812`）。默认端口被占用时它会**自动换一个**，
并把实际地址打印出来 —— 要收藏的是打印出来的那个。

### 第 3 步：让主 Agent 接入

在页面里选好协作与厂商，按提示操作即可。本机接入有两种形态，按你的宿主选：

- **在宿主自己的聊天里接入**（DeepSeek Harness 这一类）：控制台只留下一条"申请"，
  你在那个聊天里说一句「**请接入 Tsunagou**」，剩下的由那条会话完成。
- **OpenCode / Codex 本机接入**：同样先在控制台留下申请，然后由那条会话认领：

  ```powershell
  python -m tsunagou agent join --adapter opencode   # Codex 用 --adapter codex
  ```

  控制台不签票、不写宿主配置；签名与桥配置都发生在**认领**这一步。

### 第 4 步：目标要"提案 + 你确认"

建协作时那个 `objective` 字段是**占位**（默认写着"待主 Agent 与用户确认"），不是你的目标。

真正的目标是：主 Agent 与你谈清楚之后提一条决定，**你确认**了，界面才会把它显示成目标。
在那之前，任何看起来像"目标"的句子都还只是草稿。

---

## 4. 让第二台机器加入

三个动作，谁做哪一步写清楚了：

### ① 那台机器先"报号"

```powershell
# 在第二台机器上（它自己的项目目录里）
python -m tsunagou agent whoami
```

把打印出来的编号发给主机。

### ② 主机打一张邀请

```powershell
# 在主机上
python -m tsunagou agent invite --adapter opencode --nickname "远端小三"
```

三个要点：

- `--adapter` 是**必填**：写对方用的宿主（`opencode` / `codex` / `deepseek`）。
- `--nickname` 是**给人看的昵称**，可以中文。
- 会话名谁起，看宿主：**主机能起名的**（OpenCode）这边直接生成一个；**只有它自己知道会话名的**
  （Codex、DeepSeek Harness）先让对方 `agent whoami` 报号，再用 `--conversation-id <编号>` 传进来。
- **会话名（会话 id）由主机随机生成，必须是纯 ASCII**。OpenCode 会把它放进 HTTP 头，
  中文会被宿主直接拒掉。邀请里会带着这个名字，你要用它开会话：
  `opencode --session <邀请里给的名字>`，**开了之后不要改名**。
- 邀请默认 **10 分钟**有效（`--ttl` 单位是秒），而且**一次性**：
  当作凭据对待，不要贴进聊天记录、不要提交进仓库。

### ③ 第二台机器导入

```powershell
# 在第二台机器上
python -m tsunagou agent import "<把邀请内容整段粘进来>" `
  --workdir "C:\work\我的协作" `
  --daemon-url "http://192.168.32.1:2810" `
  --machine "工位-九" `
  --copy "C:\work\我的协作" `
  --baseline main
```

然后在那个会话里说一句「**请接入 Tsunagou**」，主机的页面上会自动出现它。

| 参数 | 写什么 |
|---|---|
| `--daemon-url` | 主机上协调中心**能被这台机器拨到**的地址 |
| `--machine` | **只写机器名**（如 `工位-九`）。写成 `http://…` 或 `host:port` 会被拒 |
| `--copy` | **这个项目的代码副本**在这台机器上的位置（不是 Tsunagou 的安装位置）。声明一次，之后不能改 |
| `--baseline` | 这份副本对应的分支或提交 |

### 主机这一侧要能被拨到

```powershell
python -m tsunagou daemon start `
  --coordination-root "E:\Tsunagou\projects\我的协作" `
  --host 192.168.32.1 `
  --port 2810 `
  --advertised-url "http://192.168.32.1:2810"
```

- `--host` 决定**在哪些网卡上听**。只在本机用写 `127.0.0.1`；要让别的机器连，
  必须写那张网卡上对方能到达的地址。
- `--advertised-url` 决定**邀请里写哪个地址**，也就是对方会去拨的那个号。
  跨机器时**必须**写成一个对方真能连上的地址。
- **不要把 `0.0.0.0` 当成对外地址**。绑 `0.0.0.0` 是"听所有网卡"，它不是别人能拨的地址；
  不写 `--advertised-url` 的话，邀请里会落到回环地址，对方永远连不上。

---

## 5. 日常怎么用

左栏选一个协作，右边一共**八个标签**（顺序就是页面上的顺序）：

| 标签 | 看什么 |
|---|---|
| **主视图** | 目标、基本信息、协作进度、统计、存储位置；还有"**待用户决定**"那一节 —— 需要你拍板的事都在这儿 |
| **Agent 管理** | 谁在这个协作里、什么角色、什么状态；任命主 Agent、让某个 Agent 退役都在这一屏 |
| **任务区** | 每项任务谁在做、什么状态、动了哪些文件；还包括开工条件（认知报告／契约／工作区／租约）与改动范围 |
| **冲突与协商** | 消息与契约，以及**冲突账本**：谁和谁在哪件事上不一致、谈成了什么 |
| **租约审计** | 谁在什么时间占了哪些资源（租约与意图） |
| **工作区** | 隔离出来的工作区，以及文件占用情况 |
| **验收与存档点** | 验收结论、等你确认的完成提案、中途快照（含"没存成"的那几条）。两者**故意合成一屏**：确认完成本身就会落成一个存档点 |
| **总路径** | 任务之间的先后关系（谁等谁）画成一张图，也就是这个协作的推进路径 |

### 主视图那个百分数是什么意思

它是**按任务记录数**算的：`已完成 ÷ 全部任务记录`。所以：

- **已取消**的任务单独标出来（清单里带「已取消」前缀），它不算"做完了"，但也不该被读成
  "还没开始"；**被替代**的另有「已被替代」标记 —— 那是"换了条任务接着做"，统计里也单独报，
  不和"已取消"重复计数；
- **业务验收通过率**是另一回事，在"验收与存档点"那一屏。两份数字不同是正常的 ——
  "验收 12/12 而任务面板 50%"完全可能同时成立，尤其是中途重排过任务的时候。

### 生命周期什么时候变成"已完成"

只有**你确认**了主 Agent 提的完成提案，项目才会标成完成。主 Agent 只能提提案。

提案会出现在**主视图的"待用户决定"**里，点"查看详情"会把你带到**"验收与存档点"** ——
确认动作在那里。提案挂着等你的期间，页面显示的还是"进行中"。

---

## 6. 停与收尾

```powershell
python -m tsunagou web stop                      # 停控制台
python -m tsunagou daemon status --coordination-root "E:\Tsunagou\projects\我的协作"
python -m tsunagou daemon stop   --coordination-root "E:\Tsunagou\projects\我的协作"
```

**停控制台不会停协调中心**，Agent 可以继续干活。这两件事分开是有意的：
协调中心是脱离控制台的作业对象启动的，正是为了让它活过控制台的关停。

`web stop` 的清单文件写在**配置文件旁边**；不带 `--config` 时用默认位置（`~/.tsunagou/`），
所以 `start` / `status` / `stop` 要么都用默认，要么带同一个 `--config`。

想请一位 Agent 退场（他从此不能再动，但做过的事一个字都不改）：

```powershell
python -m tsunagou agent retire <agent_id> --reason user_requested
```

---

## 7. 出问题时先看这几条

页面上的红色提示、或者 Agent 报回来的错，多半是下面某一条。括号里是你能搜到的原文。

| 现象 / 报错 | 意思与怎么办 |
|---|---|
| `not_enrolled:run_agent_connect` | 这条会话还没接入。本机走控制台留下的申请（`agent join` / 在聊天里说一句）；跨机器要先 `agent import` 再在会话里说一句 |
| `conversation_id_must_be_ascii` | 会话名不能用中文。会话名是给宿主看的（会进 HTTP 头），中文请填在**昵称**里 |
| `machine_must_be_a_name` | `--machine` 只写机器名（`hostname` 命令的输出就是它），别写地址；地址用 `--daemon-url` |
| `daemon_endpoint_not_configured` | 那台机器不知道主机地址（路由式宿主只读它状态目录里的 `endpoint.json`）。重新导入一次邀请 |
| `host_route_project_conflict` | 这个会话名已经绑在别的协作上了。用 `opencode --session <新名字>` 开一条新会话再接入 |
| 页面提示"有 N 项数据拉取失败" | 页面有几个出口没读到。先 `python -m tsunagou daemon status --coordination-root <目录>` 看协调中心在不在；在跑就检查中间层记的地址是不是**能拨到的**（跨机器时看 `--advertised-url`） |
| 控制台打不开 / 地址不对 | `python -m tsunagou web status` 看它到底在哪；默认端口被占会自动换一个 |
| 邀请过期 | 邀请默认 10 分钟、一次性。回到主机重新 `agent invite` 一张 |
| 桥/宿主连不上协调中心 | 先在第二台机器上直接访问 `--daemon-url` 那个地址；网络不通时先解决网络，再谈接入 |

还有两个最常见的"其实没坏"：

- **主视图进度不动**：它只在 Agent 汇报时变。任务没被领取、或者没提交，它就不动。
- **进度与验收数字不一致**：见第 5 节，两个指标本来就不是一回事。

---

## 8. 安全与权限（请务必读）

- **接入一位新的 Agent 是你的决定。** 主 Agent 不该自己发邀请；如果它问你要不要接入谁，
  那是它在按规矩征求你同意。
- **邀请是凭据。** 一次性、有时效，能换一个席位。不要贴进聊天、不要提交、不要放进截图。
- **项目完成、重大设计、权限边界都由你拍板。** Agent 只能提提案。
- **控制台只管本机。** 它自己不做认证，却拿着各项目的控制令牌替你转发命令，所以只监听回环地址。
  想让别人用，是让别人接入协作，而不是把控制台暴露到网络上。

---

## 9. 命令速查

```powershell
# 项目
python -m tsunagou project init --coordination-root <目录> --name "<名字>"
python -m tsunagou project complete                # 确认完成提案；参数较多，见下
# 等价写法（三个都是必填，值来自那条提案本身）：
# python -m tsunagou project complete <提案编号> --expected-project-revision <n> --digest <摘要>
# 日常直接在上面的"验收"那一屏点确认，不用敲这三个值。

# 协调中心（默认 127.0.0.1:2810）
python -m tsunagou daemon start --coordination-root <目录> [--host <地址>] [--port 2810] [--advertised-url <地址>]
python -m tsunagou daemon status --coordination-root <目录>
python -m tsunagou daemon stop   --coordination-root <目录>

# 控制台（默认 127.0.0.1:2812）
python -m tsunagou web start [--port <端口>] [--config <配置>]
python -m tsunagou web status [--config <配置>]
python -m tsunagou web stop   [--config <配置>]

# 接入
python -m tsunagou agent whoami                            # 报号（在那台机器上）
python -m tsunagou agent invite --adapter <宿主> --nickname "<昵称>"   # 主机发邀请
python -m tsunagou agent import "<邀请内容>" --workdir <目录> --daemon-url <地址> --machine "<机器名>" --copy <副本目录> --baseline <分支>
python -m tsunagou agent join --adapter opencode            # 本机会话认领控制台的申请
python -m tsunagou agent retire <agent_id> --reason user_requested
```

加 `--json` 可以把任何命令的输出变成机器可读的 JSON（脚本里好用）。

---

## 10. 想了解更多

| 想看什么 | 去哪里 |
|---|---|
| 每个词、每一屏、虚拟机那台的逐步操作 | [详细使用手册](docs/overview/user-guide.md) |
| 命令与 HTTP 接口的完整说明 | [CLI/HTTP 说明书](docs/overview/cli-http-manual.md) |
| 子 Agent 怎么加入与协作 | [子 Agent 指南](docs/overview/subagent-guide.md) |
| OpenCode 接入的具体约束 | [OpenCode 适配说明](docs/implementation/adapter-opencode.md) |
| 控制台的组成与边界 | [本机控制台](docs/implementation/console.md) |
| 装不动、起不来 | [调试手册](docs/standalone/debugging-runbook.md) |
| 文档总目录 | [docs/README.md](docs/README.md) |
