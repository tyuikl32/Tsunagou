# D192 远端干文件活：走"外部准备" + 它自己报的副本（第 0 档）

日期：2026-10-03
状态：已实施

## 决定

D191 把远端挡在文件任务之外，理由是"工作区、基线与证据都是主机文件系统上的事实"。这一条**没有推翻**，
而是给它开了一扇**唯一**的门：

远端 Agent 只要满足三条，就可以接**要工作区**的任务 ——

1. 它在入席时**报过自己的代码副本**（`tsunagou agent import --copy <路径> [--baseline <分支|提交>]`，
   随 `descriptor_ref` 上来）；
2. 这个任务的隔离方式被主 Agent 选成 **`external`**（外部准备），而不是共享目录或独立检出；
3. 工作区的 `external_locator` **就是它报的那个位置**（分隔符/大小写/末尾斜杠不算差别）。

三条都满足时，主机**只记账、不读那个路径**（也读不到）：

- 工作区照样登记（谁在哪儿动过哪块逻辑路径要看得见），状态如实写成 **"远端自报"**；
- **没有基线**（主机没观察过那份副本，也就没有"改动前后"可比）；
- 交活时**没有工作区清单**：清单里的基线、改动、冲突判定都是本地观察的产物，硬造一份出来只会
  让"看起来像证据"取代证据。结果里留下的是那台机器自己的交代 —— 证据等级相应是**自报**。

哪一条不满足，就还是 D191 的拒绝，只是原因更具体：`remote_worker_needs_a_code_copy`（没报副本）、
`remote_worker_requires_external_workspace`（工作区不是外部准备）、
`remote_workspace_locator_mismatch`（位置对不上）。

## 为什么是这三条（而不是别的形状）

- **必须是"它自己报的"**：副本的位置只有那台机器知道。主机猜、或者按主机的路径推断，等于把
  D191 要防的那种失败（"看起来在范围内，实际改的是别处的同名文件"）重新请回来。
- **必须是 `external`**：另两种隔离方式绑的是**主机**的根与仓库（绝对路径 + 物理身份、单仓库工作树），
  对另一台机器根本不成立。`external` 的本义正是"在主机之外准备好的东西"，远端副本是它最自然的用法。
- **位置必须对得上**：主 Agent 从名单里读到那台机器报的位置，填进 `external_locator`。填错一个字符，
  就意味着"工作区指向的地方，这台机器从没为它担保过"。

## 付了什么代价（说清楚）

- **证据降一档**：本地那条路是"主机亲自扫过"（`system_verified` + 清单），远端这一条是"那台机器说它
  改了什么"。所以远端那一条**不出清单**，也不声称"无冲突" —— 主机不知道的事就不写。
- **拿不到补丁字节**：远端不把 diff 传回来（那是下一档的事），所以复核者看到的是它的交代与它给的证据引用。
- **冲突与范围仍然按逻辑路径判**（`root_id` + 相对路径 + 资源租约）：这一层本来就是机器无关的，
  所以两台机器不会"永远不冲突"。这也是为什么远端文件活**必须**先有 `workspace.select`，不能绕过。

## 这不是安全边界（同 D191）

"报了副本"是自报，被改过的客户端当然可以谎报。这里守的是**一致性**：别让一次"看起来在范围内"的开工
把证据变成空话。真正的边界仍是票、会话、授权与资源租约。

## 将来（不在本次范围）

- 第 1 档：远端交活时附一份**可校验的摘要**（tree hash / `git status --porcelain` 的规范化输出），
  主机不读文件也能发现"自报前后不一致"。
- 第 2 档：把"读远端文件"做成受控能力（主机点名要什么、远端回传摘要），证据等级回到"主机亲自看过"。
  那需要一份独立设计（协议、配额、读到一半变了怎么办）。

## 附：把两端接起来才发现的四件事（同日联调审计）

前面每一项都有测试，但**测试各自只覆盖一端**：CLI 断言"文件写对了"，中间层用假 daemon，执行判定
直接调 handler，插件用假 CLI。于是下面几处只有"真 daemon + 真桥 + 真的另一台机器目录"才暴露出来。
补上的端到端测试就在 `tests/integration/test_remote_machine_end_to_end.py`（真项目、真 daemon、
真 `dist/server.js`、独立状态目录与代码副本当作第二台机器）。

