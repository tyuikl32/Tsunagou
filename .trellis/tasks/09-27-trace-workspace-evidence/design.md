# PT3 设计

created_at: 2026-09-27T14:39:38Z

工作区扫描接收授权 scope，规范化相对路径和文件内容/类型/模式后计算 baseline/result digest；内部 `.tsunagou`、bridge 私密目录、范围外路径和未提升 artifact 在扫描层排除。Patch 由系统根据扫描结果创建并以 content-addressed ArtifactRef 保存，读取先做 project/domain/owner/recipient 授权。

验证回执使用四级 evidence level，保存时间、actor、命令、退出码、工具版本 digest 和安全输出摘要。`submitted_by` 只表示认证提交者；不生成逐行作者断言。
