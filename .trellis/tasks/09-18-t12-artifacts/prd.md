# T12 领域授权附件与内容寻址存储

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- upload intent/bytes/finalize与blob目录
- 各模块ArtifactRef授权接口
- promote与共享导出规则

## 前置依赖

T06, T04。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 实现大小受限流式上传、临时文件与SHA256/length finalize
- 引用归领域拥有，read始终检查domain ref和recipient
- 实现默认local及main/user显式project_shared promote
- 实现临时上传清理，禁止已final blob自动GC，错误路径脱敏

## 验收标准

- [x] 仅知hash不能读取，私信附件不因main身份自动提升（必须持有 ArtifactRef、recipient 和领域授权）
- [x] 截断/篡改/重复上传结果正确（size limit、SHA-256 finalize 和内容寻址去重）
- [x] no-auto-GC和checkpoint export白名单可验证
- [x] 文件I/O不在SQLite写事务中（上传/rename 使用独立文件流程）

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
