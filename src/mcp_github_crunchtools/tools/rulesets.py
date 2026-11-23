"""Ruleset tools.

Tools for listing, reading, creating and updating GitHub rulesets, at the
organization level or on a single repository.

``org`` is required on every function and never falls back to
GITHUB_DEFAULT_ORG: a gateway guard pins the organization, and an absent
argument would slip past it.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ..client import get_client
from ..models import (
    ALL_PATTERN,
    ENFORCEMENTS,
    MAX_PATTERN_LENGTH,
    clamp_per_page,
    validate_choice,
    validate_name,
    validate_patterns,
    validate_positive_int,
    validate_text,
)

TARGETS = ("branch", "tag", "push", "repository")
MAX_RULES = 50
MAX_BYPASS_ACTORS = 100
MAX_CONTEXT_LENGTH = 255

_REF_INCLUDE_SPECIALS = frozenset({"~DEFAULT_BRANCH", ALL_PATTERN})
_REPO_INCLUDE_SPECIALS = frozenset({ALL_PATTERN})

_ACTOR_ID_REQUIRED = frozenset({"Integration", "RepositoryRole", "Team", "User"})


class BypassActor(BaseModel):
    """An actor allowed to bypass a ruleset."""

    model_config = ConfigDict(extra="forbid")

    actor_id: int | None = None
    actor_type: Literal[
        "Integration", "OrganizationAdmin", "RepositoryRole", "Team", "DeployKey", "User"
    ]
    bypass_mode: Literal["always", "pull_request", "exempt"] = "always"

    @model_validator(mode="after")
    def _check(self) -> "BypassActor":
        if self.actor_type in _ACTOR_ID_REQUIRED and (self.actor_id is None or self.actor_id < 1):
            raise ValueError(f"actor_id must be a positive integer for {self.actor_type}")
        if self.actor_type == "DeployKey" and self.actor_id is not None:
            raise ValueError("actor_id must be null for DeployKey")
        if (
            self.actor_type == "OrganizationAdmin"
            and self.actor_id is not None
            and self.actor_id < 1
        ):
            raise ValueError("actor_id must be a positive integer when given")
        if self.actor_type == "DeployKey" and self.bypass_mode == "pull_request":
            raise ValueError("bypass_mode pull_request is not allowed for DeployKey")
        return self

    def to_api(self) -> dict[str, Any]:
        """The wire form. OrganizationAdmin omits a missing actor_id."""
        out: dict[str, Any] = {"actor_type": self.actor_type, "bypass_mode": self.bypass_mode}
        if self.actor_id is not None or self.actor_type != "OrganizationAdmin":
            out["actor_id"] = self.actor_id
        return out


# --- rules -----------------------------------------------------------------


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UpdateParameters(_Params):
    """Parameters of the update rule."""

    update_allows_fetch_and_merge: bool = False


class RequiredDeploymentsParameters(_Params):
    """Parameters of the required_deployments rule."""

    required_deployment_environments: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> "RequiredDeploymentsParameters":
        self.required_deployment_environments = [
            validate_name(e, "required_deployment_environments entry")
            for e in self.required_deployment_environments
        ]
        return self


class PullRequestParameters(_Params):
    """Parameters of the pull_request rule."""

    allowed_merge_methods: list[Literal["merge", "squash", "rebase"]] = Field(
        default=["merge", "squash", "rebase"], min_length=1
    )
    dismiss_stale_reviews_on_push: bool = False
    require_code_owner_review: bool = False
    require_last_push_approval: bool = False
    required_approving_review_count: int = Field(default=1, ge=0, le=10)
    required_review_thread_resolution: bool = False


class StatusCheck(_Params):
    """One required status check."""

    context: str
    integration_id: int | None = None

    @model_validator(mode="after")
    def _check(self) -> "StatusCheck":
        validate_text(self.context, "context", MAX_CONTEXT_LENGTH)
        return self


class RequiredStatusChecksParameters(_Params):
    """Parameters of the required_status_checks rule."""

    required_status_checks: list[StatusCheck] = Field(min_length=1)
    strict_required_status_checks_policy: bool = False
    do_not_enforce_on_create: bool = False


class PatternParameters(_Params):
    """Parameters of the commit/branch/tag pattern rules."""

    operator: Literal["starts_with", "ends_with", "contains", "regex"]
    pattern: str
    name: str | None = None
    negate: bool = False

    @model_validator(mode="after")
    def _check(self) -> "PatternParameters":
        validate_text(self.pattern, "pattern", MAX_PATTERN_LENGTH)
        if self.name is not None:
            validate_text(self.name, "name")
        return self


class _BareRule(BaseModel):
    """A rule that takes no parameters: ``parameters`` is refused."""

    model_config = ConfigDict(extra="forbid")


class CreationRule(_BareRule):
    """creation rule."""

    type: Literal["creation"]


class DeletionRule(_BareRule):
    """deletion rule."""

    type: Literal["deletion"]


class RequiredLinearHistoryRule(_BareRule):
    """required_linear_history rule."""

    type: Literal["required_linear_history"]


class RequiredSignaturesRule(_BareRule):
    """required_signatures rule."""

    type: Literal["required_signatures"]


class NonFastForwardRule(_BareRule):
    """non_fast_forward rule."""

    type: Literal["non_fast_forward"]


class UpdateRule(_BareRule):
    """update rule."""

    type: Literal["update"]
    parameters: UpdateParameters = Field(default_factory=UpdateParameters)


class RequiredDeploymentsRule(_BareRule):
    """required_deployments rule."""

    type: Literal["required_deployments"]
    parameters: RequiredDeploymentsParameters


class PullRequestRule(_BareRule):
    """pull_request rule."""

    type: Literal["pull_request"]
    parameters: PullRequestParameters = Field(default_factory=PullRequestParameters)


class RequiredStatusChecksRule(_BareRule):
    """required_status_checks rule."""

    type: Literal["required_status_checks"]
    parameters: RequiredStatusChecksParameters


class CommitMessagePatternRule(_BareRule):
    """commit_message_pattern rule."""

    type: Literal["commit_message_pattern"]
    parameters: PatternParameters


class CommitAuthorEmailPatternRule(_BareRule):
    """commit_author_email_pattern rule."""

    type: Literal["commit_author_email_pattern"]
    parameters: PatternParameters


class CommitterEmailPatternRule(_BareRule):
    """committer_email_pattern rule."""

    type: Literal["committer_email_pattern"]
    parameters: PatternParameters


class BranchNamePatternRule(_BareRule):
    """branch_name_pattern rule."""

    type: Literal["branch_name_pattern"]
    parameters: PatternParameters


class TagNamePatternRule(_BareRule):
    """tag_name_pattern rule."""

    type: Literal["tag_name_pattern"]
    parameters: PatternParameters


Rule = Annotated[
    CreationRule
    | DeletionRule
    | RequiredLinearHistoryRule
    | RequiredSignaturesRule
    | NonFastForwardRule
    | UpdateRule
    | RequiredDeploymentsRule
    | PullRequestRule
    | RequiredStatusChecksRule
    | CommitMessagePatternRule
    | CommitAuthorEmailPatternRule
    | CommitterEmailPatternRule
    | BranchNamePatternRule
    | TagNamePatternRule,
    Field(discriminator="type"),
]

SUPPORTED_RULE_TYPES = (
    "creation",
    "deletion",
    "required_linear_history",
    "required_signatures",
    "non_fast_forward",
    "update",
    "required_deployments",
    "pull_request",
    "required_status_checks",
    "commit_message_pattern",
    "commit_author_email_pattern",
    "committer_email_pattern",
    "branch_name_pattern",
    "tag_name_pattern",
)

_RULES_ADAPTER: TypeAdapter[list[Rule]] = TypeAdapter(list[Rule])
_BYPASS_ADAPTER: TypeAdapter[list[BypassActor]] = TypeAdapter(list[BypassActor])


# --- validation helpers ----------------------------------------------------


def _validate_ruleset_name(value: str) -> str:
    return validate_text(value.strip() if isinstance(value, str) else value, "name")


def _validate_rules(rules: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if rules is None:
        return None
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise ValueError(f"rules must be a list of at most {MAX_RULES} rules")
    for rule in rules:
        rule_type = rule.get("type") if isinstance(rule, dict) else None
        if rule_type not in SUPPORTED_RULE_TYPES:
            raise ValueError(
                f"unsupported rule type {rule_type!r}; supported: {', '.join(SUPPORTED_RULE_TYPES)}"
            )
    parsed = _RULES_ADAPTER.validate_python(rules)
    return [r.model_dump(mode="json", exclude_none=True) for r in parsed]


def _validate_bypass(
    actors: list[dict[str, Any]] | None, target: str | None
) -> list[dict[str, Any]] | None:
    if actors is None:
        return None
    if not isinstance(actors, list) or len(actors) > MAX_BYPASS_ACTORS:
        raise ValueError(f"bypass_actors must be a list of at most {MAX_BYPASS_ACTORS} actors")
    parsed = _BYPASS_ADAPTER.validate_python(actors)
    if target is not None and target != "branch":
        for actor in parsed:
            if actor.bypass_mode == "pull_request":
                raise ValueError("bypass_mode pull_request is only allowed for branch rulesets")
    return [a.to_api() for a in parsed]


def _ruleset_path(org: str, repo: str | None) -> str:
    org = validate_name(org, "org")
    if repo is None:
        return f"/orgs/{org}/rulesets"
    return f"/repos/{org}/{validate_name(repo, 'repo')}/rulesets"


def _conditions(
    *,
    org_level: bool,
    target: str | None,
    ref_name_include: list[str] | None,
    ref_name_exclude: list[str] | None,
    repository_name_include: list[str] | None,
    repository_name_exclude: list[str] | None,
    repository_name_protected: bool | None,
) -> dict[str, Any] | None:
    """Build the conditions object from the fields given, or None if none."""
    ref_inc = validate_patterns(ref_name_include, "ref_name_include", _REF_INCLUDE_SPECIALS)
    ref_exc = validate_patterns(ref_name_exclude, "ref_name_exclude")
    repo_inc = validate_patterns(
        repository_name_include, "repository_name_include", _REPO_INCLUDE_SPECIALS
    )
    repo_exc = validate_patterns(repository_name_exclude, "repository_name_exclude")
    ref_given = ref_inc is not None or ref_exc is not None
    repo_given = (
        repo_inc is not None or repo_exc is not None or repository_name_protected is not None
    )

    if repo_given and not org_level:
        raise ValueError("repository_name_* conditions are only valid for organization rulesets")
    if ref_given and target in ("push", "repository"):
        raise ValueError(f"ref_name conditions are not valid for target {target}")

    conditions: dict[str, Any] = {}
    if ref_given:
        conditions["ref_name"] = {"include": ref_inc or [], "exclude": ref_exc or []}
    if repo_given:
        repo_cond: dict[str, Any] = {"include": repo_inc or [], "exclude": repo_exc or []}
        if repository_name_protected is not None:
            repo_cond["protected"] = bool(repository_name_protected)
        conditions["repository_name"] = repo_cond
    return conditions or None


def _trim(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in (
            "id",
            "name",
            "target",
            "source_type",
            "source",
            "enforcement",
            "bypass_actors",
            "conditions",
            "rules",
            "current_user_can_bypass",
            "updated_at",
        )
    }


# --- tools -----------------------------------------------------------------


async def list_rulesets(
    org: str,
    repo: str | None = None,
    targets: str | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    """List rulesets of an organization, or of one repository.

    Args:
        org: Organization name (required; no default is applied)
        repo: Repository name; if unset, the organization's rulesets are listed
        targets: Comma-separated subset of branch, tag, push, repository
            (``repository`` only when ``repo`` is unset)
        page: Page number (default: 1)
        per_page: Results per page (default: 30, max: 100)

    Returns:
        ``rulesets`` (list of trimmed rulesets) and ``pagination`` when GitHub
        reports more pages
    """
    path = _ruleset_path(org, repo)
    params: dict[str, Any] = {
        "per_page": clamp_per_page(per_page),
        "page": validate_positive_int(page, "page"),
    }
    if targets is not None:
        parts = [t.strip() for t in targets.split(",")]
        for part in parts:
            validate_choice(part, TARGETS, "targets entry")
            if part == "repository" and repo is not None:
                raise ValueError("target repository is only valid for organization rulesets")
        params["targets"] = ",".join(dict.fromkeys(parts))

    result = await get_client().get(path, params=params)
    out: dict[str, Any] = {"rulesets": [_trim(r) for r in result.get("items", [])]}
    if "pagination" in result:
        out["pagination"] = result["pagination"]
    return out


async def get_ruleset(
    org: str,
    ruleset_id: int,
    repo: str | None = None,
) -> dict[str, Any]:
    """Get one ruleset, with its rules, conditions and bypass actors.

    Args:
        org: Organization name (required; no default is applied)
        ruleset_id: Ruleset ID
        repo: Repository name; if unset, an organization ruleset is read

    Returns:
        Trimmed ruleset (id, name, target, source_type, source, enforcement,
        bypass_actors, conditions, rules, current_user_can_bypass, updated_at)
    """
    path = _ruleset_path(org, repo)
    ruleset_id = validate_positive_int(ruleset_id, "ruleset_id")
    return _trim(await get_client().get(f"{path}/{ruleset_id}"))


def _build_body(
    *,
    org_level: bool,
    name: str | None,
    enforcement: str | None,
    target: str | None,
    ref_name_include: list[str] | None,
    ref_name_exclude: list[str] | None,
    repository_name_include: list[str] | None,
    repository_name_exclude: list[str] | None,
    repository_name_protected: bool | None,
    bypass_actors: list[dict[str, Any]] | None,
    rules: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Validate every field given and build the request body from them only."""
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = _validate_ruleset_name(name)
    if target is not None:
        body["target"] = validate_choice(target, TARGETS, "target")
        if target == "repository" and not org_level:
            raise ValueError("target repository is only valid for organization rulesets")
    if enforcement is not None:
        body["enforcement"] = validate_choice(enforcement, ENFORCEMENTS, "enforcement")
    conditions = _conditions(
        org_level=org_level,
        target=target,
        ref_name_include=ref_name_include,
        ref_name_exclude=ref_name_exclude,
        repository_name_include=repository_name_include,
        repository_name_exclude=repository_name_exclude,
        repository_name_protected=repository_name_protected,
    )
    if conditions is not None:
        body["conditions"] = conditions
    actors = _validate_bypass(bypass_actors, target)
    if actors is not None:
        body["bypass_actors"] = actors
    validated_rules = _validate_rules(rules)
    if validated_rules is not None:
        body["rules"] = validated_rules
    return body


