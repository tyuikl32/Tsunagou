# PT7 实施步骤

1. 编写 dry-run、备份、停写、迁移、integrity、启动、回滚和 restore 操作单。
2. 按三层环境执行八类验收，保存版本/时间/退出码/证据引用，不保存秘密和完整私密输出。
3. 运行 `python tools/docs/validate_docs.py`、Trellis validate、构建和测试，更新 implementation/overview/command 文档。
4. 只有用户另行授权才接触真实项目；完成后生成用户可读时间线和风险/限制报告。
