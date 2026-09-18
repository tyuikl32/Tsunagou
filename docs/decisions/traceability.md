# 决策到实施的追溯表

历史原稿保留完整问答，新规范给出单一执行解释。本表用于检查最近一轮 Plan 知识是否真正落到模块和任务。

| 已确认决定 | 当前规范落点 | 实施任务 |
|---|---|---|
| D161 无状态流程层 | architecture、lifecycle；不新增领域表 | T01、T13、T15 |
| D162 完成即时生效与异步checkpoint | lifecycle、projects/durability模块 | T14、T15、T23 |
| D163 本机heads/tags可达锚点 | durability、workspaces | T11、T14 |
| D164 未锚定与恢复性/最后副本边界 | durability、command-catalog | T14、T15 |
| D165 惰性加载后常驻 | architecture、durability | T04、T05 |
| D166 sealed lineage不合并 | durability、lifecycle | T14、T15 |
| D167 只做恢复重置，fork延后 | product、lifecycle、command-catalog | T15 |
| D168 main按范围处置unknown | durability、OperationResolution | T04、T15 |
| D169 语义重大性main判断，固定user-only | principles、projects、command-catalog | T06、T15、T16 |
| D170 本机公共REST | protocol、command-catalog | T03、T16 |
| D171 项目共享MCP、逐连接身份 | protocol、adapters | T02、T16、T17 |
| D172 reset后unassigned与无旧授权 | lifecycle、agents、durability | T15、T23 |
| D173 本机内容寻址附件 | protocol、durability | T12 |
| D174 字节与领域引用权限分离 | architecture、durability | T12、T14 |
| D175 首发blob无自动GC | durability | T12、T14 |
| D176 单read transaction黑板 | architecture、runtime-prompts | T16 |
| D177 最小注入、详情工具读取 | runtime-prompts、adapters | T16、T17–T21 |
| D178 core版本化提示 | runtime-prompts | T16、T17 |
| D179 对话呈现、CLI/HTTP control提交 | runtime-walkthrough、command-catalog | T15、T16 |
| D180 无宿主user-role授权增强 | adapters、projects | T06、T16 |
| D181 main呈现与CLI查询，无系统通知 | runtime-prompts、command-catalog | T07、T16 |
| D182 ZCode首发验收后置 | release-gates、roadmap、host-matrix、首发验收执行单 | T20、T23、T24 |

重要的早期边界也已贯穿规范：本机首发与Python后端；三个首发宿主正式共同基线，ZCode后置；所有Git写操作归main；初始化即项目内持久化；主子身份/Attempt所有权分离；用户不答不超时；父子任务不隐式门禁/级联；机械代码不作复杂业务语义裁决；减少强制用户决策；Web和远程认证延后。

本轮新增的实现默认与消歧详见 [E01–E27](engineering-resolutions.md)，不得把这些工程推导表述为新的用户选择。完整当前入口：[实施指导](../implementation/README.md)。
