# T01 工程骨架与可复现工具链

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- pyproject.toml、uv.lock、src/tsunagou骨架
- package.json、pnpm-workspace.yaml、pnpm-lock.yaml
- Windows开发引导与静态检查脚本

## 前置依赖

无，可作为起点。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 核验Python/Node/pnpm/TS版本窗口和注册表可用性，保存实际输出；冲突记录兼容矩阵
- 建立单Python distribution和六TS工作区包，生成目录标只读
- 安装并锁定FastAPI/数据库/CLI/Schema/测试依赖，MCP SDK精确版本接T02结论
- 加入Ruff/mypy/pytest/Vitest和import边界检查入口，制定源码运行命令

## 验收标准

- [ ] Windows干净环境可按锁文件安装和导入空应用
- [ ] Python域层不依赖框架，TS内部包使用workspace:*和strict/NodeNext
- [ ] 重装不改变锁文件；不把未实现产品演示写成已可运行
- [ ] 版本冲突有证据，无静默扩大已定窗口

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
