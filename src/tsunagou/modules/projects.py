"""Project registration, local root bindings, and scope calculations.

The coordination repository is the first durable project record.  Local path
bindings are deliberately kept in ``.tsunagou/local`` and never appear in the
shared export.
"""

from __future__ import annotations

import json
import os
import platform
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id

# What a project's ``objective`` says until a goal has actually been agreed.
#
# Nobody is asked for a goal while the project is being created any more: the
# goal comes out of the user's conversation with the main Agent, and it becomes
# a fact only once the user confirms it (a ``user_decision.propose`` with
# ``kind=project.objective``, see ``docs/decisions/2026-10-01-objective-from-dialogue.md``).
# The field itself cannot be empty -- ``project.initialize`` requires it and the
# schema has ``minLength: 1`` -- so it holds this sentence instead of pretending
# to be a goal. Callers that do know a real goal (the CLI's ``--objective``, a
# caller of ``/api/v1/projects``) still win; only the fallback changes.
PENDING_OBJECTIVE = "待主 Agent 与用户确认"


def _atomic_json(path: Path, value: Any) -> None:
    if path.is_file():
        try:
            if json.loads(path.read_text(encoding="utf-8")) == value:
                return
        except (ValueError, UnicodeError):
            pass  # A disposable projection is rebuilt from authoritative state.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def physical_identity(path: Path) -> str:
    """Return a stable local identity without exposing the path itself."""
    resolved = path.resolve(strict=False)
    try:
        stat = resolved.stat()
    except OSError:
        return f"unresolved:{platform.system().lower()}:{os.path.normcase(str(resolved))}"
    return f"inode:{stat.st_dev}:{stat.st_ino}"


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_within(root: Path, candidate: Path) -> bool:
    """Check segment-aware containment after resolving links and junctions."""
    root_value = os.path.normcase(str(_resolved(root)))
    candidate_value = os.path.normcase(str(_resolved(candidate)))
    try:
        return os.path.commonpath([root_value, candidate_value]) == root_value
    except ValueError:  # different Windows drives
        return False


@dataclass(frozen=True, slots=True)
class PathRule:
    root_id: str
    segments: tuple[str, ...] = ()

    def allows(self, relative_segments: tuple[str, ...]) -> bool:
        wanted = tuple(part.casefold() for part in self.segments)
        actual = tuple(part.casefold() for part in relative_segments)
        return actual[: len(wanted)] == wanted

    def intersect(self, other: PathRule) -> PathRule | None:
        if self.root_id != other.root_id:
            return None
        left = tuple(part.casefold() for part in self.segments)
        right = tuple(part.casefold() for part in other.segments)
        if left[: len(right)] == right:
            return self
        if right[: len(left)] == left:
            return other
        return None


@dataclass(frozen=True, slots=True)
class ConfigProvenance:
    source: str
    revision: int
    digest: str


@dataclass(slots=True)
class Project:
    project_id: str
    name: str
    objective: str
    lifecycle: str
    coordination_repository_id: str
    current_lineage_id: str
    current_replica_id: str
    runtime_epoch: str
    policy_revision: int = 1
    roots: dict[str, dict[str, Any]] = field(default_factory=dict)
    repositories: dict[str, dict[str, Any]] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    config: ConfigProvenance | None = None

    @property
    def automatic_wake_enabled(self) -> bool:
        """Unconfigured projects use supported native wake; explicit false is retained."""
        return bool(self.settings.get("auto_wake_multi_agent", True))


