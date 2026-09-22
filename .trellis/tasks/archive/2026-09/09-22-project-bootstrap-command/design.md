# 项目初始化与安装脚本联动设计

## 命令边界

新增 `project bootstrap` 是项目文件物化命令，不是 Agent/任务业务命令。它使用 `TSUNAGOU_PROJECT_ROOT`、显式 `--coordination-root` 或现有 endpoint/project manifest 定位项目；通过 user control 或本地初始化上下文核对 project_id。命令输出每个文件的 `created|updated|unchanged|conflict`。

建议参数：

```text
project bootstrap --coordination-root <path>
  [--source-root <path>] [--source-ref <ref>]
  [--host generic|codex|opencode|deepseek ...]
  [--refresh] [--json]
```

默认不启动宿主、兑换 bridge、任命 main、生成任务或修改 Git 历史。`--refresh` 只刷新带标记的受管文件和来源诊断。

## 与安装 skill 的关系

`tools/install/install.py` 保持 GitHub clone、uv/pnpm 安装、bridge build、skill 安装和版本检查。`tsunagou-install` 完成后将 source root 传给 onboarding；`tsunagou-agent-onboarding` 在用户确认目标项目后按顺序执行：

```text
git init (若需要) → project init → project bootstrap → daemon start/status → agent enroll
```

安装脚本不能在没有用户选定协调根时把入口写到任意当前目录，也不能把 daemon token 复制到 checkout 或业务项目。

## 写入实现

新增 project integration service，负责模板、manifest、原子文件替换、受管标记和状态结果；CLI 只做参数/环境适配。写入前创建 `.tsunagou`，随后按契约写共享文件；`.tsunagou/local` 仍由 daemon lifecycle 创建。

`AGENTS.md` 和 `.gitignore` 用标记区块替换算法；其他三文件使用临时文件 + `os.replace`。并发调用按协调根锁或 manifest CAS 串行化。
