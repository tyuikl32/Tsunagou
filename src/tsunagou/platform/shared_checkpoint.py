"""Versioned, allow-listed shared DTOs; never serialize a runtime snapshot raw."""

from __future__ import annotations

import re
from typing import Any

from tsunagou.modules.evaluation import SecretRedactor

# These lists are a compatibility contract. Adding a runtime dataclass field
# does not silently publish it in Git. Public semantic documents are named
# explicitly (payload, scope, claims), then stripped of local/secret values.
COLLECTION_FIELDS: dict[str, dict[str, str]] = {
    "tasks": {
        "tasks": (
            "task_id title objective status parent_task_id blocks current_attempt_id revision scope_revision "
            "execution_scope block_reason orphan_reason suspension_snapshot"
        ),
        "attempts": "attempt_id task_id owner_agent_id status execution_epoch revision started_at ended_at",
        "results": "result_id task_id attempt_id payload digest submitted_by",
        "reviews": "round_no result_id reviewer_agent_id decision reason",
        "scope_requests": "scope_request_id task_id attempt_id requested_scope reason expected_revisions status approved_scope",
        "progress_records": "progress_id task_id attempt_id summary evidence_refs recorded_at",
    },
    "cognition": {
        "reports": "report_id task_id attempt_id actor_agent_id claims uncertainties assumptions digest created_at",
        "discrepancies": "discrepancy_id rule_id rule_version subject_key severity input_digest claim_ids status",
        "proposals": "proposal_id payload participants required_slots digest status proposed_by",
        "acceptances": "proposal_id participant_slot proposal_digest real_actor_id represented_participant via_proxy",
        "risk_requests": "request_id attempt_id input_snapshot input_digest candidates deadline_at status",
        "risk_submissions": "request_id assessor_id risk_level reason recommended_driver scope conditions evidence_refs input_digest",
        "risk_acceptances": (
            "subject_ref actor_main_id reason accepted_risks input_digest valid_until_task_terminal status "
            "effective_outcome"
        ),
    },
    "workspaces": {
        "decisions": "decision_id task_id attempt_id driver_kind input_digest hard_constraints evidence_refs decided_by decision_digest",
        "workspaces": (
            "workspace_id attempt_id decision_id driver_kind root_binding_refs repository_id status "
            "baseline_manifest_id result_manifest_id revision scope_paths scope_digest scope_roots"
        ),
        "git_requests": "request_id workspace_id repository_id action requested_main_id exact_input_digest parameters status evidence",
        "baselines": (
            "manifest_id workspace_id head_commit branch index_digest tracked_state_digest untracked_summary "
            "root_identities digest scope_paths scope_digest root_observations"
        ),
        "results": (
            "manifest_id workspace_id attempt_id baseline_digest commit_refs patch_artifact_ref changed_paths "
            "untracked_summary validation_refs digest observed_state_digest baseline_conflict submitted_by observed_at "
            "evidence_level validation_metadata scope_paths scope_digest patch_artifact_domain patch_artifact_owner "
            "root_observations"
        ),
    },
    "lifecycle": {
        "decisions": "decision_id kind subject_ref expected_revision input_digest status decision reason choices summary",
        "resolutions": "operation_id actor conclusion evidence_refs reason",
    },
    "authority": {
        "agents": "agent_id installation_digest status role requested_role",
    },
}

PROJECT_FIELDS = (
    "project_id name objective lifecycle coordination_repository_id current_lineage_id policy_revision roots "
    "repositories settings config"
)
_PRIVATE = frozenset({
    "runtime_epoch", "connection_epoch", "session_id", "conversation_id", "conversation_evidence",
    "conversation_digest", "host_id", "bridge_config", "absolute_path", "storage_path", "external_locator",
    "current_replica_id", "physical_identity", "git_common_dir_identity", "local_binding_ids",
    "private_message", "grant", "grants", "reservation", "reservations", "reservation_id", "root_aliases", "job_claim",
    "lease_owner", "lease_until", "lease_epoch", "worker_id", "job_id", "root_identities",
})
_SECRET_REDACTOR = SecretRedactor()
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/](?:[^\\/\s<>\"|?*]+[\\/])*[^\\/\s<>\"|?*]+")
_UNC_PATH = re.compile(r"(?<![A-Za-z0-9_])(?:\\\\|//)[^\\/\s]+(?:[\\/][^\\/\s]+)+")
_POSIX_PATH = re.compile(r"(?<![\w:/])/(?:[A-Za-z0-9._~+-]+/)*[A-Za-z0-9._~+-]+(?:/[A-Za-z0-9._~+-]+)*")


def _public_text(value: str) -> str:
    value = _SECRET_REDACTOR.text(value)
    urls: list[str] = []

    def preserve_url(match: re.Match[str]) -> str:
        urls.append(match.group(0))
        return f"\u0000CHECKPOINT_URL_{len(urls) - 1}\u0000"

    value = re.sub(r"https?://[^\s]+", preserve_url, value, flags=re.IGNORECASE)
    value = _WINDOWS_PATH.sub("[REDACTED_PATH]", value)
    value = _UNC_PATH.sub("[REDACTED_PATH]", value)
    value = _POSIX_PATH.sub("[REDACTED_PATH]", value)
    for index, url in enumerate(urls):
        value = value.replace(f"\u0000CHECKPOINT_URL_{index}\u0000", url)
    return value


def public_document(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) in ({"__tuple__"}, {"__set__"}):
            return public_document(next(iter(value.values())))
        return {
            key: public_document(item) for key, item in value.items()
            if key.casefold() not in _PRIVATE
            and not any(marker in key.casefold() for marker in ("token", "secret", "credential", "nonce", "ticket"))
        }
    if isinstance(value, (list, tuple)):
        return [public_document(item) for item in value]
    if isinstance(value, str):
        return _public_text(value)
    return value


def select_fields(value: dict[str, Any], fields: str) -> dict[str, Any]:
    return public_document({key: value[key] for key in fields.split() if key in value})  # type: ignore[no-any-return]


def export_shared(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Export public history only; no inbox, runtime authority or local blobs."""
    result: dict[str, list[dict[str, Any]]] = {}
    project = snapshot.get("projects", {}).get("project")
    if project:
        result["project"] = [select_fields(project, PROJECT_FIELDS)]
    for module, collections in COLLECTION_FIELDS.items():
        source = snapshot.get(module, {})
        record: dict[str, Any] = {}
        for collection, fields in collections.items():
            items = source.get(collection)
            if isinstance(items, dict):
                record[collection] = {key: select_fields(value, fields) for key, value in items.items()}
            elif isinstance(items, list):
                record[collection] = [select_fields(value, fields) for value in items]
        if record:
            result[module] = [record]
    # An attachment may be referenced in historical evidence without making
    # its private bytes shareable. Only explicitly promoted refs enter export.
    refs = snapshot.get("artifacts", {}).get("refs", {})
    public_refs = {
        key: select_fields(item, "artifact_ref digest owner_actor domain_ref storage_scope project_id lineage_id scope_digest created_at")
        for key, item in refs.items() if item.get("storage_scope") == "project_shared" and not item.get("recipient_agent_id")
    }
    if public_refs:
        public_digests = {item["digest"] for item in public_refs.values() if isinstance(item.get("digest"), str)}
        blobs = snapshot.get("artifacts", {}).get("blobs", {})
        public_blobs = {
            digest: select_fields(blob, "digest size_bytes media_type local_relative_path storage_state verified_at")
            for digest, blob in blobs.items() if digest in public_digests
        }
        result["artifacts"] = [{"refs": public_refs, "blobs": public_blobs}]
    return result
