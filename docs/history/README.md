# 原始记录归档

2026-09-18 将根目录48份Markdown原稿原样移动到 `2026-09-18-source/`。内容字节不变、原稿彼此相对链接保持同目录关系；[校验清单](source-manifest.json)保存原路径、新路径、大小和SHA256。

原稿包含历轮选项、否决方案、候选设计和后来的覆盖决定，不能直接作为新实现的唯一规范。当前入口：[实施指导](../implementation/README.md)、[用户说明](../overview/product.md)、[本轮决策](../decisions/2026-09-18-boundary-decisions.md)。

请勿修改归档来消除旧矛盾；新解释写进decisions与implementation。校验命令：`python tools/docs/validate_docs.py`。

## 总体规划与决策

- [planning_consensus.md](2026-09-18-source/planning_consensus.md)
- [multi_agent_collaboration_current_design.md](2026-09-18-source/multi_agent_collaboration_current_design.md)
- [implementation_decisions.md](2026-09-18-source/implementation_decisions.md)
- [implementation_decisions_round2.md](2026-09-18-source/implementation_decisions_round2.md)
- [design_and_runtime_principles.md](2026-09-18-source/design_and_runtime_principles.md)
- [repository_module_structure.md](2026-09-18-source/repository_module_structure.md)

## 原题与技术研究

- [agent_to_agent_deep_research.md](2026-09-18-source/agent_to_agent_deep_research.md)
- [adapter_research.md](2026-09-18-source/adapter_research.md)
- [cli_framework_research.md](2026-09-18-source/cli_framework_research.md)
- [technology_stack_research.md](2026-09-18-source/technology_stack_research.md)
- [python_dependency_window.md](2026-09-18-source/python_dependency_window.md)
- [protocol_transport_research.md](2026-09-18-source/protocol_transport_research.md)
- [durable_operations_research.md](2026-09-18-source/durable_operations_research.md)

## 项目、权限、路径与生命周期

- [authorization_grant_model.md](2026-09-18-source/authorization_grant_model.md)
- [grant_scope_model.md](2026-09-18-source/grant_scope_model.md)
- [root_scope_authority.md](2026-09-18-source/root_scope_authority.md)
- [command_authorization_matrix.md](2026-09-18-source/command_authorization_matrix.md)
- [capability_registry.md](2026-09-18-source/capability_registry.md)
- [configuration_model.md](2026-09-18-source/configuration_model.md)
- [project_bootstrap_activation.md](2026-09-18-source/project_bootstrap_activation.md)
- [project_identity_lifecycle.md](2026-09-18-source/project_identity_lifecycle.md)
- [project_identity_replica_model.md](2026-09-18-source/project_identity_replica_model.md)
- [project_root_repository_registry.md](2026-09-18-source/project_root_repository_registry.md)
- [project_state_model.md](2026-09-18-source/project_state_model.md)
- [path_identity_and_overlapping_roots.md](2026-09-18-source/path_identity_and_overlapping_roots.md)
- [project_completion_protocol.md](2026-09-18-source/project_completion_protocol.md)
- [local_authentication_boundary.md](2026-09-18-source/local_authentication_boundary.md)

## Agent、主权限与运行协作

- [adapter_capability_negotiation.md](2026-09-18-source/adapter_capability_negotiation.md)
- [agent_enrollment_protocol.md](2026-09-18-source/agent_enrollment_protocol.md)
- [agent_host_session_lifecycle.md](2026-09-18-source/agent_host_session_lifecycle.md)
- [agent_succession_protocol.md](2026-09-18-source/agent_succession_protocol.md)
- [authority_handoff_grants.md](2026-09-18-source/authority_handoff_grants.md)
- [project_main_agent_bootstrap.md](2026-09-18-source/project_main_agent_bootstrap.md)
- [main_agent_role_acceptance.md](2026-09-18-source/main_agent_role_acceptance.md)
- [agent_autonomy_blackboard_resume_protocol.md](2026-09-18-source/agent_autonomy_blackboard_resume_protocol.md)
- [task_delegation_model.md](2026-09-18-source/task_delegation_model.md)
- [risk_assessment_protocol.md](2026-09-18-source/risk_assessment_protocol.md)

## 接口、消息与生成

- [api_command_transport.md](2026-09-18-source/api_command_transport.md)
- [messaging_protocol.md](2026-09-18-source/messaging_protocol.md)
- [pagination_protocol.md](2026-09-18-source/pagination_protocol.md)
- [code_generation_pipeline.md](2026-09-18-source/code_generation_pipeline.md)
- [versioning_compatibility.md](2026-09-18-source/versioning_compatibility.md)
- [wire_format_conventions.md](2026-09-18-source/wire_format_conventions.md)

## Git与持久性范围

- [git_durability_scope.md](2026-09-18-source/git_durability_scope.md)
- [local_anchor_discovery.md](2026-09-18-source/local_anchor_discovery.md)
- [main_agent_git_control.md](2026-09-18-source/main_agent_git_control.md)
- [multi_repository_git_consistency.md](2026-09-18-source/multi_repository_git_consistency.md)
- [remote_publication_verification.md](2026-09-18-source/remote_publication_verification.md)
