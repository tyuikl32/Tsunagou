"""One begin/submit command, with filesystem observation before the write UoW."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from tsunagou.application.workflows.task_execution import TaskExecutionWorkflow
from tsunagou.application.workspace_evidence import WorkspaceEvidence
from tsunagou.modules.artifacts import ArtifactService
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.coordination import CoordinationService
from tsunagou.modules.messaging import MessageStore
from tsunagou.modules.resources import ResourceKey, ResourceRequest, ResourceService
from tsunagou.modules.tasks import Task, TaskService
from tsunagou.modules.workspaces import Workspace, WorkspaceService
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id


def _same_place(left: str, right: str) -> bool:
    """Do two machine-local paths name the same place?

    Only used to compare what a machine reported about itself with what a workspace was
    pointed at. Separators, trailing slashes and letter case vary between machines and
    platforms, and none of that changes which directory is meant.
    """

    def normalise(value: str) -> str:
        return str(value or "").strip().replace("\\", "/").rstrip("/").casefold()

    return bool(normalise(left)) and normalise(left) == normalise(right)


class ExecutionCommands:
    def __init__(
        self, *, authority: AuthorityService, tasks: TaskService, cognition: CognitionService,
        resources: ResourceService, workspaces: WorkspaceService, coordination: CoordinationService,
        evidence: WorkspaceEvidence | None, artifacts: ArtifactService | None, lifecycle: Any,
        project_id: str, state_runtime: Any,
        messages: MessageStore,
    ) -> None:
        self.authority, self.tasks, self.resources = authority, tasks, resources
        self.cognition = cognition
        self.workspaces, self.coordination = workspaces, coordination
        self.evidence, self.artifacts, self.lifecycle = evidence, artifacts, lifecycle
        self.project_id, self.state_runtime = project_id, state_runtime
        self.messages = messages
        self.workflow = TaskExecutionWorkflow(tasks=tasks, cognition=cognition)

    def authorize(self, context: dict[str, Any], capability: str, **scope: Any) -> None:
        session = self.authority.sessions.get(context["session_id"])
        if session is None or session.connection_epoch != context["connection_epoch"]:
            raise PermissionError("stale_connection_epoch")
        grant = self.authority.find_grant(agent_id=context["principal_id"], session_id=context["session_id"],
                                          capability=capability, **scope)
        if grant is None:
            raise PermissionError("capability_denied")
        self.authority.authorize(agent_id=context["principal_id"], session_id=context["session_id"],
                                 grant_id=grant.grant_id, capability=capability, **scope)

    def _require_contract_alignment(self, task_id: str) -> None:
        """Refuse a boundary while an agreement this task depends on is unsettled.

        A contract a task declares (``payload["task_id"]``) that nobody has accepted
        yet, or that has a revision still under discussion, is exactly the "which
        version governs" ambiguity the contract layer exists to stop: work would
        start from — or publish on top of — a version that can still change.

        Both boundaries ask the same question, so "settled enough to start" and
        "settled enough to publish" can never drift apart. A task with no linked
        contract is not refused: there is nothing to be aligned with.
        """
        if self.cognition.unaligned_contracts_for_task(task_id):
            raise ValueError("contract_not_accepted")

    def _require_declared_contract_versions(self, task_id: str, payload: dict[str, Any]) -> None:
        """Refuse a boundary whose caller declared contract versions that are not in force.

        ``_require_contract_alignment`` above answers "is an agreement in force at all";
        this one answers "is the version you actually read the one that governs". A worker
        that started before a revision landed can finish its work and still not publish it:
        reading the current version, bringing the work up to date and submitting again is
        the repair, and this refusal closes nothing (attempt, reservation and files stay).

        A caller that declares nothing is not refused. The declaration is what makes the
        comparison possible, so an in-process caller (and the A2A face, which carries no
        task context) keeps working; the bridge fills the field in from the versions the
        agent read through ``context.project_read``, which is what turns "I read it" into
        a checkable fact.
        """
        declared = payload.get("expected_revisions")
        if not isinstance(declared, dict):
            return
        versions = declared.get("contract")
        if versions is None:
            return
        if not isinstance(versions, (list, tuple)):
            raise ValueError("contract_revision_conflict")
        in_force = sorted(str(item) for item in self.cognition.current_contract_versions(task_id))
        if sorted(str(item) for item in versions) != in_force:
            raise ValueError("contract_revision_conflict")

    def check_begin(self, payload: dict[str, Any], context: dict[str, Any]) -> Task:
        self.authorize(context, "task.claim")
        expected_revision = payload.get("expected_task_revision")
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            raise ValueError("expected_task_revision_required")
        task = self.workflow.validate_begin(payload["task_id"], context["principal_id"], expected_revision)
        self.coordination.require_assigned_worker(task.task_id, context["principal_id"])
        self._require_contract_alignment(task.task_id)
        self._require_declared_contract_versions(task.task_id, payload)
        # 契约那两道先问：契约没谈拢的任务本来就不能开工，用哪台机器来开工都轮不到。
        self._require_supported_workspace(task, context)
        if self.lifecycle is not None:
            pending = next((item for item in self.lifecycle.decisions.values()
                            if item.subject_ref == task.task_id and item.status == "pending"), None)
            if pending is not None:
                raise ValueError("user_decision_pending:" + pending.decision_id)
        return task

    def _require_supported_workspace(self, task: Task, context: dict[str, Any]) -> None:
        """Who may hold a workspace for this task: a local Agent by default, a remote one only
        when it has declared a code copy and the workspace was pointed at that copy.

        "Touches files" is already defined by the task itself: its resource requests contain a
        ``path`` row, which is what makes ``prepare_begin`` demand a workspace. A workspace is
        normally a fact about **this machine's** filesystem — the root binding holds an absolute
        path and a physical identity, the baseline is scanned from those files, and the evidence
        records that scan.

        A remote machine's copy cannot be read from here. So it is allowed on exactly one shape:
        the machine **declared** its copy when it joined (``agent import --copy``, carried as
        ``descriptor_ref``), and the workspace decision is ``external`` pointing at that same
        location. Then the host records the location and never reads it, the workspace carries no
        baseline, and the result is no manifest — "the machine reported it", not "we watched it"
        (see D192). Anything else is refused, because the failure it would produce is worse than
        a refusal: a task that looks in scope while the worker edits a same-named path elsewhere.
        """

        if not any(item.key.kind == "path" for item in self.requests(task)):
            return
        agent = self.authority.agents.get(context["principal_id"])
        machine = str(getattr(agent, "machine", "") or "")
        if not machine:
            return                       # 本机 Agent：仓库根就在这台机器上，照旧
        copy_path = str(getattr(agent, "copy_path", "") or "")
        if not copy_path:
            raise ValueError("remote_worker_needs_a_code_copy")
        decision = max((item for item in self.workspaces.decisions.values() if item.task_id == task.task_id),
                       key=lambda item: item.revision, default=None)
        if decision is None:
            return                       # 还没选工作区：让 prepare_begin 照旧说"先定工作区"
        if decision.driver_kind != "external":
            raise ValueError("remote_worker_requires_external_workspace")
        if not _same_place(decision.external_locator or "", copy_path):
            raise ValueError("remote_workspace_locator_mismatch")

    def _remote_holder(self, task: Task, context: dict[str, Any]) -> bool:
        """Is this task's workspace held by another machine (external + a remote claimer)?"""

        agent = self.authority.agents.get(context["principal_id"])
        if not str(getattr(agent, "machine", "") or "") or not str(getattr(agent, "copy_path", "") or ""):
            return False
        decision = max((item for item in self.workspaces.decisions.values() if item.task_id == task.task_id),
                       key=lambda item: item.revision, default=None)
        return decision is not None and decision.driver_kind == "external"

    @staticmethod
    def requests(task: Task) -> list[ResourceRequest]:
        # 只有个壳的任务（调用方给的对象可能只带 task_id）就是"没有范围"：它当然也没有资源请求，
        # 不该在这里炸成一个属性错误。
        scope = getattr(task, "execution_scope", None)
        if not scope:
            return []
        if set(scope) == {"roots"}:
            if not isinstance(scope["roots"], list) or any(not isinstance(r, str) or not r for r in scope["roots"]):
                raise ValueError("invalid_task_execution_scope")
            return [ResourceRequest(ResourceKey.path(root), "exclusive_write") for root in scope["roots"]]
        if set(scope) != {"resources"} or not isinstance(scope["resources"], list):
            raise ValueError("invalid_task_execution_scope")
        result = []
        for row in scope["resources"]:
            if not isinstance(row, dict):
                raise ValueError("invalid_resource_request")
            if row.get("kind") == "path":
                root, segments, mode = row.get("root_id"), row.get("segments", []), row.get("mode", "exclusive_write")
                if (not isinstance(root, str) or not root.strip() or not isinstance(segments, list)
                        or any(not isinstance(s, str) or not s or s in {".", ".."} or "/" in s or "\\" in s for s in segments)
                        or mode not in {"read", "consistent_read", "exclusive_write"}):
                    raise ValueError("invalid_path_resource")
                result.append(ResourceRequest(ResourceKey.path(root, *segments), mode))
            elif row.get("kind") == "named":
                namespace, name = row.get("namespace"), row.get("name")
                if (not isinstance(namespace, str) or not namespace.strip() or not isinstance(name, str) or not name.strip()
                        or row.get("mode", "exclusive_use") != "exclusive_use"):
                    raise ValueError("invalid_named_resource")
                result.append(ResourceRequest(ResourceKey.named(namespace, name), "exclusive_use"))
            else:
                raise ValueError("invalid_resource_kind")
        return result

    def prepare_begin(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        task = self.check_begin(payload, context)
        requests = self.requests(task)
        prepared: dict[str, Any] = {"requests": requests, "scope_digest": canonical_digest(task.execution_scope),
                                    "workspace": None, "observed": None}
        if not any(item.key.kind == "path" for item in requests):
            return prepared
        if self.evidence is None:
            raise ValueError("workspace_project_required")
        decision = max((item for item in self.workspaces.decisions.values() if item.task_id == task.task_id),
                       key=lambda item: item.revision, default=None)
        if decision is None or decision.scope_revision != task.scope_revision:
            raise ValueError("main_workspace_selection_required")
        roots = self.evidence.resolve_scope(task, [])
        if decision.root_binding_refs and set(decision.root_binding_refs) != {root["root_id"] for root in roots}:
            raise ValueError("workspace_policy_roots_mismatch")
        if decision.driver_kind == "worktree" and (len(roots) != 1 or not decision.repository_id):
            raise ValueError("main_worktree_preparation_required")
        if decision.driver_kind == "external" and not decision.external_locator:
            raise ValueError("main_external_preparation_required")
        workspace = next((item for item in self.workspaces.workspaces.values()
                          if item.attempt_id == task.current_attempt_id), None) if task.status == "running" else None
        if workspace is not None:
            if workspace.decision_id != decision.decision_id or workspace.scope_digest != canonical_digest(roots):
                raise ValueError("workspace_policy_changed_reclaim_required")
            prepared["workspace"] = workspace
            return prepared
        scope_paths = self.evidence.virtual_paths(roots)
        remote = self._remote_holder(task, context)
        workspace = Workspace(
            new_id(), "pending", decision.decision_id, decision.driver_kind,
            tuple(root["root_id"] for root in roots), decision.repository_id, decision.external_locator,
            scope_paths=tuple(scope_paths) if scope_paths is not None else None,
            scope_digest=canonical_digest(roots), scope_roots=tuple(roots),
        )
        # 远端自己那份副本：主机**不扫**它（也扫不到）。没有基线、没有清单，只有"那台机器说它
        # 改了什么" —— 这是 D192 那一档证据的全部含义，不能拿主机这边扫出来的东西冒充它。
        prepared.update(workspace=workspace, observed=None if remote else self.evidence.scan(workspace, task))
        return prepared

    def begin(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        task = self.check_begin(payload, context)
        prepared = context["_prepared"]
        attempt = self.workflow.begin_attempt(task.task_id, context["principal_id"], payload["expected_task_revision"])
        workspace: Workspace | None = prepared["workspace"]
        if workspace is not None:
            self.resources.set_root_aliases({**self.resources.root_aliases,
                                            **{root["root_id"]: root["physical_identity"] for root in workspace.scope_roots}})
            workspace = replace(workspace, attempt_id=attempt.attempt_id)
            self.workspaces.workspaces[workspace.workspace_id] = workspace
            if prepared["observed"] is not None:
                observed = prepared["observed"]
                self.workspaces.record_baseline(workspace.workspace_id, **{key: observed[key] for key in (
                    "head_commit", "branch", "index_digest", "tracked_state_digest", "untracked_summary",
                    "root_identities", "dirty", "root_observations",
                )})
            else:
                # 远端自己那份副本：主机没看过，所以**没有基线**。工作区照样登记（谁在哪儿动过
                # 哪块逻辑路径要看得见），状态如实写成"远端自报"，交活时也就不会有清单。
                workspace.status = "remote_reported"
        reservation = self.resources.reserve_set(task_id=task.task_id, attempt_id=attempt.attempt_id,
                                                owner_agent_id=context["principal_id"], execution_epoch=attempt.execution_epoch,
                                                scope_digest=prepared["scope_digest"], requests=prepared["requests"])
        if attempt.status == "claimed":
            self.tasks.start(task.task_id, context["principal_id"])
        grant = self.authority.find_grant(agent_id=context["principal_id"], session_id=context["session_id"],
                                          capability="task.execute", task_id=task.task_id, attempt_id=attempt.attempt_id)
        if grant is None:
            self.authority.issue_execution_grant(agent_id=context["principal_id"], session_id=context["session_id"],
                                                 task_id=task.task_id, attempt_id=attempt.attempt_id,
                                                 execution_epoch=attempt.execution_epoch)
        return {"task_id": task.task_id, "attempt_id": attempt.attempt_id, "owner_agent_id": attempt.owner_agent_id,
                "status": task.status, "revision": task.revision, "scope_revision": task.scope_revision,
                "execution_scope": task.execution_scope, "workspace_id": workspace.workspace_id if workspace else None,
                "reservation_id": reservation.reservation_id if reservation else None}

    def prepare_submit(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        task_id, attempt_id = payload["task_id"], payload["attempt_id"]
        self.authorize(context, "task.execute", task_id=task_id, attempt_id=attempt_id)
        self.workflow.validate_submit(task_id, context["principal_id"], attempt_id)
        workspace = next((item for item in self.workspaces.workspaces.values() if item.attempt_id == attempt_id), None)
        prepared: dict[str, Any] = {"workspace": workspace, "observed": None, "artifact_ref": None, "artifact_blob": None}
        if workspace is not None:
            if self.evidence is None:
                raise ValueError("workspace_project_required")
            # 远端自己那份副本没有基线：主机没观察过它，也就没有"改动前后"可比 —— 不扫盘、
            # 不编清单。交活时带上的是那台机器自己的交代（见 D192）。
            if workspace.baseline_manifest_id:
                prepared["observed"] = self.evidence.scan(workspace, self.tasks.tasks[task_id], include_patch=True)
                patch = prepared["observed"].pop("patch_bytes", b"")
                if patch:
                    if self.artifacts is None or self.state_runtime is None:
                        raise ValueError("artifact_service_required")
                    # Materialize immutable bytes before SQLite BEGIN. This temporary
                    # service owns no live reference; the UoW adopts it only on success.
                    staging = ArtifactService(self.artifacts.storage_dir)
                    ref = staging.record_workspace_patch(patch, workspace_id=workspace.workspace_id,
                                                         actor=context["principal_id"], project_id=self.project_id,
                                                         lineage_id=self.state_runtime.lineage_id,
                                                         scope_digest=workspace.scope_digest or "")
                    prepared.update(artifact_ref=ref, artifact_blob=staging.blobs[ref.digest])
        return prepared

    def submit(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        task_id, attempt_id = payload["task_id"], payload["attempt_id"]
        self.authorize(context, "task.execute", task_id=task_id, attempt_id=attempt_id)
        self.workflow.validate_submit(task_id, context["principal_id"], attempt_id)
        # A result must not be published on top of a superseded agreement. The refusal
        # closes nothing — the attempt, its reservation and its files stay in place —
        # so the caller can read the current version, bring the work up to date and
        # submit again instead of starting over.
        self._require_contract_alignment(task_id)
        self._require_declared_contract_versions(task_id, payload)
        prepared = context["_prepared"]
        workspace, observed = prepared["workspace"], prepared["observed"]
        result_ref = None
        # 只有"主机亲自看过"的那一条才写工作区清单：清单里的基线、改动与冲突判定，都是本地观察
        # 的产物。远端自己那份副本没有基线（见 D192），于是**没有清单** —— 那正是它诚实的样子：
        # 结果里留下的是那台机器自己的交代，而不是一份看起来像观察的记录。
        if workspace is not None and observed is not None:
            baseline = self.workspaces.baselines[workspace.baseline_manifest_id]
            ref = prepared["artifact_ref"]
            if ref is not None and self.artifacts is not None:
                self.artifacts.refs[ref.artifact_ref] = ref
                self.artifacts.blobs[ref.digest] = prepared["artifact_blob"]
            manifest = self.workspaces.record_result(
                workspace.workspace_id, attempt_id=attempt_id, baseline_digest=baseline.digest,
                commit_refs=[], patch_artifact_ref=ref.artifact_ref if ref else None,
                changed_paths=observed["changed_paths"], untracked_summary=observed["untracked_summary"],
                validation_refs=list(payload.get("evidence_refs") or []), observed_state_digest=observed["tracked_state_digest"],
                baseline_conflict=observed["tracked_state_digest"] != baseline.tracked_state_digest,
                submitted_by=context["principal_id"], root_observations=observed["root_observations"],
                evidence_level="system_verified", validation_metadata=payload.get("validation_metadata"),
            )
            result_ref = manifest.manifest_id
        elif workspace is not None:
            # 远端自己那份副本：没有清单可写，但状态要往前走一步 —— 停在"远端自报"会让人以为
            # 这活还在做。它交的是什么，就在那台机器自己的交代里（见 D192）。
            workspace.status = "remote_result_reported"
        work = {key: value for key, value in payload.items() if key not in {"task_id", "attempt_id"}}
        work["workspace_result_ref"] = result_ref
        result = self.workflow.submit(task_id, context["principal_id"], work, attempt_id=attempt_id)
        self.release(attempt_id, "attempt_submitted")
        main = self.authority.main_agent_id
        main_session = next((s for s in self.authority.sessions.values()
                             if s.agent_id == main and s.active and s.status == "ready"), None)
        if main and main_session:
            self.authority.issue_grant(issuer_agent_id=main, kind="task_review", principal_id=main,
                                       session_id=main_session.session_id, task_id=task_id,
                                       capabilities={"task.review"}, scope={"task_id": task_id})
        if main and main != context["principal_id"]:
            # The review boundary compares result_digest against the stored result, and
            # this notification is the only place the reviewer learns a result exists.
            # Sending the id without the digest leaves the reviewer able to see the
            # obligation but unable to act on it, so both travel together. The digest is
            # a version pin, not a secret: it is the value review already requires back.
            self.messages.send(command_id=context["command_id"] + ":submitted", sender_agent_id=context["principal_id"],
                               recipient_agent_id=main, kind="task.submitted", subject_ref="task/" + task_id,
                               summary="有结果待评审",
                               payload={"task_id": task_id, "result_id": result.result_id,
                                        "result_digest": result.digest})
        return {"task_id": task_id, "attempt_id": attempt_id, "result_id": result.result_id, "digest": result.digest,
                "workspace_result_ref": result_ref, "status": "submitted"}

    def release(self, attempt_id: str, reason: str) -> None:
        self.resources.release_for_attempt(attempt_id, reason=reason)
        for key, grant in list(self.authority.grants.items()):
            if grant.attempt_id == attempt_id and grant.status == "active":
                self.authority.grants[key] = replace(grant, status="revoked")

    def select_workspace(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        self.authorize(context, "workspace.select")
        task = self.tasks.tasks[payload["task_id"]]
        if task.status in {"claimed", "running", "cancel_requested", "submitted", "completed", "cancelled", "failed"}:
            raise ValueError("workspace_selection_requires_stopped_task")
        decision = self.workspaces.record_isolation_decision(
            task_id=task.task_id, scope_revision=task.scope_revision, driver_kind=payload["driver_kind"],
            input_snapshot={"execution_scope": task.execution_scope, "reason": payload.get("reason", "")},
            hard_constraints=set(payload.get("hard_constraints") or []), evidence_refs=payload.get("evidence_refs") or [],
            decided_by=context["principal_id"], root_binding_refs=tuple(payload.get("root_binding_refs") or []),
            repository_id=payload.get("repository_id"), external_locator=payload.get("external_locator"),
        )
        return {"decision_id": decision.decision_id, "decision_digest": decision.decision_digest,
                "revision": decision.revision, "scope_revision": decision.scope_revision, "status": "selected"}
