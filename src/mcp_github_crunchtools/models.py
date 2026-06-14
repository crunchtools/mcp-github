"""Pydantic models and validation helpers for input validation.

All tool inputs are validated through these helpers to prevent injection
attacks and ensure data integrity before making API calls.
"""

import re

from pydantic import BaseModel, ConfigDict, Field

from .config import get_config

SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

ISSUE_STATES = frozenset({"open", "closed", "all"})
PR_STATES = frozenset({"open", "closed", "all"})

MAX_NAME_LENGTH = 100
MAX_PATH_LENGTH = 1000
MAX_COMMENT_LENGTH = 65536
MAX_QUERY_LENGTH = 1000
MAX_PER_PAGE = 100


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
            raise ValueError(
                "owner is required (or set GITHUB_DEFAULT_ORG)"
            )
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
            f"{field} must contain only letters, digits, dots, hyphens, "
            "and underscores"
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


class CreateIssueCommentInput(BaseModel):
    """Validated input for creating an issue comment."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(
        ...,
        min_length=1,
        max_length=MAX_COMMENT_LENGTH,
        description="Comment body (Markdown)",
    )
