# Schema 与客户端代码生成流水线

> 核对日期：2026-09-17。
> 状态：已确认选择 A（单一 Python 原子 codegen 编排器）。

## 工具能力与风险

- `datamodel-code-generator` 0.82 支持 JSON Schema 输入、Pydantic v2 BaseModel 输出、Python/Pydantic target、标准集合和 union 语法。
- `openapi-typescript` 7 从 OpenAPI 3.0/3.1 生成 TypeScript `paths/components` 类型；`openapi-fetch` 是读取这些类型的轻量 fetch runtime，不需要再生成手写风格 client methods。
- `json-schema-to-typescript` 16 可以处理 `$ref`、`$defs` 等常见结构，但内部 schema model 仍基于 draft-04；部分 2019-09/2020-12 关键词仅部分支持或忽略。生成的 TS 类型不是运行时 validator。
- `json-schema-to-typescript --imports` 仍标为 experimental。首版不应让协议正确性依赖该模式。

来源：

- [datamodel-code-generator README](https://github.com/koxudaxi/datamodel-code-generator)
- [openapi-typescript CLI](https://openapi-ts.dev/cli)
- [openapi-fetch](https://openapi-ts.dev/openapi-fetch/)
- [json-schema-to-typescript README](https://github.com/bcherny/json-schema-to-typescript)

## 选项

| 选项 | 编排方案 | 优点 | 代价与风险 |
|---|---|---|---|
| A（推荐） | 一个 Python `tools.codegen` 编排器依次调用锁定的 Python/Node CLI，统一校验、staging、manifest 和 `--check` | Windows/CI 只有一个入口；失败原子；能统一检查 2020-12 子集、bundle digest 和跨语言 fixtures | 编排器要维护少量 subprocess、规范化和 manifest 代码 |
| B | Python、TypeScript、OpenAPI 各自维护 package scripts/PowerShell/bash | 每个生态使用原生命令，初始实现快 | 顺序、环境和清理分散；跨平台脚本漂移；部分生成成功时容易留下混合产物 |
| C | 自建单一 JSON Schema -> Python/TS/OpenAPI 生成器 | 完全控制确定性和协议子集 | 实际是在维护编译器；oneOf/ref/validation 语义风险远高于项目收益 |

## 推荐 A：唯一入口

```text
uv run --locked python -m tools.codegen generate
uv run --locked python -m tools.codegen check
uv run --locked python -m tools.codegen lint
uv run --locked python -m tools.codegen fixtures
```

- Python module 是跨平台 orchestration entry；它通过 argv 数组调用 `datamodel-codegen` 和 `pnpm exec ...`，不拼接 shell 字符串。
- 执行前验证 Python/Node/pnpm、`uv.lock`/`pnpm-lock.yaml`、generator versions 和工作目录。Node 依赖必须先由 `pnpm install --frozen-lockfile` 准备。
- `generate` 先写 OS temp 下的完整 staging tree，全部步骤成功、manifest/hash 验证通过后才逐文件原子替换目标；失败不改变已提交产物。
- `check` 在临时目录重生成并做内容比较，不修改工作树；差异输出 added/removed/changed 文件和首个 unified diff，CI 使用该命令。
- 所有生成器禁止联网和 remote `$ref`；只允许 bundle manifest 中的本地 canonical schema IDs。缺失 ref 立即失败。

## 固定阶段

1. **Discover**：按 `protocol/bundle.source.json` 的显式文件表读取 schema，不依赖 filesystem glob 顺序。
2. **Schema lint**：验证 JSON、重复 key、draft `$schema`、canonical `$id`、命名/整数/时间 profile、ref closure 和允许的生成子集。
3. **Bundle**：JCS 计算每个 schema hash和 bundle digest，输出 `protocol/bundle.json`；已发布 `$id` 内容变更直接失败。
4. **Python models**：每个业务模块使用一个显式 aggregate root schema，生成一个模块文件，避免跨文件重复类名。
5. **TypeScript domain types**：从单一 deterministic aggregate bundle 生成 `protocol-ts` 的一个领域类型入口，不使用 experimental `--imports`。
6. **Runtime validation fixtures**：Python `jsonschema` Draft202012Validator 跑正反 fixtures，Pydantic 对适用 DTO 跑同一 fixtures。
7. **OpenAPI export**：导入 schema-only FastAPI app factory 并调用 `app.openapi()`，不打开数据库、凭据库、Git 或 worker；规范化后写固定 artifact。
8. **HTTP TypeScript**：`openapi-typescript` 从本地 OpenAPI JSON 生成类型，`openapi-fetch` 保持手写的薄 runtime wrapper。
9. **Format/typecheck**：Ruff format/check generated Python；Prettier/ESLint/`tsc --noEmit` 检查 TS；不让各生成器自行发现不同 formatter 配置。
10. **Manifest/conformance**：写 generation manifest，执行 Python/TS JCS round-trip、REST/MCP envelope 和 schema fixture conformance。

## Generator 固定边界

### Python Pydantic

- 使用 `datamodel-codegen --input <module-aggregate> --input-file-type jsonschema --output-model-type pydantic_v2.BaseModel --target-python-version 3.13 --use-standard-collections --use-union-operator`。
- 实际完整参数保存在版本控制的 `tools/codegen/config.toml`；编排器不把几十个 flags 散落在 CI 配置。
- 输出到 `src/tsunagou/generated/protocol/<module>.py`；生成模型只做协议边界 validation/serialization，领域实体不会继承 Pydantic model。
- 每个文件前缀固定 generated header，记录 tool/version、bundle digest、aggregate schema ID；不包含绝对路径或生成时间。

### TypeScript 领域类型

- 生成一个 `packages/protocol-ts/src/generated/protocol.ts`，显式关闭 const enum，启用 readonly/strict index signatures，并由项目固定 Prettier 统一格式。
- date-time、UUID 和 URI 在 TS 类型层仍是 string；使用 branded helper 只能存在于手写 wrapper，不能声称静态类型已经完成运行时验证。
- aggregate bundle 必须让所有 public definitions reachable/显式列出；不使用 experimental multi-file imports。
- 输出 header 记录 generator/version 和 bundle digest，不包含当前日期。

### OpenAPI 与 HTTP SDK

- OpenAPI artifact 固定为 `protocol/openapi/v1/openapi.json`；排序和清理仅处理不具语义的生成噪音，不改写 paths/schema 行为。
- 所有 operation 都有稳定唯一 `operation_id`；缺失、重复或未声明 response/error schema 阻止生成。
- `openapi-typescript` 输出 `packages/bridge-sdk/src/generated/http/schema.d.ts`；手写 `client.ts` 使用 `openapi-fetch`，负责 bearer、protocol version、trace、ETag/If-Match、RFC 9457 映射和 SSE fetch stream。
- 不生成每个 endpoint 的独立 runtime method layer，避免在 OpenAPI types 和 bridge SDK 之间再产生一套可漂移 API。

## 2020-12 生成子集门槛

- runtime JSON Schema 可使用完整 2020-12 validator，但“公开跨语言 DTO schema”只能使用 lint allowlist 中经三路验证的组合。
- 首个 allowlist 包括 object/properties/required/additionalProperties、array/items/min/max、string pattern/format/length、number/integer bounds、enum/const、`$defs`/JSON Pointer `$ref`、受测的 oneOf/anyOf/allOf。
- `$dynamicRef/$dynamicAnchor`、`unevaluatedProperties` 跨组合、dependentSchemas、复杂 conditional schema 和 generator 已知忽略的关键词默认禁止进入 public DTO。
- 如确需超出子集，变更必须同时加入最小正反 schema fixture、Python validation、Pydantic、TS compile-time assertions 和 generator issue/行为说明；无法等价表达时保持 opaque JSON 加运行时 validator，或更换生成工具后再公开。
- TS 类型只能证明编译期 shape；所有外部输入仍由 daemon 的 2020-12/Pydantic 边界校验，bridge 不独立决定协议合法性。

## 确定性与发布检查

- 生成输出统一 LF、UTF-8 无 BOM、稳定 header/sort；不含时间、用户名、绝对路径、临时目录或随机 ID。
- generation manifest 包含 input schema IDs/hashes、bundle digest、工具及版本、config hash、output paths/hashes 和 OpenAPI hash。
- Windows 阻塞检查至少运行 schema lint、generate check、fixtures、Python import/type validation、TS typecheck 和 generated source lint。
- generator 依赖升级必须作为独立变更提交，附 generated diff；若相同 schema 产生语义变化，执行 protocol compatibility review，不能归类为普通格式化。

## 后续细化

- `bundle.source.json`、aggregate schema 和 `config.toml` 的完整格式。
- 每个生成器的最终 flags，通过 spike 后锁定 golden output。
- schema subset lint 规则编号和 compatibility diff 分类算法。