| # | 发现 | 症状 | 修法 |
|---|---|---|---|
| 1 | **路由式的宿主只从状态目录里的 `endpoint.json` 取主机地址**（Codex、深寻那条分支里 `httpUrl` 是空串） | 远端第一次调用必然 `daemon_endpoint_not_configured` —— "导入成功了，但什么也读不到" | `agent import` 在那台机器的私有目录里补一份 `endpoint.json`（内容就是邀请里那个地址，隧道场景下是 `--daemon-url` 覆盖过的） |
| 2 | **OpenCode 靠代码副本里的 `.tsunagou/project.json` 认项目** | 远端只有副本、没有那个文件 → 多项目 daemon 以 `project_context_required` 拒绝（单项目 daemon 恰好看不出来） | 桥新增 `TSUNAGOU_PROJECT_ID`（由导入按邀请写入，优先于目录探测；本机接入没人声明它，manifest 仍是唯一真相） |
| 3 | **Codex 注册的是"共享条目"，却带着每会话的 env** | 名字是共享的 `tsunagou`，env 却是某一个会话的票/会话文件（路由分支会忽略它们；第二台机器或第二个会话会把它改掉） | 路由式宿主改写 `write_shared_bridge_config`：注册的就是"只有路由目录"的共享条目，与本地 `agent connect` 同形；会话级事实留在路由文件里（D192 已解释为什么必须在路由里） |
| 4 | `--ttl` 没有上限 | 一张邀请可以活一整天，与"邀请是短时效机密"这条红线不符 | 收口成 60 秒 ~ 1 小时（`_invite_ttl`） |

顺带把 `workspaces` 出口补上 `external_locator`：复核的人要知道"这活是在哪台机器上的哪个目录做的"。

### 还发现一处**测试污染了使用者的机器**（已修）

机器级的那条待接入记录（`~/.tsunagou/console-enrollments/enrollments.json`，每个 OS 用户只有一条）
**一直在被仓库自己的测试和冒烟工具写**：审计时那份文件里躺着 19 条记录，13 条来自 `pytest-of-*`、
6 条来自 `console-smoke`，全都是随临时目录一起消失的项目。后果有两个：使用者的机器上常驻着"有人
在等接入"的假记录；而只要有一条 `pending` 没收掉，后面的接入就全部 `enrollment_already_pending`
（这次就是这么撞上的）。

修法与当年项目索引那次同款（见 `tests/conftest.py` 的注释：那份 `~/.tsunagou/projects.json` 曾经被
写进 260 条）：给整套测试加一条 per-test 的 `TSUNAGOU_ENROLLMENT_DIR` 守卫（留一条 pending 也不会
挡住下一个用例），冒烟工具把它的沙箱环境一并指向沙箱目录。使用者那份被污染的 store 已挪到
`~/.tsunagou/console-enrollments.backup-<时间戳>` 留底，之后测试与冒烟都不再碰真实那份。

## 落点

- 判定与工作区：`src/tsunagou/application/workflows/execution_commands.py`
  （`_require_supported_workspace` / `_remote_holder` / `prepare_begin` / `begin` / `prepare_submit` / `submit`）
- 自报通道：`agent import --copy/--baseline`（`cli/app.py`）→ 身份文件 → 桥
  （`packages/bridge-server/src/server.ts::readSelfReport`、`credential-handoff.ts::descriptorRef`）
  → `handlers.enroll` → `authority.Agent.copy_path/copy_baseline` → agents 出口
- 人话与状态词：`src/tsunagou/console/glossary.py`（三个拒绝码 + 工作区状态「远端自报」）
- 界面：Agent 详情窗的「代码副本」一行，以及"这台机器的限制"那两句会跟着变
- 测试：`tests/integration/test_remote_worker_scope.py`、`tests/unit/test_remote_machine_name.py`、
  `tests/unit/test_remote_invite.py`、`web/tests/behavior.smoke.test.ts`
