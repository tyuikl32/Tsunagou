# 细化文档与操作说明

## 目标

给后续Agent提供可按顺序实施的搭建步骤、假想目录和官方知识入口；让用户理解子Agent如何加入、承担任务、协商和恢复；提供与既有协议一致的CLI/HTTP手册。

## 验收

- [x] 实施步骤明确前置、文件、工作顺序、验收和对应T任务，区分现有与待建内容。
- [x] 详细目录标明所有权、生成物、运行数据和禁止依赖。
- [x] 外部链接来自官方资料并记录核验范围，不伪称依赖/宿主已兼容。
- [x] overview包含用户接入多个子Agent、主子职责和加入后的任务流程。
- [x] 手册覆盖CLI常用操作、HTTP架构、请求示例、认证、revision/幂等/异步和错误处置。
- [x] 无新增超级权限、隐含用户确认、Agent身份混用或第二套接口名字。
- [x] 索引、Trellis上下文与相关实施任务同步；链接/hash/context检查通过。

## 验证记录

- `python tools/docs/validate_docs.py`：通过；177份Markdown、434个本地链接、24个实施任务、620条任务上下文，依赖无环，D161-D181完整。
- `python ./.trellis/scripts/task.py validate <task>`：26个活动任务全部通过；当前任务implement/check各16条上下文。
- `git diff --check`：通过，仅报告既有roadmap行尾格式提示。
