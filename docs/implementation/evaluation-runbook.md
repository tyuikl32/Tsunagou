# 评估模块运行约定

`tsunagou.modules.evaluation` 是只读审计投影和追加式实验记录层。它不拥有任务、权限、消息或契约真相，也不接受任何“代表主 Agent 修改业务状态”的入口。

## 固定实验结构

实验臂固定为 A（单 Agent）、B（多 Agent + Worktree）、C（完整协作）、D（无认知协调）。同一 `ExperimentDefinition` 固定 task set digest、预算、host/model matrix、随机种子、指标和 success criteria；定义摘要变化就必须创建新定义。运行记录引用 definition digest、adapter/protocol/config 版本，失败运行仍保留。

## 指标口径

正确性必须引用相同外部验收；intervention 和 rework 按预注册规则计数；wall time 分开记录用户等待、基础设施等待和执行时间。宿主可证明 token usage 标 `observed`，tokenizer 推算标 `estimated`，无法取得标 `unavailable`，任何缺失值都不能填 0。

## 隐私和权限

审计投影只包含注册字段，按收件人权限隐藏私信 subject/body；不记录 prompt、源码、token、ticket、Authorization、原始宿主会话 ID 或完整配置。导出和错误路径使用同一 secret redactor。OTLP 默认关闭，启用时只能指向用户明确配置的本机端点。

## 报告

报告引用所有原始 result ID，公布样本数、失败数、均值/中位数和限制。样本不足或 token 不可观测会进入 limitations；报告是工程验收证据，不自动宣称 C 优于 B。研究门槛和工程 release gate 分开判断。

验证：`uv run pytest tests/unit/test_evaluation.py -q`、`uv run ruff check src/tsunagou/modules/evaluation.py tests/unit/test_evaluation.py`、`uv run mypy src/tsunagou/modules/evaluation.py`。