async def create_ruleset(
    org: str,
    name: str,
    enforcement: str,
    target: str = "branch",
    repo: str | None = None,
    ref_name_include: list[str] | None = None,
    ref_name_exclude: list[str] | None = None,
    repository_name_include: list[str] | None = None,
    repository_name_exclude: list[str] | None = None,
    repository_name_protected: bool | None = None,
    bypass_actors: list[dict[str, Any]] | None = None,
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a ruleset on an organization, or on one repository.

    Args:
        org: Organization name (required; no default is applied)
        name: Ruleset name (1-100 characters)
        enforcement: disabled, active or evaluate
        target: branch, tag, push or repository (``repository`` only for
            organization rulesets)
        repo: Repository name; if unset, an organization ruleset is created
        ref_name_include: Ref patterns to match (``~DEFAULT_BRANCH`` and
            ``~ALL`` allowed); required for branch and tag targets
        ref_name_exclude: Ref patterns to skip
        repository_name_include: Repository name patterns (``~ALL`` allowed);
            required for organization rulesets, refused with ``repo``
        repository_name_exclude: Repository name patterns to skip
        repository_name_protected: Also match repositories by protection
        bypass_actors: List of {actor_id, actor_type, bypass_mode} objects
        rules: List of {type, parameters} objects; supported types are
            creation, deletion, required_linear_history, required_signatures,
            non_fast_forward, update, required_deployments, pull_request,
            required_status_checks, commit_message_pattern,
            commit_author_email_pattern, committer_email_pattern,
            branch_name_pattern, tag_name_pattern

    Returns:
        Trimmed created ruleset
    """
    path = _ruleset_path(org, repo)
    if name is None or enforcement is None or target is None:
        raise ValueError("name, enforcement and target are required")
    org_level = repo is None
    if org_level and not repository_name_include:
        raise ValueError("repository_name_include is required for organization rulesets")
    if target in ("branch", "tag") and not ref_name_include:
        raise ValueError(f"ref_name_include is required for target {target}")

    body = _build_body(
        org_level=org_level,
        name=name,
        enforcement=enforcement,
        target=target,
        ref_name_include=ref_name_include,
        ref_name_exclude=ref_name_exclude,
        repository_name_include=repository_name_include,
        repository_name_exclude=repository_name_exclude,
        repository_name_protected=repository_name_protected,
        bypass_actors=bypass_actors,
        rules=rules,
    )
    body.setdefault("rules", [])
    return _trim(await get_client().post(path, json_data=body))


async def update_ruleset(
    org: str,
    ruleset_id: int,
    repo: str | None = None,
    name: str | None = None,
    enforcement: str | None = None,
    target: str | None = None,
    ref_name_include: list[str] | None = None,
    ref_name_exclude: list[str] | None = None,
    repository_name_include: list[str] | None = None,
    repository_name_exclude: list[str] | None = None,
    repository_name_protected: bool | None = None,
    bypass_actors: list[dict[str, Any]] | None = None,
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Update a ruleset; only the fields given are sent.

    GitHub's PUT replaces what it is given: ``rules`` and ``bypass_actors``,
    when given, REPLACE the stored lists, so pass the complete list. If any
    condition field is given, the whole ``conditions`` object is sent, built
    from the condition fields given, and REPLACES the stored conditions: pass
    every condition you want to keep (for an organization ruleset, the
    repository_name_* fields along with any ref_name_* change); a
    conditions change that leaves out either half is refused.

    Args:
        org: Organization name (required; no default is applied)
        ruleset_id: Ruleset ID
        repo: Repository name; if unset, an organization ruleset is updated
        name: New ruleset name
        enforcement: disabled, active or evaluate
        target: branch, tag, push or repository
        ref_name_include: Ref patterns to match
        ref_name_exclude: Ref patterns to skip
        repository_name_include: Repository name patterns (organization only)
        repository_name_exclude: Repository name patterns to skip
        repository_name_protected: Also match repositories by protection
        bypass_actors: Complete list of {actor_id, actor_type, bypass_mode}
        rules: Complete list of {type, parameters} objects (types as in
            create_ruleset)

    Returns:
        Trimmed updated ruleset
    """
    path = _ruleset_path(org, repo)
    ruleset_id = validate_positive_int(ruleset_id, "ruleset_id")
    body = _build_body(
        org_level=repo is None,
        name=name,
        enforcement=enforcement,
        target=target,
        ref_name_include=ref_name_include,
        ref_name_exclude=ref_name_exclude,
        repository_name_include=repository_name_include,
        repository_name_exclude=repository_name_exclude,
        repository_name_protected=repository_name_protected,
        bypass_actors=bypass_actors,
        rules=rules,
    )
    if not body:
        raise ValueError("nothing to update: give at least one field")
    if "conditions" in body:
        # A partial conditions object would silently drop the part left out.
        if repo is None and repository_name_include is None:
            raise ValueError("a conditions change needs repository_name_include too")
        if ref_name_include is None and target not in ("push", "repository"):
            raise ValueError("a conditions change needs ref_name_include too")
    return _trim(await get_client().put(f"{path}/{ruleset_id}", json_data=body))
