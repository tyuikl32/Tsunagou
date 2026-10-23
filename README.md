# Tsunagou

Tsunagou 是一个本地运行的多 Agent 协作后端。它记录项目目标、Agent 身份、任务归属、改动范围、消息、决定、执行结果和恢复状态，让多个 Coding Agent 会话可以在同一项目中按明确边界协作。

多个 Agent 分别工作时，需要持续确认：谁负责哪项任务，哪些文件可能冲突，哪些决定已经确认，结果是否经过验收，以及中断后应从哪里继续。Tsunagou 把这些事实保存在项目中，并通过 Web 控制台、CLI 和 Agent 工具提供一致的读写入口。

## 谁负责什么

| 参与者 | 职责 |
| --- | --- |
| 用户 | 确认项目目标，决定哪些新 Agent 可以加入，处理重大决定，确认项目完成 |
| 主 Agent（main） | 拆分和分派任务，划定改动范围，处理日常协调，验收结果，执行 Git 写操作 |
| 子 Agent（worker） | 完成分配给自己的任务，只修改允许的文件范围，报告阻塞并提交结果 |
| Tsunagou | 保存身份、权限、任务、消息、决定、结果和恢复事实，并拒绝越权或过期操作 |

使用前只需了解几个概念：

- **协作（project）**：一组共同目标、Agent、任务和协作记录。
- **后台服务（daemon）**：保存和校验协作状态的本地服务。
- **Web 控制台**：选择项目、接入 Agent、查看任务和处理用户决定的主要界面。
- **连接器（bridge）**：把当前 Coding Agent 会话连接到后台服务。

Tsunagou 管理协作状态，不代替 Agent 执行工作，也不替代代码审查或部署。Agent 需要读取任务、报告进度并提交结果。宿主授予的 Full Access 不会扩大 Agent 在 Tsunagou 中的角色、任务或文件范围。

## 快速开始

当前使用路径以 Windows 和 PowerShell 为主。安装需要：

- Git
- Python 3.13
- Node.js 24.19.x
- Corepack 或 pnpm

### 1. 让 Agent 安装并配置当前项目

在准备使用 Tsunagou 的业务项目中，把下面这段话发给当前 Coding Agent：

> 请从 https://github.com/tyuikl32/Tsunagou.git 安装 Tsunagou，为当前 Git 项目配置我正在使用的 Agent 宿主，启动该项目的 daemon 和 Web 控制台，并告诉我控制台地址。不要自行接入其他 Agent；接入谁由我在控制台选择。

Agent 会把 Tsunagou 安装到独立目录，为当前项目写入不含凭据的接入配置，并继续完成 daemon、bridge 和 Web 控制台的准备。Tsunagou 源码不会复制到业务项目中。安装本身不会创建 Agent 身份，身份由后续的控制台接入流程创建。

需要手动安装时，可以在 PowerShell 中运行：

~~~powershell
git clone https://github.com/tyuikl32/Tsunagou.git "$env:USERPROFILE\Tsunagou"

$result = python "$env:USERPROFILE\Tsunagou\tools\install\install.py" --source-root "$env:USERPROFILE\Tsunagou" --skill-scope user --project-root "D:\Work\MyProject" --host codex --json | ConvertFrom-Json
$tsunagou = $result.installation.launcher
~~~

将 **D:\Work\MyProject** 和 **codex** 换成实际项目路径与宿主。然后在当前终端使用安装器返回的 launcher：

~~~powershell
& $tsunagou daemon start --coordination-root "D:\Work\MyProject"
& $tsunagou web start
~~~

**web start** 会在前台运行并输出控制台地址。需要从另一个 PowerShell 窗口检查状态时，重新打开终端后运行 **tsunagou web status**。

### 2. 接入主 Agent

1. 打开 Web 控制台，选择或创建业务项目。
2. 在「Agent 管理」中选择「接入主 Agent」，填写名称并选择当前宿主。
3. 回到准备接入的原始 Agent 对话，告诉它：**请接入 Tsunagou**。
4. Agent 完成连接后，应读取项目上下文，确认项目、自己的身份、**main** 角色和当前会话。
5. 回到控制台，确认该 Agent 已就绪。

首次加载工具时，宿主可能要求刷新工具或重新载入当前会话。完成后应回到原会话继续接入，不要创建第二个身份。

### 3. 接入子 Agent

在另一个独立的 Coding Agent 会话中，回到「Agent 管理」并选择「接入子 Agent」，填写名称和宿主。完成后，子 Agent 也应读取项目上下文并确认自己的身份、角色和会话状态。

共享同一目录或宿主不代表共享身份。每个 Agent 都必须使用自己的接入记录。新 Agent 是否加入始终由用户决定；Agent 已接入后，主 Agent 可以直接处理日常任务分派和协调。

## 完成第一次协作

主 Agent 和子 Agent 就绪后，把下面的请求发给主 Agent：

> 这个项目的目标是：<填写目标>。请先读取当前项目状态，把工作拆给已经接入的 Agent；为每项任务写清范围和完成条件。需要我决定的事项通过 Tsunagou 提出。

一次完整协作包含以下步骤：

1. 主 Agent 提出项目目标，用户确认后写入项目。
2. 主 Agent 创建任务，指定负责人、可修改范围、依赖和完成条件。
3. 子 Agent 开始任务，在指定范围内工作。
4. 子 Agent 通过任务进度、阻塞或消息报告实际状态。
5. 子 Agent 提交结果并结束本次任务执行。
6. 主 Agent 检查结果，处理后续任务，并执行需要的 Git 写操作。
7. 用户在 Web 控制台查看任务、消息、决定和结果。

一个任务完成不代表整个项目完成。主 Agent 需要提出项目完成决定，由用户确认。

## 中断与恢复

项目目标、Agent 身份、任务、消息、决定和结果保存在项目状态中。daemon、bridge 或宿主会话重启后，Agent 应重新读取项目上下文、收件箱和任务状态，再继续工作。

原任务负责人可以恢复自己未完成的工作。需要换人时，由主 Agent 显式执行恢复和重新分派。

发送消息不代表宿主已经唤起 Agent。若会话没有被唤起，消息仍会留在收件箱中，Agent 恢复后可以读取。

## 跨机器使用

跨机器协作时，一台主机运行后台服务、Web 控制台和主 Agent，其他机器接入子 Agent：

1. 在主机控制台为远端子 Agent 创建一次性接入邀请。
2. 在远端机器导入邀请，并从原始 Agent 会话完成接入。
3. 确认主机和远端安装的是兼容版本。
4. 如果 worker 需要修改文件，为它准备明确的代码副本或外部工作区。

网络监听、访问控制、邀请导入和远端工作区要求见 [用户手册](USER_MANUAL.md)。

## 继续阅读

- [Agent 快速开始](docs/overview/agent-quick-start.md)：接入后的最短操作路径。
- [子 Agent 接入指南](docs/overview/subagent-guide.md)：角色、任务和协作边界。
- [CLI 与 HTTP 操作手册](docs/overview/cli-http-manual.md)：启动、状态检查、诊断和高级操作。
- [用户手册](USER_MANUAL.md)：本地与跨机器使用的完整说明。
