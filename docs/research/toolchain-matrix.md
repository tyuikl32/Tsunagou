# T01 实际工具链核验

核验日期：2026-09-18，Windows 11。版本窗口来自项目技术说明；本文件保存本机输出和注册表结果，不能替代其他 Windows 干净环境的重装验收。

| 工具 | 项目窗口 | 本机/注册表证据 | 结论 |
|---|---|---|---|
| Python | >=3.13,<3.14 | Python 3.13.13 | 符合 |
| uv | 项目锁定工具 | uv 0.9.26 | 已执行 uv lock/sync |
| Node | >=24.19,<25 | v24.19.0 | 符合 |
| pnpm | >=12,<13 | 本机 shim 11.19.0；corepack 下载并执行 pnpm 12.4.2 | 项目命令使用 corepack pnpm 12.4.2 |
| TypeScript | >=7.0,<7.1 | npm registry 提供 7.0.2；workspace check 通过 | 符合 |
| Codex | T02 研究对象 | codex-cli 0.154.0-alpha.6.2 | 已生成脱敏探针证据 |
| OpenCode/ZCode/DeepSeek Harness | T02 研究对象 | OpenCode 1.18.31、DeepSeek Harness 0.1.5-rc.2 可由 npm 临时运行；ZCode 当前无官方可锁定安装 | OpenCode/DeepSeek 只有部分无模型证据，ZCode unknown；ZCode不阻塞首发，但均不能称 supported |

已执行命令及结果：

    uv lock                         exit 0
    uv sync --extra dev             exit 0
    corepack pnpm install --lockfile-only  exit 0
    corepack pnpm -r run check      exit 0
    uv run pytest                   16 passed
    uv run ruff check src tools tests  exit 0
    uv run mypy src                 exit 0

干净环境验收仍需执行 uv sync --locked、corepack pnpm install --frozen-lockfile --ignore-scripts 和上述检查；由于 pnpm 12 的安全策略会拒绝未批准的 esbuild install script，本项目不依赖该脚本，检查阶段使用 --ignore-scripts，需要实际打包时另行记录批准依据。
