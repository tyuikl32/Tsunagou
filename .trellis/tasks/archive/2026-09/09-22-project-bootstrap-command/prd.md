# 项目初始化与安装脚本联动

## Goal

提供一个真实可执行、幂等且不泄密的项目 bootstrap 命令，并让 GitHub 安装 skill 在用户选定业务项目后自动引导执行它。

## Requirements

- 新增 `project bootstrap`，接受协调根、可选 Tsunagou source root/ref 和 host 列表，生成契约子任务规定的共享入口。
- `project init` 仍只初始化项目事实；onboarding 在 init 成功后调用 bootstrap，不把安装 checkout 当作业务项目。
- 共享文件写入原子化；既有用户文件保留，冲突必须可诊断；重复运行返回 unchanged。
- 复用一个 daemon 管理多个项目；命令不能把项目 ID、scope、任务或 Agent 状态写入全局单例。
- installer 只负责安装发行物和 skills；不猜业务根、不把 token/ticket 写入项目入口。

## Acceptance Criteria

- [x] PowerShell 用户可按一条连续流程在任意 Git 项目执行 init + bootstrap + daemon start。
- [x] 生成结果包含结构化状态和下一步，不打印秘密；daemon 未启动不阻止共享入口生成。
- [x] 已有 AGENTS/skill/gitignore、重复运行、受管内容冲突和 source root 缺失均有明确结果。
- [x] 两个项目的 project bootstrap 结果和读取上下文不串项目；daemon 共用仍由运行时配置决定，本任务不新增 daemon 多项目运行时。
