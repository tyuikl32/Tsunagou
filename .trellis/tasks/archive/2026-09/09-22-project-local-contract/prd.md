# 项目本地约束包与源码引用契约

## Goal

冻结项目初始化后必须生成的无秘密、可提交入口，使任何支持的 Agent 在业务项目目录中都能找到 Tsunagou 约束，并能定位规范源码而无需复制源码。

## Requirements

- 定义 `.tsunagou/project-integration.json` 的稳定字段、版本、digest、来源 URL/安装路径提示和 managed file 清单。
- 定义 `.tsunagou/agent-context.md`、`.agents/skills/tsunagou-project/SKILL.md` 和 `AGENTS.md` 的受管标记与内容一致性。
- 明确 `.tsunagou/local`、token、ticket、endpoint、session、SQLite、日志不属于共享项目入口。
- 明确已有 `AGENTS.md`、`.gitignore`、`.agents/skills` 时只增量更新，受管块被修改时产生冲突而不是静默覆盖。
- 明确 generic 入口是硬要求，host hook/平台专属文件只有真实能力证据才可声明生成。

## Acceptance Criteria

- [x] schema 能表达新建、重复生成、source checkout 移动、版本升级和缺失 source root，且不能容纳秘密字段。
- [x] 三份 Agent 入口的主/worker/user 边界、Full Access 限制、claim/preflight/start、Git 归属、ACK/恢复规则语义一致。
- [x] 所有受管文件都有版本标记和 content digest；非受管用户正文不会被模板覆盖。
- [x] 文档给出项目相对规范链接和 GitHub URL；绝对 source path 仅为可选诊断值。
