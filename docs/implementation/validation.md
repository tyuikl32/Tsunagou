# 验证、发布与完成标准

| 层次 | 必需检查 | 失败影响 |
|---|---|---|
| 架构 | domain纯度、跨模块public边界、表所有权、API不直连ORM | 阻止合并/发布 |
| 协议 | Schema subset、正反fixtures、JCS、UUID/time、双语言codegen零diff、OpenAPI | 阻止全部adapter交付 |
| 授权 | 每CommandPolicy允许/拒绝、主子越权、user-only、旧epoch、recipient | 阻止发布 |
| 状态机 | Task/Attempt/review、contract、Project、Operation转换 | 阻止发布 |
| 存储 | 真SQLite WAL、迁移备份、双writer、outbox/checkpoint崩溃恢复 | Windows阻断 |
| 路径/Git | drive/UNC/junction/symlink/case/重叠roots、只读Git、heads/tags锚点 | 对应平台/功能阻断 |
| 桥接 | 同一simulator+四宿主真机11项baseline | 无实测不宣称正式支持 |
| 端到端 | 认知→契约→任务、等待、继任、完成checkpoint失败、回退 | 阻止工程交付 |
| 实验 | A/B/C/D各≥5次、另一宿主复验、统一预算/质量 | 未达标不能宣称研究效果 |

使用真 SQLite 事务和临时 Git 仓库验证恢复，不用全部 mock 证明持久性。可注入 Clock/故障点验证 Lease、Job、backoff，避免长 sleep。属性测试覆盖 DAG、scope 交集、状态机和幂等。秘密哨兵穿过错误、access log、CLI JSON、OTel、checkpoint，不能泄露。

## 最低故障集合

1. DB commit 前/后杀进程；重试不丢、不重复领域事实。
2. 新 Connection 建立后旧请求到达 commit，必须拒绝。
3. 并发 claim 仅一个 owner。
4. Lease 过期而物理 Agent 仍运行；orphaned+残余风险，不伪称已停止。
5. push/SSE 断开后 pull 恢复；ACK 丢失不重复灌入正文。
6. 用户数天未确认；pending/blocked 持久存在，无关任务继续。
7. 契约内容/参与者变化，旧接受不能覆盖。
8. Git 外部效果发生但 receipt 丢失；unknown 而非盲重试。
9. completion checkpoint 失败；Project 仍 completed，归档受阻，repair 可用。
10. clone/rollback 不携带运行凭据，回退新 lineage unassigned。
11. manifest/blob 篡改、未来 format、路径逃逸、只读磁盘均明确诊断。
12. 私信/附件不能经黑板、审计、export 或仅凭 hash 扩大读取者。

## 发布与研究

首发从源码 checkout 运行，交付两套锁文件、版本矩阵、Schema/OpenAPI、生成客户端、迁移、四 adapter 安装说明、CLI runbook、故障与实验报告。Windows 固定基准与允许补丁回归必须通过；macOS/Linux 只测 smoke 就如实标 smoke。

工程交付和研究效果分别判断。A 单 Agent、B 多 Agent+Worktree、C 完整、D 无认知；每组≥5次，多 Agent≥3个，随机顺序、同预算/任务，再另一宿主复验。正确性100%，注入硬分歧检出≥95%、误阻塞≤5%；C对B干预/返工中位数改善≥30%、耗时≤+10%、可比token≤+25%。没有token观测标unavailable；未达标报告限制，不美化数据。

升级分别验证协议N/N-1、共享format和DB迁移；doctor/备份→迁移→probe→恢复，失败只读诊断，不自动downgrade。

## 每个任务的 Done

PRD验收有证据；design和最终实现一致；implement步骤记录结果；Schema/fixtures/文档同步；无跨模块写表或绕权；check上下文实际审查。不能用“已编码”代替真宿主实测和故障恢复。新增API不在command registry则启动/CI失败。

本轮文档任务只验证文档、链接、决策映射、任务依赖和上下文，不声称运行产品测试。
