# 关键外部知识与项目采用边界

核验日期：2026-09-18。下面全部是官方规范、官方文档或官方SDK仓库。通过直接HTTPS核对链接并读取相关主题；[核验记录](../research/reference-checks-2026-09-18.json)保存URL、响应、页面标题和检查范围。链接可访问不代表项目依赖或四宿主已集成通过。

优先级仍为用户决定→当前项目规范；外部框架示例不会自动成为本项目架构。实施时使用T01/T02锁定版本对应文档，尤其不要把SDK main分支README当作已安装稳定版本API。

## 工程与目录

| 官方资料 | 建议读的内容 | 本项目怎样使用/避免什么误用 |
|---|---|---|
| [PyPA：src layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) | 源码与项目根的导入差异 | T01采用src/tsunagou；测试安装后的包，不靠cwd碰巧import成功 |
| [uv：Working on projects](https://docs.astral.sh/uv/guides/projects/) | pyproject、虚拟环境、lock/sync/run | 一份uv.lock；不是每模块一个Python环境 |
| [pnpm：Workspace](https://pnpm.io/workspaces) | pnpm-workspace.yaml、workspace protocol | 内部依赖workspace:*，拒绝意外装到同名registry包 |
| [TypeScript：Modules reference](https://www.typescriptlang.org/docs/handbook/modules/reference.html) | NodeNext和package type | 项目明确ESM并strict；NodeNext本身不等于所有文件自动ESM |

## API、CLI与测试入口

| 官方资料 | 对应项目约定 | 注意 |
|---|---|---|
| [FastAPI：多文件应用](https://fastapi.tiangolo.com/tutorial/bigger-applications/) | APIRouter组合与依赖注入，T16 | 路由组织不授权router直写ORM |
| [FastAPI：Testing](https://fastapi.tiangolo.com/tutorial/testing/) | 请求/响应和依赖测试 | TestClient通过不能替代真SQLite/Git故障测试 |
| [Typer：教程](https://typer.tiangolo.com/tutorial/) | 用户命令分组、参数、帮助 | CLI是U入口，不通过读Agent token增加能力 |
| [RFC 9110：HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110) | 条件请求、If-Match、状态语义 | 本项目绑定主aggregate revision，并在事务内重验 |
| [RFC 9457：Problem Details](https://www.rfc-editor.org/rfc/rfc9457) | application/problem+json | 加项目稳定code/blockers；客户端不解析人类detail控制流程 |

## 数据、事务与迁移

| 官方资料 | 对应任务与采用方式 | 不应混淆 |
|---|---|---|
| [SQLite：WAL](https://www.sqlite.org/wal.html) | T04并发读+单writer、恢复 | WAL不是分布式数据库；文档说明共享内存机制不适合跨主机网络文件系统 |
| [SQLite：PRAGMA](https://www.sqlite.org/pragma.html) | 明确WAL/FULL/foreign_keys/busy_timeout | 依赖默认值不等于已启用所需约束 |
| [SQLAlchemy 2：事务](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html) | UoW注入、begin/commit/rollback边界 | ORM事务不能使Git或文件rename与SQLite一起原子 |
| [Alembic：教程](https://alembic.sqlalchemy.org/en/latest/tutorial.html) | 单线migration环境和revision | 自动生成迁移要审核，不自动downgrade修复业务数据 |

## 协议、规范化与身份

| 官方资料 | 对应项目约定 | 需验证的点 |
|---|---|---|
| [JSON Schema 2020-12](https://json-schema.org/draft/2020-12) | protocol/schemas是DTO唯一源 | required/null/未知字段、ref解析和生成器subset一致 |
| [RFC 8785：JCS](https://www.rfc-editor.org/rfc/rfc8785) | contract/scope/input digest规范化 | 不用各语言默认json.dumps或普通键排序冒充完整JCS |
| [RFC 9562：UUID](https://www.rfc-editor.org/rfc/rfc9562) | UUIDv7 ID/runtime_epoch | 时间有序不等于可推导权限或事件顺序；event_seq独立 |

## MCP与四宿主桥接

| 官方资料 | 对应项目约定 | 版本边界 |
|---|---|---|
| [MCP 2025-06-18：Transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) | Streamable HTTP多连接、stdio协议流 | 此链接是固定参考版本，不宣称它是当前最新版或已选择的协商版本 |
| [MCP 2025-06-18：Lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle) | 初始化、版本与能力交换 | Tsunagou collaboration_baseline_v1是自己的profile，不等于MCP capabilities |
| [官方Python SDK](https://github.com/modelcontextprotocol/python-sdk) | daemon承载MCP | T02锁定版本、ASGI/lifespan/session绑定方式后才写集成 |
| [官方TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk) | bridge客户端与必要stdio转发 | 当前文档可能含拆分包；不能预设旧单包导入路径仍有效 |

MCP传输认证规则必须随选定版本核验。Tsunagou自己的业务SSE高水位与MCP Streamable HTTP内部可能使用的SSE不是同一协议或同一endpoint；不能把`P/events:stream`直接当MCP传输。

四宿主官网/仓库和历史调查入口见[adapter研究](../history/2026-09-18-source/adapter_research.md)与[当前适配规范](adapters.md)。T02要逐宿主核验原生ID/生命周期/工具入口及官方URL，不用模型API文档替代Harness文档。宿主具体API未实测前保留unknown，不在本页给出猜测方法名。

## Git、测试与恢复证据

| 官方资料 | 项目对应场景 | 边界 |
|---|---|---|
| [Git：worktree](https://git-scm.com/docs/git-worktree) | 独立工作目录、主Agent创建/移除 | 文档说明命令能力，不授权daemon执行Git mutation |
| [Git：rev-list](https://git-scm.com/docs/git-rev-list) | 从指定refs遍历可达commit | 必须按项目规则限制heads/tags，不能无条件用--all扩大锚点范围 |
| [pytest：临时目录](https://docs.pytest.org/en/stable/how-to/tmp_path.html) | 临时真实SQLite/Git fixture | 不拿用户项目做故障注入 |
| [Hypothesis：状态测试](https://hypothesis.readthedocs.io/en/latest/stateful.html) | Task/Lease/Grant/幂等状态机 | 属性来自项目不变量，不能测试实现复制出来的同一逻辑 |

后续Agent引用新外部知识时，应记录“来源URL+版本/日期+支持哪条结论+不支持什么推断+实测任务”。只添加一串链接而不说明关联，不足以作为修改产品边界的依据。
