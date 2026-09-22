# 独立多项目验收与使用文档

## Goal

用真实 CLI/daemon/临时 Git 项目证明“安装后项目本地约束确实存在并被发现”，而不是仅证明 skill 或 bridge 构建成功。

## Requirements

- 覆盖全新项目、已有自定义入口、重复/并发 bootstrap、两个项目共享 daemon、source checkout 移动和源码树外安装。
- 验证共享入口无秘密、daemon state 分离、project_id/Agent/任务不串项目。
- 写出 Windows PowerShell 首次安装、初始化、bootstrap、daemon、主/worker enroll 的连续操作单。
- 保存非秘密 JSON 证据、版本、退出码和生成文件摘要。

## Acceptance Criteria

- [x] 独立临时项目 smoke 全部通过，且第二次 bootstrap 为 unchanged。
- [x] 用户自定义 `AGENTS.md` 和 `.gitignore` 正文保持不变，冲突不会静默覆盖。
- [x] 两个项目的上下文入口隔离；移动 source 后刷新不改变项目身份。一个 daemon 同时托管多个 runtime 不在本子任务的通过证据中。
- [x] 文档中的主要命令在干净/临时环境实际执行过，失败路径有明确诊断。
