"""Pull request tools.

Tools for listing, fetching, diffing, checking, opening, merging, and
discussing GitHub pull requests.
"""

from typing import Any

from ..client import GitHubClient, get_client
from ..errors import ValidationError
from ..models import (
    MAX_PER_PAGE,
    MERGE_METHODS,
    PR_STATES,
    CreateIssueCommentInput,
    CreateIssueInput,
    clamp_per_page,
    resolve_owner,
    validate_commit_sha,
    validate_head,
    validate_name,
    validate_positive_int,
    validate_ref,
)

DIFF_ACCEPT = "application/vnd.github.diff"

# list_pull_request_comments reads three collections. Each is fetched at
# MAX_PER_PAGE per request up to this many items, so one call returns at most
# three times this and costs at most nine requests.
MAX_PR_COMMENTS_PER_KIND = 3 * MAX_PER_PAGE


async def list_pull_requests(
    owner: str | None,
    repo: str,
    state: str = "open",
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """List pull requests for a repository.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        state: Filter by state (open, closed, all)
        per_page: Results per page (max 100)
        page: Page number

    Returns:
        List of pull requests with pagination info
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    if state not in PR_STATES:
        allowed = ", ".join(sorted(PR_STATES))
        raise ValidationError(f"Invalid state. Allowed: {allowed}")

    client = get_client()

    params: dict[str, Any] = {
        "state": state,
        "per_page": clamp_per_page(per_page),
        "page": validate_positive_int(page, "page"),
    }

    return await client.get(f"/repos/{owner}/{repo}/pulls", params=params)


async def get_pull_request(
    owner: str | None,
    repo: str,
    pull_number: int,
) -> dict[str, Any]:
    """Get a single pull request by number.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number

    Returns:
        Pull request details including head/base refs and merge status
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")

    client = get_client()
    return await client.get(f"/repos/{owner}/{repo}/pulls/{pull_number}")


async def get_pull_request_diff(
    owner: str | None,
    repo: str,
    pull_number: int,
) -> dict[str, Any]:
    """Get the unified diff for a pull request.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number

    Returns:
        Dictionary with the diff text under the "content" key
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")

    client = get_client()
    return await client.get(
        f"/repos/{owner}/{repo}/pulls/{pull_number}",
        accept=DIFF_ACCEPT,
    )


def _classify_checks(
    check_runs: dict[str, Any], combined_status: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Sort check-runs and commit-status contexts into verdict buckets.

    Check-run conclusions failure/cancelled/timed_out/action_required are
    failures; skipped/neutral are skips (NOT failures); success passes. An
    incomplete run, or any other completed conclusion, is pending. Commit
    statuses map failure/error -> failing, pending -> pending, success ->
    passed.
    """
    buckets: dict[str, list[dict[str, Any]]] = {
        "failing": [],
        "pending": [],
        "skipped": [],
        "passed": [],
    }

    for run in check_runs.get("check_runs", []):
        name = run.get("name")
        status = run.get("status")
        if status != "completed":
            buckets["pending"].append({"name": name, "status": status})
            continue
        match run.get("conclusion"):
            case ("failure" | "cancelled" | "timed_out" | "action_required") as conclusion:
                url = run.get("html_url") or run.get("details_url") or ""
                buckets["failing"].append({"name": name, "conclusion": conclusion, "url": url})
            case ("skipped" | "neutral") as conclusion:
                buckets["skipped"].append({"name": name, "conclusion": conclusion})
            case "success":
                buckets["passed"].append({"name": name})
            case _:
                buckets["pending"].append({"name": name, "status": status})

    for ctx in combined_status.get("statuses", []):
        name = ctx.get("context")
        match ctx.get("state"):
            case ("failure" | "error") as state:
                url = ctx.get("target_url") or ""
                buckets["failing"].append({"name": name, "conclusion": state, "url": url})
            case "pending":
                buckets["pending"].append({"name": name, "status": "pending"})
            case "success":
                buckets["passed"].append({"name": name})

    return buckets


async def get_pull_request_checks(
    owner: str | None,
    repo: str,
    pull_number: int,
) -> dict[str, Any]:
    """Get a CI verdict for a pull request that distinguishes skip from fail.

    Resolves the PR head SHA, then classifies every check-run (GitHub Checks
    API) and legacy commit-status context into exactly one bucket: passed,
    failing, pending, or skipped.

    IMPORTANT: SKIPPED checks (conclusion "skipped" or "neutral") are NOT
    failures and do not block merging. The legacy combined commit status can
    report an overall state of "failure" when checks are merely skipped, which
    is why this tool classifies each check explicitly instead of trusting that
    aggregate. Use the ``ready_to_merge`` boolean as the signal for whether the
    PR is clear to merge: it is True only when there are no failing and no
    pending checks and the PR is not known-unmergeable.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number

    Returns:
        A verdict with the head SHA, mergeability, per-bucket check lists, a
        summary count, and the ``ready_to_merge`` signal
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")

    client = get_client()

    pr = await client.get(f"/repos/{owner}/{repo}/pulls/{pull_number}")
    head = pr.get("head") or {}
    sha = head.get("sha")
    if not sha:
        raise ValidationError("Could not resolve pull request head SHA")

    check_runs = await client.get(f"/repos/{owner}/{repo}/commits/{sha}/check-runs")
    combined_status = await client.get(f"/repos/{owner}/{repo}/commits/{sha}/status")

    buckets = _classify_checks(check_runs, combined_status)
    failing = buckets["failing"]
    pending = buckets["pending"]
    skipped = buckets["skipped"]
    passed = buckets["passed"]

    mergeable = pr.get("mergeable")
    ready_to_merge = not failing and not pending and mergeable is not False

    return {
        "pull_number": pull_number,
        "head_sha": sha,
        "mergeable": mergeable,
        "mergeable_state": pr.get("mergeable_state", ""),
        "ready_to_merge": ready_to_merge,
        "summary": {
            "passed": len(passed),
            "failing": len(failing),
            "pending": len(pending),
            "skipped": len(skipped),
        },
        "failing": failing,
        "pending": pending,
        "skipped": skipped,
        "passed": passed,
    }


async def update_pull_request(
    owner: str | None,
    repo: str,
    pull_number: int,
    state: str | None = None,
    title: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """Update a pull request — including closing or reopening it.

    Note: this does NOT merge. Set state="closed" to close a PR without merging.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number
        state: "open" or "closed" (set "closed" to close the PR)
        title: New title (optional)
        body: New body (optional)

    Returns:
        Updated PR details (number, state, html_url, title)
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")

    json_data: dict[str, Any] = {}
    if state is not None:
        if state not in ("open", "closed"):
            raise ValidationError("state must be 'open' or 'closed'")
        json_data["state"] = state
    if title is not None:
        json_data["title"] = title
    if body is not None:
        json_data["body"] = body
    if not json_data:
        raise ValidationError("no fields to update")

    client = get_client()
    result = await client.patch(
        f"/repos/{owner}/{repo}/pulls/{pull_number}",
        json_data=json_data,
    )
    return {
        "number": result.get("number"),
        "state": result.get("state"),
        "html_url": result.get("html_url"),
        "title": result.get("title"),
    }


async def create_pull_request(
    owner: str | None,
    repo: str,
    title: str,
    head: str,
    base: str,
    body: str = "",
    draft: bool = False,
) -> dict[str, Any]:
    """Open a pull request.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        title: Pull request title (required, non-empty)
        head: Branch holding the changes; "owner:branch" for a fork
        base: Branch the changes should be merged into
        body: Pull request description (Markdown)
        draft: Open the pull request as a draft

    Returns:
        Created PR details (number, html_url, title, state, draft)
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    if not title or not title.strip():
        raise ValidationError("title must not be empty")
    # A pull request's title and body have the same limits as an issue's.
    validated = CreateIssueInput(title=title.strip(), body=body)

    client = get_client()
    result = await client.post(
        f"/repos/{owner}/{repo}/pulls",
        json_data={
            "title": validated.title,
            "body": validated.body,
            "head": validate_head(head),
            "base": validate_ref(base, "base"),
            "draft": draft,
        },
    )
    return {
        "number": result.get("number"),
        "html_url": result.get("html_url"),
        "title": result.get("title"),
        "state": result.get("state"),
        "draft": result.get("draft"),
    }


async def merge_pull_request(
    owner: str | None,
    repo: str,
    pull_number: int,
    merge_method: str = "merge",
    sha: str | None = None,
) -> dict[str, Any]:
    """Merge a pull request.

    GitHub answers 405 when the pull request cannot be merged (failing
    required checks, conflicts, a draft) and 409 when ``sha`` is given and is
    no longer the head of the branch. Both surface as a GitHubApiError that
    carries GitHub's message.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number
        merge_method: "merge", "squash", or "rebase"
        sha: Full commit SHA the PR head must still be at for the merge to
            happen (optional)

    Returns:
        Merge result (merged, sha of the merge commit, message)
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")
    if merge_method not in MERGE_METHODS:
        allowed = ", ".join(sorted(MERGE_METHODS))
        raise ValidationError(f"Invalid merge_method. Allowed: {allowed}")

    json_data: dict[str, Any] = {"merge_method": merge_method}
    expected_head = validate_commit_sha(sha)
    if expected_head:
        json_data["sha"] = expected_head

    client = get_client()
    result = await client.put(
        f"/repos/{owner}/{repo}/pulls/{pull_number}/merge",
        json_data=json_data,
    )
    return {
        "merged": result.get("merged"),
        "sha": result.get("sha"),
        "message": result.get("message"),
    }


async def _collect_pages(client: GitHubClient, path: str) -> tuple[list[dict[str, Any]], bool]:
    """Read a paginated list up to MAX_PR_COMMENTS_PER_KIND items.

    Returns the items and whether GitHub had more than were read.
    """
    collected: list[dict[str, Any]] = []
    has_more = False
    for page in range(1, MAX_PR_COMMENTS_PER_KIND // MAX_PER_PAGE + 1):
        result = await client.get(path, params={"per_page": MAX_PER_PAGE, "page": page})
        collected.extend(result.get("items", []))
        has_more = "next_page" in result.get("pagination", {})
        if not has_more:
            break
    cut = has_more or len(collected) > MAX_PR_COMMENTS_PER_KIND
    return collected[:MAX_PR_COMMENTS_PER_KIND], cut


def _discussion_item(kind: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Reduce an issue comment, review comment, or review to common fields.

    A review has no created_at; its submitted_at takes that place.
    """
    item: dict[str, Any] = {
        "kind": kind,
        "id": raw.get("id"),
        "author": (raw.get("user") or {}).get("login"),
        "created_at": raw.get("created_at") or raw.get("submitted_at"),
        "body": raw.get("body") or "",
        "html_url": raw.get("html_url"),
    }
    if kind == "review_comment":
        item["path"] = raw.get("path")
        item["line"] = raw.get("line")
        item["in_reply_to_id"] = raw.get("in_reply_to_id")
        item["review_id"] = raw.get("pull_request_review_id")
    if kind == "review":
        item["state"] = raw.get("state")
    return item


async def list_pull_request_comments(
    owner: str | None,
    repo: str,
    pull_number: int,
) -> dict[str, Any]:
    """List everything said on a pull request, in one chronological list.

    Combines three GitHub collections, tagging each item with its ``kind``:

    - ``issue_comment``: comments in the PR conversation
    - ``review_comment``: comments on the diff, with path, line, the review
      they belong to and, for a reply, the ``in_reply_to_id`` of the comment
      they answer
    - ``review``: submitted reviews, with their state (APPROVED,
      CHANGES_REQUESTED, COMMENTED, ...)

    Every item carries id, author (login), created_at, body and html_url.
    Each collection is read oldest first and capped; a kind named in
    ``truncated_kinds`` had newer items that are not in the result.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number

    Returns:
        {"pull_number", "total_count", "truncated", "truncated_kinds", "items"}
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")

    client = get_client()
    sources = {
        "issue_comment": f"/repos/{owner}/{repo}/issues/{pull_number}/comments",
        "review_comment": f"/repos/{owner}/{repo}/pulls/{pull_number}/comments",
        "review": f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
    }

    items: list[dict[str, Any]] = []
    truncated_kinds: list[str] = []
    for kind, path in sources.items():
        raw_items, cut = await _collect_pages(client, path)
        items.extend(_discussion_item(kind, raw) for raw in raw_items)
        if cut:
            truncated_kinds.append(kind)

    items.sort(key=lambda item: item["created_at"] or "")

    return {
        "pull_number": pull_number,
        "total_count": len(items),
        "truncated": bool(truncated_kinds),
        "truncated_kinds": truncated_kinds,
        "items": items,
    }


async def reply_to_review_comment(
    owner: str | None,
    repo: str,
    pull_number: int,
    comment_id: int,
    body: str,
) -> dict[str, Any]:
    """Reply in the thread of a pull request review comment.

    ``comment_id`` must be a top-level review comment (one whose
    ``in_reply_to_id`` is empty); GitHub rejects a reply to a reply.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        pull_number: Pull request number
        comment_id: ID of the review comment to reply to
        body: Reply body (Markdown)

    Returns:
        Created reply details (id, html_url, in_reply_to_id)
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    pull_number = validate_positive_int(pull_number, "pull_number")
    comment_id = validate_positive_int(comment_id, "comment_id")
    # A reply is a comment: same body limits as an issue comment.
    validated = CreateIssueCommentInput(body=body)

    client = get_client()
    result = await client.post(
        f"/repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies",
        json_data={"body": validated.body},
    )
    return {
        "id": result.get("id"),
        "html_url": result.get("html_url"),
        "in_reply_to_id": result.get("in_reply_to_id"),
    }
