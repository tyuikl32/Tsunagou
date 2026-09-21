# R1 协议与独立安装入口

状态：planning（第一轮实现已落地，完整 Schema/版本门禁仍待验收）。负责人：tyuikl32；平台：Codex；优先级：P0。

上级：[M1](../09-20-tsunagou-m1/prd.md)。前置：无。历史责任关联：T01, T03, T16（已归档，不作为启动依赖）。

范围来源：[独立运行实施方案](../../../docs/standalone/implementation-plan.md)、[当前缺口](../../../docs/standalone/status-and-gaps.md)、[路线图](../../../docs/implementation/roadmap.md)。多宿主正式认证和研究实验不作为本任务关闭条件。

## 交付内容

- 可独立安装的 wheel，内含 registry、Schema、OpenAPI，读取不依赖源码目录
- M1 命令及查询的具体 request/response DTO、生成校验器和协议版本映射
- REST 与 flat 入口规范化到同一 dispatcher；统一 RFC9457 错误和 revision 约定

## 验收条件

- [ ] wheel 在临时 venv、源码目录以外可导入并构建 application；缺资源不依赖 editable install 补救
- [ ] M1 接口字段有具体类型，optional/required 正确；未知字段、类型、协议和 digest 在 handler 前拒绝
- [ ] REST 与 flat 对同一目标生成等价规范命令；不允许 body/path 冲突选择另一个对象
- [ ] 受版本保护的修改缺 revision 返回 428、旧 revision 返回 412；协议错误不产生业务写入
- [ ] 相同源重复生成无差异；当前及确切 N-1 映射有正反 fixtures，不支持的版本明确拒绝

## 实施边界

保持主 Agent 控制 Git、用户重大确认、逐会话身份和领域所有权。代码只维护结构、状态、范围和版本不变量，语义协调由主 Agent 完成。不得返回占位成功、绕开所有权检查或伪造宿主 supported 状态。

文件责任见 [design](design.md)，执行和交接见 [implement](implement.md)。公共变更同步实施方案、Schema/registry、fixtures 与用户文档。
