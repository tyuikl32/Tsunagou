# T02 四宿主与MCP可行性探针

> 2026-09-20：按用户要求关闭旧计划并归档。保留原分项完成记录，不表示独立成品已交付。 当前执行入口：[M1 路线图](../../../../../docs/implementation/roadmap.md)。

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- docs/research/host-matrix.md
- tools/conformance/probes/<host>/
- 脱敏身份生命周期与MCP验证记录

## 前置依赖

无，可作为起点。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 核对四宿主官方资料、已安装或可获取版本，确认目标Harness而非模型API
- 逐宿主验证同目录双session、resume、compact、new、clear、fork和安装profile标识
- 验证typed tools、共享项目MCP鉴权、stdio转发、token私有交付；锁定Python/TS官方SDK兼容API
- 记录wake/gate/presented/launch/stop增强实测值，给出正式支持版本窗或明确阻断原因

## 验收标准

- [x] 11项共同基线逐项有证据状态，未知不填supported
- [x] 身份连续性无法证明则不ready，不用cwd/PID/LLM自报替代
- [x] 两个宿主连接共享服务但不能共享principal（Codex app-server同服务双thread证明独立身份；bridge token隔离仍留为T17实测门槛）
- [x] 所有probe日志无token/raw conversation ID/私有transcript；失败不被隐藏

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
