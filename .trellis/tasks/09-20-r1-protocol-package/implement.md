# R1 实施步骤与交接

先读 [PRD](prd.md)、[design](design.md) 和 implement.jsonl。以下拆自独立成品方案，不表示已经修改代码。

## 启动

本任务可首先启动。

```powershell
python .trellis/scripts/task.py validate .trellis/tasks/09-20-r1-protocol-package
python .trellis/scripts/task.py start .trellis/tasks/09-20-r1-protocol-package
```

## 实施顺序

最小故障：wheel缺少registry；公开Schema、手写PAYLOAD_FIELDS和handler参数不一致；CLI调用`protocol_version=1/schema_digest=sha256:x`仍通过。

实施：

1. 将 registry、所有实际使用的Schema及OpenAPI作为包内资源构建，使用 `importlib.resources` 定位。修改 `pyproject.toml` 和所有 `parents[3]/protocol` 读取处，不能依赖cwd或源码checkout。
2. 修复 codegen：以显式 Schema为DTO真相；Markdown目录用作权限/路由登记的校验输入。当前生成器去掉`?`后又把全部字段设为required，复杂字段生成`{}`；这些必须改掉。不要运行旧生成器覆盖已补完整的Schema。
3. 首先补齐 M1 命令的 request/response/查询Schema，精确区分path参数、payload、envelope执行上下文。`task.create`返回draft，不含创建时自动ready/publish。
4. 修复`PAYLOAD_FIELDS`与Schema分叉：由同一规范生成校验器和MCP工具。flat compatibility入口规范化task_id等路径参数后进入同dispatcher，不拥有另一种业务语义。
5. 落实协议/digest检查和RFC9457错误；新增主对象更新必须If-Match，保持原设计的401/403/409/412/428区分。
6. 生成当前bundle及确切N-1映射；未支持的旧格式明确拒绝，不写“兼容”后直接忽略版本。

出口：安装到临时venv，cd到别处仍能构建application；错误版本/未知字段/缺revision在任何变更前失败；生成DTO有具体字段类型。此时尚不能声称完整协作可用。

## 验证与调试

1. 执行已有协议/fixture 检查与相关 Python/TS 测试，新增 optional、未知字段、path 冲突和版本拒绝案例。
2. 按调试执行单 A5 的隔离安装步骤定位现状；修复后在全新 venv 验证包资源，从临时 cwd 构建入口。
3. 对同一业务输入分别走 REST 和 flat，断言规范命令、错误和版本行为相同。不得用仅导入 Python 类的测试替代入口契约。

相关检查入口：

```powershell
uv run python -m pytest -q
corepack pnpm run check
corepack pnpm exec vitest run
python tools/docs/validate_docs.py
```

按实际变更运行对应 lint/type/schema 检查。本轮仅建任务，以上不是已通过的实现验收记录。

旧审计器若因协议变化不能运行，需迁移行为断言到正式入口测试，不能删除失败项后声称完成。

## 交接记录

- [ ] PRD 逐项通过，记录真实命令、退出码、公开查询和数据库事实。
- [ ] 公共接口同步 Schema、registry、生成类型、fixtures 与操作文档。
- [ ] 拒绝用例零部分写入；持久化改动经过重启验证。
- [ ] 记录修改文件、兼容处理、后继依赖和剩余范围，清除成功占位。
- [ ] 验收通过后更新任务/机器计划；按用户授权处理 Git，不自动提交或发布。

实际实现结果（2026-09-21）：Python wheel 已包含 `tsunagou.protocol_data` registry/schema 资源；bridge-server 构建时复制 registry 到 `dist/../protocol/registry/commands.json`，运行时优先读取包内资源。`corepack pnpm --filter @tsunagou/bridge-server run build`、`check` 和 `npm pack` 通过；临时目录解包后执行 `npm install --omit=dev`，再从源码树外启动 `dist/server.js`，未出现 digest 资源缺失。M1 全量 Schema、N-1 映射和完整协议矩阵仍未关闭，因此任务保持 planning。
