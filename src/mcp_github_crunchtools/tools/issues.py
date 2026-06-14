"""Issue management tools.

Tools for listing, fetching, and commenting on GitHub issues.
"""

from typing import Any

from ..client import get_client
from ..errors import ValidationError
from ..models import (
    ISSUE_STATES,
    CreateIssueCommentInput,
    CreateIssueInput,
    clamp_per_page,
    resolve_owner,
    validate_name,
    validate_positive_int,
)


async def list_issues(
    owner: str | None,
    repo: str,
    state: str = "open",
    labels: str | None = None,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """List issues for a repository.

    Pull requests are filtered out (the GitHub issues endpoint includes PRs).

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        state: Filter by state (open, closed, all)
        labels: Comma-separated label names
        per_page: Results per page (max 100)
        page: Page number

    Returns:
        List of issues with pagination info
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    if state not in ISSUE_STATES:
        allowed = ", ".join(sorted(ISSUE_STATES))
        raise ValidationError(f"Invalid state. Allowed: {allowed}")

    client = get_client()

    params: dict[str, Any] = {
        "state": state,
        "per_page": clamp_per_page(per_page),
        "page": validate_positive_int(page, "page"),
    }
    if labels:
        params["labels"] = labels

    result = await client.get(f"/repos/{owner}/{repo}/issues", params=params)

    items = result.get("items", [])
    result["items"] = [item for item in items if "pull_request" not in item]

    return result


async def get_issue(
    owner: str | None,
    repo: str,
    issue_number: int,
) -> dict[str, Any]:
    """Get a single issue by number.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        issue_number: Issue number (the value shown in the UI, e.g., #42)

    Returns:
        Issue details
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    issue_number = validate_positive_int(issue_number, "issue_number")

    client = get_client()
    return await client.get(f"/repos/{owner}/{repo}/issues/{issue_number}")


async def create_issue(
    owner: str | None,
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new issue in a repository.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        title: Issue title (required, non-empty)
        body: Issue body (Markdown)
        labels: Optional list of label names to apply

    Returns:
        Created issue details (number, html_url, title)
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    if not title or not title.strip():
        raise ValidationError("title must not be empty")
    validated = CreateIssueInput(title=title.strip(), body=body)

    json_data: dict[str, Any] = {
        "title": validated.title,
        "body": validated.body,
    }
    if labels:
        json_data["labels"] = labels

    client = get_client()
    result = await client.post(
        f"/repos/{owner}/{repo}/issues",
        json_data=json_data,
    )
    return {
        "number": result.get("number"),
        "html_url": result.get("html_url"),
        "title": result.get("title"),
    }


async def update_issue(
    owner: str | None,
    repo: str,
    issue_number: int,
    state: str | None = None,
    state_reason: str | None = None,
    title: str | None = None,
    body: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing issue — including closing or reopening it.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        issue_number: Issue number
        state: "open" or "closed" (set "closed" to close the issue)
        state_reason: When closing, one of "completed" or "not_planned";
            when reopening, "reopened"
        title: New title (optional)
        body: New body (optional)
        labels: Replacement list of label names (optional)

    Returns:
        Updated issue details (number, state, html_url, title)
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    issue_number = validate_positive_int(issue_number, "issue_number")

    json_data: dict[str, Any] = {}
    if state is not None:
        if state not in ("open", "closed"):
            raise ValidationError("state must be 'open' or 'closed'")
        json_data["state"] = state
    if state_reason is not None:
        if state_reason not in ("completed", "not_planned", "reopened"):
            raise ValidationError(
                "state_reason must be 'completed', 'not_planned', or 'reopened'"
            )
        json_data["state_reason"] = state_reason
    if title is not None:
        json_data["title"] = title
    if body is not None:
        json_data["body"] = body
    if labels is not None:
        json_data["labels"] = labels
    if not json_data:
        raise ValidationError("no fields to update")

    client = get_client()
    result = await client.patch(
        f"/repos/{owner}/{repo}/issues/{issue_number}",
        json_data=json_data,
    )
    return {
        "number": result.get("number"),
        "state": result.get("state"),
        "html_url": result.get("html_url"),
        "title": result.get("title"),
    }


async def create_issue_comment(
    owner: str | None,
    repo: str,
    issue_number: int,
    body: str,
) -> dict[str, Any]:
    """Create a comment on an issue or pull request.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        issue_number: Issue or pull request number
        body: Comment body (Markdown)

    Returns:
        Created comment details
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    issue_number = validate_positive_int(issue_number, "issue_number")
    validated = CreateIssueCommentInput(body=body)

    client = get_client()
    return await client.post(
        f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
        json_data={"body": validated.body},
    )
