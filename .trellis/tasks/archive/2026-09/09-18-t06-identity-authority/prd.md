# T06 会话身份、最小认证、Grant与主权限

> 2026-09-20：按用户要求关闭旧计划并归档。保留原分项完成记录，不表示独立成品已交付。 当前执行入口：[M1 路线图](../../../../../docs/implementation/roadmap.md)。

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- agents接入/认证/public ports
- 五类Grant与CommandPolicy执行器
- 最小control/session私有凭据存储

## 前置依赖

T05, T02。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 实现installation+conversation keyed digest、ticket原子兑换、degraded/ready与probe快照
- 实现32字节opaque token哈希存储、私有交付、rebind和secret脱敏
- 实现Connection nonce CAS及commit前epoch fencing、单Agent单非终态Session
- 实现user-only任命撤销、main-authority、五Grant typed scope与权限矩阵

## 验收标准

- [x] 子Agent不能任命主Agent或操作其他Attempt（user-only appoint 与 exact task/attempt grant）
- [x] 并发兑换/重连无重复身份，token交付丢失走rebind（单次 ticket、connection epoch CAS 语义）
- [x] baseline缺失仅diagnostic，raw ID/token不进共享历史或模型（degraded snapshot 与 public_snapshot 脱敏）
- [x] 无OAuth/keyring/refresh体系；Full Access防护范围如实说明（opaque token 哈希存储）

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。

## 本轮补充验收

- [x] 用户attach两个会话产生独立worker身份；宿主内置subagent不自动视为正式成员；接入不授任务执行权。
