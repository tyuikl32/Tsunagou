# JSON 线格式与跨语言类型约定

> 核对日期：2026-09-17。
> 状态：已确认选择 A（统一实用型 profile）。

## 标准核对

- RFC 8259 指出，JSON 实现能精确一致处理的整数范围是 `[-(2^53)+1, (2^53)-1]`；JavaScript `number` 不能安全表示所有 SQLite signed int64。
- RFC 3339 定义 Internet 时间戳，可使用 `Z` 明确 UTC；小数秒精度由协议进一步限定。
- RFC 9562 的 UUID 文本允许大小写；UUIDv7 使用 Unix epoch 毫秒放在高 48 位。本项目可进一步规定统一小写，以消除等价文本。
- JSON object 成员名应唯一；重复 key 在不同 parser 中行为不可预测，因此协议边界必须拒绝重复 key。

来源：

- [RFC 8259: JSON](https://www.rfc-editor.org/rfc/rfc8259.html)
- [RFC 3339: Date and Time on the Internet](https://www.rfc-editor.org/rfc/rfc3339.html)
- [RFC 9562: UUIDs](https://www.rfc-editor.org/rfc/rfc9562.html)

## 选项

| 选项 | Profile | 优点 | 代价与风险 |
|---|---|---|---|
| A（推荐） | 全协议 `snake_case`；revision/sequence 使用上限为 `2^53-1` 的 JSON integer；UTC 毫秒时间 | Python/TS/schema/files 无别名层；可直接比较和排序；对本地项目容量足够 | 数据库 int64 需加应用/约束上限；不能宣称协议支持完整 uint64 |
| B | REST/TS 使用 `camelCase`，Python/共享文件使用 `snake_case`；其余同 A | Web 开发生态常见；TS 属性更惯用 | alias/codegen/JCS 映射增多；REST、MCP、Git 文件不再同形，容易产生哈希差异 |
| C | 全协议 `snake_case`；revision/sequence 使用十进制字符串；时间允许任意 RFC 3339 offset/精度 | 可表达完整 64 位计数器；接受外部时间更宽松 | 每个客户端都需字符串数值比较/解析；规范化和测试面更大；可观察文本不统一 |

## 推荐 A：字段与文本

- REST、MCP tools、SSE data、JSON snapshots、NDJSON events、OpenAPI 和生成的 TS 类型全部使用 ASCII `snake_case` property names。
- enum wire values 使用小写 `snake_case`，一旦发布不得重命名；展示文案是独立本地化/人类字段，不能作为状态判断。
- schema/type/command/error code 使用稳定 ASCII 标识；自然语言只进入明确命名的 `summary`、`description`、`rationale` 等字段。
- JSON 编码固定 UTF-8、无 BOM；生成器不输出重复 key、NaN、Infinity 或负零。解析器在 schema validation 前拒绝重复 key 和非法 Unicode surrogate。
- 普通传输 JSON 不要求 property 排序；需要 hash/签名比较时先用 RFC 8785 JCS canonicalize，不能直接 hash 原始字节。

## ID、hash 与 URI

- 所有 UUID 在 wire 上使用 36 字符、小写、带连字符的 canonical text；ID schema 同时验证 UUID 版本，领域实体必须为 v7。
- 特殊 nil/max UUID 不作为正常实体 ID。测试 fixtures 可使用固定 v7 值，但不能绕过版本验证。
- SHA-256 文本统一为 `sha256:<64 lowercase hex>`；字段名明确区分 `content_hash`、`request_hash`、`checkpoint_hash`，不使用无类型的 `hash`。
- 资源引用使用已有 `fs://{root_id}/{relative_path}` 等 typed URI；JSON 不把本机绝对路径伪装成跨机器资源 ID。

## 时间与时长

- 所有 instant wire 值使用固定 UTC RFC 3339：`YYYY-MM-DDTHH:mm:ss.sssZ`，大写 `T/Z`、恰好三位毫秒，不接受 local time、`-00:00` 或其他 offset。
- 服务端解析外部时间后先转 UTC/毫秒再保存；精度截断规则固定为向下截断，不四舍五入到未来。服务端生成的事实时间优先于客户端声明时间。
- SQLite 保存 UTC epoch milliseconds integer；Pydantic/TS boundary serializer 负责固定文本。时间戳只表达事实时间，不承担 revision/event ordering。
- 时长、timeout、lease TTL 在 JSON 中用非负 integer 毫秒并以 `_ms` 结尾；绝对 deadline 使用 `_at` 时间戳。容量统一 bytes 并以 `_bytes` 结尾。

## 数字

- revision、project event sequence、execution/authority/runtime epoch、attempt number、计数和字节值使用 JSON integer，范围 `0..9007199254740991`；数据库和 domain 层都验证上限。
- 金额、任意精度小数和可能超出安全整数的外部值使用带明确格式的十进制字符串，不能进入通用 number 字段。首版核心领域不定义金额。
- confidence 不使用 0 到 1 浮点；继续使用受控 enum。比例/实验统计允许 finite JSON number，但原始计数必须保留，报告层明确计算方法。

## absent、null 与更新

- property 缺失表示“schema 允许省略且调用方未提供/服务端未投影”；`null` 只在 schema 明确包含 null 时表示一个领域上有意义的空值。
- “未知”“尚未计算”“不适用”“被清除”不能都依赖 null；需要区分时使用状态 enum 或独立字段。
- mutation 使用 action-specific payload，不采用通用 JSON Merge Patch，因此省略字段不会被解释为删除。清除可空值使用显式 action 或 schema 明确的 null。
- response 可以新增 optional 字段；客户端 v1 reader 忽略未知 property，但未知 enum 必须进入 `unknown` 处理/升级错误，不能映射为现有值。

## Schema/codegen 检查

- schema lint 阻止 camelCase property、无单位数值、无最大值计数器、未约束 UUID/hash/time string 和未声明 null 的 nullable 输出。
- Python/TypeScript fixtures 必须往返保持同一 JCS/hash；覆盖最大安全整数、毫秒边界、重复 key、非法 UUID case/version、offset timestamp 和 unknown enum。
- Pydantic 内部字段名等于 wire 名，不使用 alias generator。TypeScript generator 保留原 property 名，不做运行时 rename。

## 后续细化

- list pagination、sort key 与 cursor 编码。
- 每类 URI 的 schema 和 path percent-encoding 规则。
- 自然语言字段的长度、Markdown/plain-text 和内容采样限制。
