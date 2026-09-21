# 总体实施设计

以 [实施基线](../../../../../docs/implementation/README.md) 为唯一当前规范；八模块、stateless workflows与一致读blackboard，不新增领域模块。

按foundation/schema/storage→身份/任务/消息→资源/认知/workspace→跨模块恢复→公共接口/SDK→三个首发宿主→端到端/实验推进。T02仍研究四个宿主，ZCode适配器正式基线后置；各任务依赖见task-plan.json。不得通过删掉首发宿主的正式共同基线来让适配器任务通过。
