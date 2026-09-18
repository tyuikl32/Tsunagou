# 配置作用域、优先级与秘密边界

> 核对日期：2026-09-17。
> 状态：已确认选择 A（按作用域分层配置）。

## 事实与既有约束

- Pydantic Settings 支持自定义 source 与 TOML source，但其默认“高优先级覆盖低优先级”不表达权限交集、显式拒绝优先和只能收紧等项目规则，必须增加项目自己的合并器。
- Pydantic Settings 的 TOML 多文件默认浅合并；虽然可启用 deep merge，本项目仍需逐字段 scope/merge policy，不能把通用 deep merge 当成权限语义。
- `platformdirs` 提供跨平台 user config/state/log 目录；项目已经确认用户级目录只承担 daemon 发现、runtime 注册和项目索引，不能成为项目协作状态的唯一位置。
- Python `tomllib` 只读 TOML；需要保持人工文件注释/格式时使用已选候选 `tomlkit`，机器快照继续使用 JSON/JCS，而不反向写成人工 TOML。
- `.tsunagou/` 已确定分为 Git 共享层和忽略的 `local/`，跨仓库使用具名 root 与 `fs://` URI。

来源：

- [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [platformdirs API](https://platformdirs.readthedocs.io/en/latest/api.html)
- [Python 3.13 tomllib](https://docs.python.org/3.13/library/tomllib.html)

## 选项

| 选项 | 方案 | 优点 | 代价与风险 |
|---|---|---|---|
| A（推荐） | 按作用域拆分 shared project TOML、project local TOML、user TOML；动态状态留 SQLite | Git 可审查且跨机器；绝对路径和本机能力不污染共享层；可对权限使用专门合并规则 | 文件较多；必须提供 `config explain`/doctor 说明每个最终值来源 |
| B | 所有非秘密配置放 `.tsunagou/project.toml` | 心智模型和备份最简单 | 外部仓库绝对路径、adapter 路径和机器能力会进入 Git；跨机器 clone 后容易失效或泄露环境信息 |
| C | SQLite 为配置真相，TOML 仅作导入导出 | 动态更新和 revision 控制直接；文件结构较少 | Git diff 难审查；新 clone 恢复和手工编辑差；与已确认的人工 TOML/共享层目标不契合 |

## 推荐 A 的文件作用域

| 位置 | 所有权与内容 | Git/敏感性 |
|---|---|---|
| 内建 defaults | 超时、容量、日志等保守默认值 | 随代码版本 |
| 用户 `config.toml` | daemon/CLI 默认、日志/OTLP、默认 checkout、非秘密网络与 UX 设置 | platformdirs user config，不进项目 Git |
| `.tsunagou/project.toml` | project/lineage identity、schema version、逻辑 roots、项目策略、权限上限、driver/adapter 允许范围、保留与评估策略 | 提交 Git，不得含绝对机密或 token |
| `.tsunagou/local/config.toml` | root ID 到本机绝对路径、external 环境、adapter executable/IDE 绑定、本机能力覆盖和非秘密端点 | Git 忽略，仅当前用户可写 |
| SQLite | Task/Agent/Contract/Lease/Operation 等动态状态及已导入配置 revision | Git 忽略；当前运行代次权威 |
| credential store | control token、refresh token、服务秘密和凭据引用 | 不进入 TOML、环境、CLI 或日志 |

协调仓库内 root 可以用相对 locator；外部仓库只在共享 TOML 中保存稳定 `root_id`、用途、期望 repo identity/remote fingerprint 等可移植事实，本机绝对路径在 local binding 中解析。

## 合并与优先级

不采用全局统一覆盖顺序。每个 setting 在 schema metadata 中声明 `scope`、`merge_strategy`、`reloadability` 和 `sensitive`。

### 启动与操作偏好

- 普通 daemon/CLI 操作设置按“显式 CLI 参数 > allowlist 环境变量 > user TOML > 内建默认值”解析。
- 环境变量统一使用 `TSUNAGOU_` 前缀，只允许文档列出的启动定位、日志和测试设置；不自动加载 `.env` 文件。
- project selector、endpoint 和单次 timeout 可以由 CLI 覆盖；覆盖只影响当前客户端调用，不能持久改变项目策略。

### 项目策略与权限

- project TOML 是共享声明；导入后以 SQLite 中带 revision/hash 的配置聚合作为当前运行真相，并按既定 checkpoint/fast-forward/divergence 规则物化和导入。
- 影响权限上限、Full Access、driver 允许范围、保留或审计的设置必须通过有权限的应用命令修改，再由 outbox 写回 TOML；不能被 env、user TOML 或普通 CLI flag 覆盖。
- local config 只能绑定逻辑 root/adapter/environment，或把本机能力和权限进一步收紧。任何扩大 shared 上限的值在 validation 阶段拒绝。
- deny 使用集合并集，allow/capability limit 使用交集，数值上限取更严格值。只有用户授权的项目命令可以扩大 shared policy。

### 未知与冲突

- 所有文件含 `schema_version`。项目拥有的 section 默认拒绝未知 key；未来 adapter 扩展只能进入已登记、带独立 schema 的 namespaced section。
- 配置错误输出文件、TOML path、无敏感值的实际来源和期望规则；不自动猜测或忽略拼写错误。
- 外部编辑 project TOML 只有可验证 checkpoint 后继时按既有 fast-forward 规则导入；分叉/未 checkpoint 本机更改时进入 diverged，不热覆盖。
- local config 改变 root binding、driver capability 或 adapter path 时先验证并创建配置 revision；影响 running 任务则触发已确定的 re-evaluate/migration_required，不原地偷换环境。

## 读取、写入与 reload

- Pydantic v2 models 负责字段验证；Pydantic Settings 只聚合启动层 source，项目自己的 scoped merge service 负责项目规则。
- `tomllib`/Pydantic TOML source 用于读取；`tomlkit` 只写项目拥有的文档/托管 section并保留注释。写入使用同目录临时文件、flush 和原子替换。
- user config 默认只在 daemon 启动时加载；`daemon reload` 只应用声明为 reloadable 的日志/OTLP/轮询参数，其他改变返回 restart required。
- project/shared/local config 文件变化只产生 reload/import job；job 完整验证和计算 diff 后一次提交，不允许观察到半套配置。
- `tsunagou config show --effective --provenance` 展示脱敏后的最终值、来源和合并规则；`config validate` 不修改状态；实际持久修改使用对应 domain 命令，而不是通用 `config set` 绕过权限。

## 秘密处理

- token、refresh secret、join ticket、provider/API credential 不允许出现在任何 TOML、命令参数、`TSUNAGOU_*` 环境变量或 JSON 输出。
- 配置只能保存 opaque credential reference；实际秘密来自 OS credential store，缺失时使用既定的当前用户可读 local 降级文件。
- 由于 Agent 可在 Full Access 下运行，环境变量不被视为安全秘密通道；daemon 启动子进程时构造 allowlist environment，不继承不相关秘密。

## 待后续细化

- 每个具体 setting 的字段表、默认值、scope、merge strategy 与 reloadability。
- `project.toml`/`local/config.toml` 完整 schema 和示例。
- runtime registry、project index 和 endpoint manifest 是 config 还是 state 的逐文件定义。
