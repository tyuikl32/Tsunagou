# T05 项目初始化、根目录与范围模型

状态：已规划，未实施。负责人：tyuikl32；开发平台：Codex。

## 目标与交付

- projects实体/仓储/public ports
- 项目中心目录与配置层
- 路径身份/交集/绑定测试

## 前置依赖

T04。父任务只分组；meta.depends_on 是项目约定，Trellis 不自动调度。开始前检查依赖产物与验收证据。

## 范围

- 初始化已有Git协调仓库，创建project/lineage/replica和genesis计划，未commit可active
- 实现named roots/repositories、本机binding、physical identity、case/link规则
- 实现PathRule交并、user ceiling、config provenance和scoped conditions/blockers
- 实现项目注册/惰性加载与只读诊断，禁止全局目录成为唯一协作存储

## 验收标准

- [ ] 多文件夹跨仓库可登记且共享文件不泄露绝对路径
- [ ] 别名/嵌套root/Windows junction不能扩大权限
- [ ] 单root故障不阻塞无关动作
- [ ] unanchored允许普通协作，init从第一步有持久化

## 不包含

不增加 Web UI、远程认证、隐含认知推断或 daemon Git 写操作；不改变用户已确认权限边界。其他模块只能经 public ports 接入。涉及宿主的真实能力不以模拟通过代替。
