"""Pydantic models and validation helpers for input validation.

All tool inputs are validated through these helpers to prevent injection
attacks and ensure data integrity before making API calls.
"""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import get_config

SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_REF_PATTERN = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
# A full commit id: 40 hex digits (SHA-1) or 64 (SHA-256 repositories).
COMMIT_SHA_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

ISSUE_STATES = frozenset({"open", "closed", "all"})
PR_STATES = frozenset({"open", "closed", "all"})
MERGE_METHODS = frozenset({"merge", "squash", "rebase"})

MAX_NAME_LENGTH = 100
MAX_PATH_LENGTH = 1000
MAX_COMMENT_LENGTH = 65536
MAX_QUERY_LENGTH = 1000
MAX_PER_PAGE = 100
MAX_TITLE_LENGTH = 256
MAX_BODY_LENGTH = 65536
MAX_REF_LENGTH = 255
MAX_WORKFLOW_INPUTS = 32


def resolve_owner(owner: str | None) -> str:
    """Resolve and validate a repository owner.

    Falls back to GITHUB_DEFAULT_ORG when no owner is supplied.

    Args:
        owner: Owner login (user or organization), or None.

    Returns:
        A validated owner login.

    Raises:
        ValueError: If no owner is available or the value is invalid.
    """
    if owner is None or not owner.strip():
        default = get_config().default_org
        if not default:
            raise ValueError("owner is required (or set GITHUB_DEFAULT_ORG)")
        owner = default

    return validate_name(owner, "owner")


def validate_name(value: str, field: str) -> str:
    """Validate an owner or repository name against a safe allowlist.

    Args:
        value: The value to validate.
        field: Field name for error messages.

    Returns:
        The stripped, validated value.

    Raises:
        ValueError: If the value is empty or contains disallowed characters.
    """
    if not value or not value.strip():
        raise ValueError(f"{field} must not be empty")

    value = value.strip()

    if len(value) > MAX_NAME_LENGTH:
        raise ValueError(f"{field} is too long")

    if not SAFE_NAME_PATTERN.match(value):
        raise ValueError(
            f"{field} must contain only letters, digits, dots, hyphens, and underscores"
        )

    return value


def validate_positive_int(value: int, field: str) -> int:
    """Validate that a value is a positive integer.

    Args:
        value: The value to validate.
        field: Field name for error messages.

    Returns:
        The validated integer.

    Raises:
        ValueError: If the value is not a positive integer.
    """
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def clamp_per_page(per_page: int) -> int:
    """Clamp per_page to GitHub's allowed range (1-100)."""
    return max(1, min(per_page, MAX_PER_PAGE))


def validate_ref(value: str, field: str = "ref") -> str:
    """Validate a git ref (branch or tag name).

    Unlike names, refs may contain slashes between non-empty segments (e.g.
    "release/1.2"), but must reject whitespace, control characters, ".."
    traversal, empty "//" segments, and leading/trailing "." or "/" — in
    line with git's check-ref-format rules, so invalid refs are caught here
    rather than as a GitHub 422.

    Args:
        value: The ref to validate.
        field: Field name for error messages.

    Returns:
        The stripped, validated ref.

    Raises:
        ValueError: If the ref is empty, too long, malformed, or contains
            disallowed characters.
    """
    if not value or not value.strip():
        raise ValueError(f"{field} must not be empty")

    value = value.strip()

    if len(value) > MAX_REF_LENGTH:
        raise ValueError(f"{field} is too long")

    if (
        ".." in value
        or "//" in value
        or "./" in value
        or value.startswith((".", "/"))
        or value.endswith((".", "/"))
    ):
        raise ValueError(f"{field} is not a valid git ref")

    if not SAFE_REF_PATTERN.match(value):
        raise ValueError(
            f"{field} must contain only letters, digits, dots, hyphens, underscores, and slashes"
        )

    return value


def validate_head(value: str) -> str:
    """Validate the head of a new pull request.

    GitHub accepts a branch in the same repository ("feature/x") or a branch
    in a fork, written "owner:branch". The owner part follows the name rules
    and the branch part the ref rules.

    Args:
        value: The head branch, optionally prefixed with "owner:".

    Returns:
        The stripped, validated head.

    Raises:
        ValueError: If either part is empty or contains disallowed characters.
    """
    fork_owner, colon, branch = value.strip().rpartition(":")
    if not colon:
        return validate_ref(branch, "head")
    return f"{validate_name(fork_owner, 'head owner')}:{validate_ref(branch, 'head')}"


def validate_commit_sha(value: str | None, field: str = "sha") -> str | None:
    """Validate an optional full commit SHA.

    An empty or whitespace-only value means "not given" and becomes None.

    Args:
        value: The SHA, or None.
        field: Field name for error messages.

    Returns:
        The lower-cased SHA, or None when no value was given.

    Raises:
        ValueError: If a value was given that is not 40 or 64 hex digits.
    """
    if value is None or not value.strip():
        return None

    value = value.strip().lower()
    if not COMMIT_SHA_PATTERN.match(value):
        raise ValueError(f"{field} must be a full 40 or 64 character commit SHA")
    return value


def validate_workflow_inputs(inputs: dict[str, object]) -> dict[str, object]:
    """Validate workflow_dispatch inputs before sending them to GitHub.

    Args:
        inputs: Mapping of input name to a primitive value.

    Returns:
        The validated inputs mapping.

    Raises:
        ValueError: If there are too many inputs, a key is not a safe name,
            or a value is not a string, number, or boolean.
    """
    is_mapping = isinstance(inputs, dict)
    if not is_mapping:
        raise ValueError("inputs must be an object of name/value pairs")

    if len(inputs) > MAX_WORKFLOW_INPUTS:
        raise ValueError(f"inputs may not exceed {MAX_WORKFLOW_INPUTS} entries")

    for key, value in inputs.items():
        validate_name(key, "inputs key")
        is_primitive = isinstance(value, (str, int, float, bool))
        if not is_primitive:
            raise ValueError(f"inputs value for '{key}' must be a string, number, or boolean")

    return inputs


class CreateIssueCommentInput(BaseModel):
    """Validated input for creating an issue comment."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(
        ...,
        min_length=1,
        max_length=MAX_COMMENT_LENGTH,
        description="Comment body (Markdown)",
    )


class CreateIssueInput(BaseModel):
    """Validated input for creating an issue."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        ...,
        min_length=1,
        max_length=MAX_TITLE_LENGTH,
        description="Issue title",
    )
    body: str = Field(
        default="",
        max_length=MAX_BODY_LENGTH,
        description="Issue body (Markdown)",
    )


class CreateReleaseInput(BaseModel):
    """Validated input for the free-text fields of a new release."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        max_length=MAX_TITLE_LENGTH,
        description="Release title (GitHub uses the tag name when omitted)",
    )
    body: str = Field(
        default="",
        max_length=MAX_BODY_LENGTH,
        description="Release notes (Markdown)",
    )

    @field_validator("name", mode="before")
    @classmethod
    def _blank_name_is_not_given(cls, value: object) -> object:
        """An empty or whitespace-only optional name means "not given"."""
        if isinstance(value, str):
            return value.strip() or None
        return value
