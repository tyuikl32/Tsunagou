# 文档设计

新增implementation/build-guide、directory-layout、coordination-walkthrough、references、cli-contract以及overview/subagent-guide和cli-http-manual。现有protocol、command-catalog、data-model和D/E决策是语义来源；新指南解释和细化，不替换它们。

对CLI已有命令树但缺user授权映射的动作明确标注入口限制，不能暗中增加U权限。子Agent接入复用worker ticket、session enroll、probe和独立凭据，不新建join业务协议。CLI参数是既定动作的用户外壳，集中在cli-contract定义并标计划状态。

核验官方URL可访问性，并阅读支持关键约定的段落；记录链接核验与依赖/宿主兼容测试的区别。给相关产品任务添加新文档上下文，不开启产品实施。
