# 版本、Schema Bundle 与兼容协商

> 核对日期：2026-09-17。
> 状态：已确认选择 A（有界实时协议协商 + 独立格式迁移）。

## 参考与约束

- MCP 最新版本规范明确区分 protocol version 与 capability/extension，并在不支持版本时返回所支持版本。Tsunagou bridge 同时面对宿主 MCP 版本和自身协调协议，二者必须分开记录。
- JSON Schema 2020-12 的 `$schema` 标识 dialect，`$id` 为 schema resource 提供 canonical URI；该 URI 是身份，不一定是网络下载地址。
- SemVer 要求已发布版本内容不可原地改变；兼容新增使用 minor，不兼容 API 变化使用 major，兼容 bug fix 使用 patch。
- 已确认 `/api/v1`、schema-first、生成产物提交 Git、适配器测试版本窗、共享文件 migration 和失败只读模式。

来源：

- [MCP Versioning and Compatibility](https://modelcontextprotocol.io/specification/latest/basic/versioning)
- [JSON Schema 2020-12 Core](https://json-schema.org/draft/2020-12/json-schema-core)
- [Semantic Versioning 2.0.0](https://semver.org/)

## 选项

| 选项 | 兼容模型 | 优点 | 代价与风险 |
|---|---|---|---|
| A（推荐） | 产品统一发版；实时协议独立 major/minor 协商，daemon 支持 current 与 previous minor；schema bundle 精确 digest；共享格式独立前向迁移 | 旧 bridge 可短期共存；能力增强可协商；不会混淆代码、线协议与磁盘格式 | 需要保留 N-1 serializers/fixtures 和兼容投影，发布检查更严格 |
| B | daemon、CLI、adapter 和 schema 必须精确同版本 | 实现、诊断和测试最简单；无降级路径 | 任一源码更新都要求四适配器同步重启；真实 IDE/Harness 附着流程容易中断 |
| C | 支持多个 protocol major 和长期自动 down-conversion | 升级最平滑；可兼容很旧 adapter | 状态机和错误语义难以可靠降级；测试组合爆炸，不适合首版团队规模 |

## 推荐 A：四个版本平面

### 1. 产品发布版本

- Python core/CLI 与所有 workspace adapter 使用同一个 monorepo SemVer release，例如 `0.1.0`；发布清单记录 Git commit、锁文件和 schema bundle digest。
- 首个稳定发布前产品版本为 `0.y.z`，但仍遵守“已发布 artifact 不覆盖”的规则。正式承诺兼容后发布 `1.0.0`。
- adapter package manifest 同时记录自身 product version、支持的宿主版本窗和 Tsunagou protocol range；宿主兼容不能由产品 SemVer 推断。

### 2. 实时协调协议

- 协议版本为 `major.minor`，首个实现阶段从 `1.0` 开始；REST URL major 与 protocol major 对齐为 `/api/v1`，minor 不进入 URL。
- daemon 正式支持当前 minor N 和前一个 minor N-1；adapter 声明闭区间/离散 supported versions，双方选择最高共同版本。无交集则拒绝加入并返回 daemon/adapter 支持集合。
- enrollment/attach 握手提交 `adapter_product_version`、`adapter_protocol_versions`、`schema_bundle_digests`、host kind/version 和 probed capabilities。选中结果绑定 agent session、token family 和 capability snapshot。
- 每个后续 REST 请求发送 `Tsunagou-Protocol-Version`；必须等于 session negotiated version。MCP tool wrapper 把该值作为 bridge 元数据处理，不暴露给模型自由选择。
- 宿主 MCP/A2A/插件协议版本单独保存在 adapter diagnostic 中，只影响 bridge 实现和 capability probe，不等于 Tsunagou protocol version。

### 3. Schema bundle

- 每个 JSON Schema 都声明 draft 2020-12 `$schema` 和不可变 canonical `$id`，格式为 `urn:tsunagou:schema:<module>:<name>:<semver>`。
- 已发布 `$id` 的文件内容永不修改。任何内容变化产生新 schema SemVer 和 SHA-256；不能用 Git commit 偷换同一 ID。
- `protocol/bundle.json` 使用稳定排序列出 protocol version、每个 schema `$id`、relative path、content hash、generator versions 和 bundle hash。
- session 协商具体 protocol minor 后绑定对应 bundle digest。daemon 不接受“版本号相同但 bundle digest 未知”的正式 adapter；开发模式只能显式启用并标为 unsupported。
- generated Python/TypeScript/OpenAPI 文件头写 source schema IDs、bundle digest 和 generator version；CI 校验无漂移。

### 4. 项目共享格式

- `.tsunagou/project.toml`、checkpoint manifest、JSON snapshots 和 NDJSON segments 使用独立 `shared_format_version`，不能从 API/product version 推断。
- 新 daemon 保留同一 shared-format major 的全部已发布前向 migration 链和 golden fixtures；打开旧格式时先预检、backup/checkpoint，再迁移到当前 writer format。
- 遇到更高 minor/major 或未知 schema ID 时只读诊断，不让旧 daemon 写回或尝试“最佳猜测”。不支持的 major upgrade 必须由显式 `project upgrade` Operation 执行。
- old adapter 永不直接读写共享层，因此 adapter N-1 支持不会扩大磁盘格式兼容面。
- SQLite 使用独立 Alembic revision；发布后 migration 不删除或改写。共享格式、SQLite revision 与 product release 的映射记录在 release manifest。

## 演进规则

| 改动 | 协议版本 | 旧 minor 行为 |
|---|---|---|
| 新 optional response 字段或新独立 endpoint/tool | minor | N-1 投影省略新增字段/工具 |
| 新 optional request 字段且旧语义保持 | minor | N-1 不发送；server 使用旧默认 |
| 新 enum value | minor | 只在协商到新 minor时发送；N-1 projection 不得产生未知值 |
| 新 required 字段、删除/重命名、状态语义改变 | major | 不 down-convert；旧 major 拒绝 |
| 修正实现但 accepted instances/语义不变 | product/schema patch | protocol minor 不变 |
| 收紧 validation 导致旧合法请求失败 | minor 或 major | 必须通过兼容分析，不能当 patch |

- capability extensions 与 protocol version 分开协商。protocol version 表示基本线格式/语义，capability 表示该 host/session 实际可执行的增强功能。
- daemon 对 N-1 使用显式 versioned serializer/projector，不依赖“客户端应该忽略字段”作为唯一兼容机制。
- client 遇到未知 response property 可以忽略；未知 enum 仍按已确认规则报告升级/unsupported，不能映射为已有状态。

## 发布与兼容检查

- schema diff 分类为 additive、behavioral/breaking、metadata-only；分类不确定时按 breaking 处理并要求人工审查。
- 每次 release 对 current 与 N-1 bundle 跑 REST/MCP 双投影 conformance、四 adapter 模拟测试和 golden shared-format migrations。
- release manifest 列出 product version、protocol current/min、bundle digest、shared format current/min-readable、Alembic head、四宿主版本窗和手工 live-agent 验收记录。
- 删除 N-1 支持只能发生在 protocol minor release，必须先在 doctor/status 给出一整个已发布 minor 的 deprecation 信号。
- `daemon status` 和 adapter diagnostics 明确展示 negotiated version、bundle digest、capability snapshot、host support status 和任何降级功能。

## 后续细化

- attach/discover request/response 完整 schema 与 header 名称。
- versioned serializer 的代码目录和 OpenAPI current/N-1 artifact 生成方式。
- schema diff 工具、breaking-change allowlist 和 release manifest JSON Schema。
