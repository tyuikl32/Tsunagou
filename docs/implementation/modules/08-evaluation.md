# 08 审计、观测、实验与交付证据

## 边界

只读消费各模块公开查询及脱敏事件，保存实验配置、运行记录和分析结果。不作为任务/权限/契约的新写入口，不把审计投影当作源事件，不采集隐藏思维链。

## 实体与表

| 表（`evaluation_`） | 字段 |
|---|---|
| audit_views | source_event_id/seq,actor_ref,action,subject_ref,outcome,reason_code,evidence_refs,projection_version；可重建 |
| metric_samples | name,unit,value?,availability:observed\|estimated\|unavailable,labels,source_ref,observed_at；禁止无数据填0 |
| experiment_definitions | name,version,task_set_digest,arms,budget_policy,host_model_matrix,random_seed,metrics,success_criteria,digest |
| experiment_runs | definition_id,arm,replicate,host/adapter/model versions,protocol_digest,config_digest,started_at,finished_at?,status,result_refs |
| experiment_results | run_id,correctness,interventions,rework,wall_time,token_metrics,failures,evidence_refs,digest |
| reports | experiment_id,method_version,summary,statistics,limitations,artifact_ref,digest |

索引event_seq、experiment/arm/replicate唯一、run/status。聚合报告保留原始run引用；修正数据新建修订，不能删除坏结果美化指标。

## 日志与隐私

structlog输出 `timestamp,level,event,project_id,lineage_id,command_id,operation_id?,trace_id?,code,duration_ms` 等注册字段。默认不记录正文、代码、prompt、token、ticket、HTTP Authorization、绝对路径或完整宿主配置。异常trace对本机日志保留但必须统一secret过滤；HTTP access log也覆盖脱敏测试。

OpenTelemetry默认关闭，只支持显式配置的本机OTLP；引入前要验证 exporter开关，不因库存在就默认发送外部数据。审计查询按项目权限和消息收件限制过滤；main不能经evaluation读其他人的私信。

## 指标定义

- intervention：用户为纠正/解阻而作出的有效干预次数，预设设计与最终完成确认单列，不能算成产品额外负担。
- rework：因被记录的接口/认知不一致重开的任务或返工事件，采用预注册归因规则，人工标注与机械计数分开。
- latency：开始至验证完成wall time；模型等待用户时间、基础设施等待、执行时间分别报告，不用“模型没有时间概念”删除实际实验时钟。
- token：宿主可证明的usage；tokenizer估计独立标estimated，无法观测标unavailable，不比较不兼容口径。
- correctness：相同外部验收测试；内核没有丢消息/双owner和故障注入恢复结果另列。

## 实验与门槛

A单Agent、B多Agent+Worktree、C完整、D无认知协调。每组≥5次，正式多Agent组≥3Agent，同任务/预算/模型版本，随机顺序，至少另一个宿主复验。不得让C拥有额外人工提示却不计入条件。

必须保持正确性测试100%；硬分歧注入检出≥95%、误阻塞≤5%；C相对B干预/返工中位数改善≥30%、总耗时≤+10%、可比token≤+25%。样本小则明确置信和外推限制；没有基线数据不能宣传改善。工程发布通过与研究效果通过分别显示。

## 端口与验收

`query_audit`、`query_metrics`、`record_experiment_run`、`generate_report`。生成报告走Operation/Job，不阻塞领域事务。记录实验由user_control或专用内部runner，普通Agent不能改实验结果；Agent的自报证据作为输入，不能替代核验。

测试日志秘密哨兵、审计字段权限、投影重建去重、unavailable计算、实验定义digest、乱序/失败run保留、统计方法确定性。实施T22/T23/T24。
