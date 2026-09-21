# T14 Checkpoint、Git锚点与共享状态恢复

> 2026-09-20：按用户要求关闭旧计划并归档。保留原分项完成记录，不表示独立成品已交付。 当前执行入口：[M1 路线图](../../../../../docs/implementation/roadmap.md)。

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- 模块export/import profile与checkpoint format
- 物化barrier/只读anchor discovery
- clone/divergence恢复测试

## 前置依赖

T07, T08, T10, T11, T12。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 实现排序NDJSON/manifest/parent digest、staging/flush/replace与watermark
- 实现heads/tags可达commit字节核验，排除remote/reflog/unreachable
- 实现各模块共享白名单导出，不含token/Grant/Lease/job claim/私信
- 实现同lineage三方消歧、未来format只读、备份与迁移核验

## 验收标准

- [x] Windows rename/崩溃各窗口可恢复且hash稳定（同卷 staging、逐文件 replace、manifest digest 验证）
- [x] SQLite事实不被物化失败回滚（checkpoint 物化独立于 SQLite 写事务）
- [x] 同实体冲突不自动合并，sealed不混合（`merge_lineage`）
- [x] 本机anchor和main_reported远端证据明确不同（`GitAnchor.status` 保持 local_verified）

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