class ProjectRegistry:
    """Small persistent project registry backed by the coordination repository."""

    def __init__(self, coordination_repository: str | Path, *, load_files: bool = True) -> None:
        self.repository = _resolved(Path(coordination_repository))
        self.state_dir = self.repository / ".tsunagou"
        self.shared_path = self.state_dir / "project.json"
        self.local_path = self.state_dir / "local" / "bindings.json"
        self.project: Project | None = None
        self.local_bindings: dict[str, dict[str, Any]] = {}
        self.managed_by_database = False
        if load_files:
            self._load()

    def restore_local_state(self, project: dict[str, Any], bindings: dict[str, dict[str, Any]]) -> None:
        raw = dict(project)
        config = raw.pop("config", None)
        self.project = Project(**raw, config=ConfigProvenance(**config) if config else None)
        self.local_bindings = bindings

    @classmethod
    def initialize(
        cls, coordination_repository: str | Path, *, name: str, objective: str
    ) -> ProjectRegistry:
        registry = cls(coordination_repository)
        if not registry.is_git_repository():
            raise ValueError("coordination_repository_must_be_git_repository")
        if registry.project is None:
            registry.project = Project(
                project_id=new_id(),
                name=name,
                objective=objective,
                lifecycle="active",
                coordination_repository_id=canonical_digest({"path": str(registry.repository)})[:32],
                current_lineage_id=new_id(),
                current_replica_id=new_id(),
                runtime_epoch=new_id(),
                config=ConfigProvenance("bootstrap", 1, canonical_digest({"name": name, "objective": objective})),
            )
            registry._save()
        return registry

    def is_git_repository(self) -> bool:
        return (self.repository / ".git").exists() or (
            (self.repository / "HEAD").is_file() and (self.repository / "objects").is_dir()
        )

    def _load(self) -> None:
        if self.shared_path.is_file():
            raw = json.loads(self.shared_path.read_text(encoding="utf-8"))
            # New shared DTOs carry stable project identity only. These local
            # runtime identifiers never inherit authority from a clone.
            raw.setdefault("current_replica_id", new_id())
            raw.setdefault("runtime_epoch", new_id())
            config = raw.pop("config", None)
            self.project = Project(**raw, config=ConfigProvenance(**config) if config else None)
        if self.local_path.is_file():
            self.local_bindings = json.loads(self.local_path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        if self.managed_by_database:
            return
        self.materialize_projection()

    def materialize_projection(self) -> None:
        """Called at bootstrap or after the owning SQLite transaction commits."""
        if self.project is None:
            raise RuntimeError("project_not_initialized")
        raw = self.shared_export()
        _atomic_json(self.shared_path, raw)
        _atomic_json(self.local_path, self.local_bindings)

    def _require_project(self) -> Project:
        if self.project is None:
            raise RuntimeError("project_not_initialized")
        return self.project

    def register_root(
        self, name: str, path: str | Path, *, root_kind: str = "directory", required: bool = False
    ) -> str:
        project = self._require_project()
        if name in project.roots:
            raise ValueError("duplicate_root_name")
        if root_kind not in {"directory", "repository"}:
            raise ValueError("invalid_root_kind")
        root_id = new_id()
        descriptor = {"name": name, "root_kind": root_kind, "required": required}
        project.roots[root_id] = {
            "root_id": root_id, **descriptor, "descriptor_digest": canonical_digest(descriptor)
        }
        self.bind_root(root_id, path)
        self._save()
        return root_id

    def bind_root(self, root_id: str, path: str | Path) -> None:
        project = self._require_project()
        if root_id not in project.roots:
            raise KeyError(root_id)
        absolute = _resolved(Path(path))
        # 物理验证在**这一刻**发生，但**不拒绝**：路径不在（或该是目录却是文件）是有意义的状态
        # —— 目录被移走、挂载没挂上，控制台要把"未绑定"显示出来（见 test_unbound_root_is_diagnostic_only）。
        # 要守的是另一件事：**不许声称 bound**。"已绑定"必须可信，否则后面"根绑好了"这个前提是假的
        # （2026-10-07 实测：给一个不存在的目录，状态照样是 bound，直到真要开工作区才炸）。
        if str(project.roots[root_id].get("root_kind")) == "directory" and absolute.exists() \
                and not absolute.is_dir():
            status = "not_a_directory"
        elif not absolute.exists():
            status = "missing"
        else:
            status = "bound"
        self.local_bindings[root_id] = {
            "absolute_path": str(absolute),
            "physical_identity": physical_identity(absolute),
            "case_mode": "insensitive" if platform.system() == "Windows" else "sensitive",
            "link_policy": "resolve_and_recheck",
            "status": status,
            "binding_revision": self.local_bindings.get(root_id, {}).get("binding_revision", 0) + 1,
        }
        self._save()

    def unbind_root(self, root_id: str, reason: str = "unbound") -> None:
        if root_id not in self._require_project().roots:
            raise KeyError(root_id)
        binding = self.local_bindings.setdefault(root_id, {})
        binding["status"] = reason
        binding["binding_revision"] = binding.get("binding_revision", 0) + 1
        self._save()

    def register_repository(self, name: str, root_id: str, git_common_dir_identity: str) -> str:
        project = self._require_project()
        if root_id not in project.roots:
            raise KeyError(root_id)
        if any(item.get("git_common_dir_identity") == git_common_dir_identity for item in project.repositories.values()):
            raise ValueError("duplicate_repository_identity")
        repository_id = new_id()
        project.repositories[repository_id] = {
            "repository_id": repository_id,
            "name": name,
            "root_id": root_id,
            "git_common_dir_identity": git_common_dir_identity,
        }
        self._save()
        return repository_id

    def configure(self, *, policy_patch: dict[str, Any], reason: str) -> Project:
        """Apply the small, explicit project policy surface owned by Main."""
        project = self._require_project()
        if not reason:
            raise ValueError("configuration_reason_required")
        if not isinstance(policy_patch, dict) or not policy_patch:
            raise ValueError("policy_patch_required")
        unknown = set(policy_patch) - {"auto_wake_multi_agent"}
        if unknown:
            raise ValueError("unsupported_policy_patch")
        value = policy_patch.get("auto_wake_multi_agent")
        if not isinstance(value, bool):
            raise ValueError("auto_wake_multi_agent_boolean_required")
        project.settings["auto_wake_multi_agent"] = value
        project.policy_revision += 1
        previous_revision = project.config.revision if project.config is not None else 0
        project.config = ConfigProvenance(
            "main", previous_revision + 1,
            canonical_digest({"settings": project.settings, "reason": reason}),
        )
        self._save()
        return project

    def effective_rules(
        self, rules: list[PathRule], ceiling: list[PathRule] | None = None
    ) -> list[PathRule]:
        if ceiling is None:
            return list(rules)
        result: list[PathRule] = []
        for rule in rules:
            for limit in ceiling:
                overlap = rule.intersect(limit)
                if overlap is not None and overlap not in result:
                    result.append(overlap)
        return result

    def path_allowed(self, rule: PathRule, candidate: str | Path) -> bool:
        binding = self.local_bindings.get(rule.root_id)
        if not binding or binding.get("status") != "bound":
            return False
        root = Path(binding["absolute_path"])
        resolved = _resolved(Path(candidate))
        if not is_within(root, resolved):
            return False
        relative = resolved.relative_to(_resolved(root))
        return rule.allows(tuple(relative.parts))

    def shared_export(self) -> dict[str, Any]:
        project = self._require_project()
        raw = asdict(project)
        raw = {key: raw[key] for key in (
            "project_id", "name", "objective", "lifecycle", "coordination_repository_id",
            "current_lineage_id", "policy_revision", "settings", "config",
        )}
        raw["roots"] = {key: {k: value[k] for k in (
            "root_id", "name", "root_kind", "required", "descriptor_digest",
        ) if k in value} for key, value in project.roots.items()}
        raw["repositories"] = {key: {k: value[k] for k in (
            "repository_id", "name", "root_id", "required",
        ) if k in value} for key, value in project.repositories.items()}
        return raw

    def diagnose(self) -> dict[str, Any]:
        project = self._require_project()
        roots = {}
        for root_id, descriptor in project.roots.items():
            binding = self.local_bindings.get(root_id, {})
            roots[root_id] = {
                "name": descriptor["name"],
                "status": binding.get("status", "unbound"),
                "physical_identity": binding.get("physical_identity"),
                "required": descriptor["required"],
            }
        return {
            "project_id": project.project_id, "lifecycle": project.lifecycle,
            "roots": roots, "settings": dict(project.settings),
        }
