# 技术设计

## 项目安装路径

Agent 在用户明确要求“在当前项目安装 Tsunagou”时，先在原业务工作目录解析 Git 根并保存为 `project_root`，再从该目录之外克隆 Tsunagou checkout。安装器只接受显式 `--project-root`，不根据自身 checkout、环境变量或默认目录猜项目边界。

当 `project_root/.tsunagou/project.json` 不存在时，安装器在同一运行中调用已安装 CLI 的 `project init`，使用显式参数 `--project-name`、`--project-objective`（缺省值可诊断但必须稳定），然后调用 `project bootstrap`。已有项目只执行 bootstrap。若目标不是 Git 仓库，先失败并给出 `git init` 诊断，不替用户创建仓库。

阶段顺序为：clone/reuse source -> Python/Node dependencies -> generic skills -> optional project init -> project bootstrap -> verification。任何阶段失败保留 checkout 和已写入的非秘密文件；不启动 daemon、不 enrollment、不任命 main、不发布 task。

## 消息与唤醒边界

`message.send` 只负责在 daemon 的持久化消息/投递存储中创建记录。bridge 暴露 `inbox__claim/fetch/presented/ack`，连接中的 Agent 可以主动 pull。MCP stdio server 没有通用的、能从 daemon 反向驱动 Codex 模型新回合的接口，因此 generic bridge 不实现伪造的 wake。

如果未来某宿主提供可靠的外部唤醒 API，应作为 adapter 能力声明（`supported` + 真实 evidence）和独立 notifier 实现；失败时 pull 仍可用，消息不会被丢弃。文档必须把 `message_created`、delivery 可读和 host conversation 被唤醒分成三个状态。

## 兼容性与回滚

- `--project-root` 未提供时，安装行为保持 source/skill-only。
- 目标已有项目时不创建新 ID；项目本地受管文件继续使用既有 bootstrap 幂等/冲突规则。
- 自动 init 只写 `.tsunagou/project.json` 和本地 bindings，不接触业务源码或秘密；失败可删除本次新建 `.tsunagou` 后重试。
