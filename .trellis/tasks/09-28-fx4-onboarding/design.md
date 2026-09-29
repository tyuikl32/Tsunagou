# FX4 接入设计

## 一个安装位置，多项目入口

复用安装器和 project-integration.json 的 source metadata。安装时优先显式 source-root/已登记安装，其次当前确认为 Tsunagou 的 checkout，最后新安装默认位置；记录实际路径、commit、Python/bridge 版本。显式来源与已有安装不一致必须使用明确指定的来源或报具体冲突，不能静默复用。源码不复制到业务项目。

安装器生成用户级 tsunagou 启动入口，绑定安装 runtime；普通调用从 --project-root 显式值、已绑定项目环境或 cwd 最近的 project-integration.json 定位。显式值互相矛盾返回 project_context_conflict，不猜测第一个可用 token。项目根、状态目录、daemon endpoint、control credential 由同一 resolver 产生。

已有 daemon 是否可复用还要核对目标项目注册及 source/runtime 信息，不能仅因为该端口 health=200 就宣布成功。项目定位不等于一项目一 daemon：多个业务项目可继续引用同一个已登记 daemon，不强制复制源码或新开进程。只有没有已选可用 daemon 时才按现有启动流程处理；不构建新的多项目服务管理平台。

Windows 后台启动不依赖 PTY；使用隐藏进程、独立标准流和已有 daemon.log，记录 PID/启动时间并验证接口响应。daemon stop 定位用户选定的 daemon 进程；共享 daemon 的多个项目应在结果中明确，不把停止单个项目任务等同于停止整个 daemon。不开机自启服务，不因安装而启动无关项目。

实施细化：`bootstrap/daemon.py` 只承载项目 HTTP 路由与本机登记，复用显式 config 装配的项目容器。首次加入共享进程使用 `daemon start --reuse ROOT`，以原启动项目 U token 调用 `POST /api/v1/daemon/projects`（project_root/state_dir）；Agent token 不能注册项目。私有 daemon-projects.json 记录位置，领域状态仍各自 SQLite。项目 URL/header 冲突返回 project_context_conflict，多项目无选择返回 project_context_required。重启从任一成员的 endpoint 找回同一注册文件，恢复全部成员，不静默丢弃未启动的项目，也不搜索本机所有项目。

## 自动取得宿主上下文

保留 agent connect 作为用户接入入口，新增 agent prepare --adapter codex：由正在接入的 Agent 在真实宿主进程上下文运行，收集当前 project、会话标识、本机管道、安装位置，写私有接入请求文件。它不任命角色、不签 U 权限、不创建 Agent。

若需要用户执行命令，给完整的：
tsunagou --project-root <已填实际路径> agent connect --adapter codex --request-file <已填实际文件路径> --role worker
上述路径由向导填写，用户无需抄 ID。用户明确授权 Agent 执行接入时直接执行；main 任命沿用户明确选择的 --role main，不新增二次 appoint 仪式。

request-file 是本机请求引用，含宿主绑定信息而不含 U token；放 .tsunagou/local/onboarding/，原始 pipe 与 thread 不进入提示正文。connect 创建 ticket 时将请求与 ticket 绑定，enrollment 兑换为 Agent 后自动登记 FX3 provider。普通 worker 不能借此绑定别人的 agent_id。

MCP metadata 中的会话身份优先用于每次请求路由；没有 metadata 时仅在宿主已提供可验证的专属进程身份下回退到环境。多会话共享进程不能共享一个 profile/session。当前 bridge 的 host identity、session 文件及 project 路由必须一起检查；禁止生成 tsunagou:* 随机 ID 冒充真实 Desktop thread。

## 接入完成和重载

connect 幂等复用当前会话尚未消费的请求/接入状态，不每次创建新身份。已有 bridge 每次调用前复用现有 credential-handoff 检查新 ticket/session 和 endpoint，减少没有实际变化的 session.reconnect。

第一次安装后若宿主需要加载 MCP，向导调用实际可用的宿主重载路径；没有该路径时说明一次具体动作及验证点，不能循环宣称 Ctrl+R 一定会重启 bridge。ready 只在原会话 context 返回已认证身份、正确项目并完成 provider 绑定时报告；实际自动唤醒由 FX3/FX6 验证，不生成独立能力证明表。

更新项目生成器，使 AGENTS 管理块、agent-context.md、project Skill 和运行 Skill 使用 begin/submit，main 主动处理收件箱请求。先检查现有任务/重复请求，再发布或明确回复无需新任务；ACK 仅表示收件，不替代响应义务。业务决策由 main 作出，不能把“收到请求就自动发布任何任务”硬编码进 daemon。

bootstrap 只物化 --hosts 选择的配置，注册项目 root；多仓库根按原授权追加。保留用户区块，不重写整份 AGENTS。重复 bootstrap 内容不变时不产生噪声修订。

## 查询入口

新增 agent list --json，复用现有 agents 投影与权限。输出 agent_id、role、会话脱敏标识、当前任务、最近活动时间及连接状态；最近无活动不是死亡，也不释放占用。无需读取 worker 私信即可看见是否开始工作。
