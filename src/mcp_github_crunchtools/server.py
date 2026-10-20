"""FastMCP server setup for GitHub MCP.

This module creates and configures the MCP server with all tools.
"""

import logging
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from .tools import (
    create_issue,
    create_issue_comment,
    create_pull_request,
    create_release,
    get_failed_job_logs,
    get_file_content,
    get_issue,
    get_pull_request,
    get_pull_request_checks,
    get_pull_request_diff,
    get_workflow_run,
    list_issue_comments,
    list_issues,
    list_pull_request_comments,
    list_pull_requests,
    list_repo_tree,
    list_workflow_runs,
    merge_pull_request,
    reply_to_review_comment,
    rerun_failed_jobs,
    rerun_workflow_run,
    search_code,
    search_issues,
    trigger_workflow,
    update_issue,
    update_pull_request,
)

logger = logging.getLogger(__name__)

# A gateway drops an invalid optional argument only on a tool annotated read-only;
# on anything else it refuses the call. Only tools that change nothing on GitHub get this.
READ_ONLY = {"readOnlyHint": True}

mcp = FastMCP(
    name="mcp-github",
    version="1.6.0",
    instructions=(
        "Secure MCP server for GitHub repositories: issues, pull requests "
        "(open, review discussion, diffs, CI checks, merge), Actions runs and "
        "failed-job logs, releases, repository files, and code/issue search. "
        "Works with github.com and GitHub Enterprise Server."
    ),
)


@mcp.tool(annotations=READ_ONLY)
async def list_issues_tool(
    repo: str,
    owner: str | None = None,
    state: str = "open",
    labels: str | None = None,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """List issues for a GitHub repository (pull requests excluded).

    Args:
        repo: Repository name
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        state: Filter by state (open, closed, all)
        labels: Comma-separated label names
        per_page: Results per page, max 100 (default: 30)
        page: Page number (default: 1)

    Returns:
        List of issues with pagination info
    """
    return await list_issues(
        owner=owner,
        repo=repo,
        state=state,
        labels=labels,
        per_page=per_page,
        page=page,
    )


@mcp.tool(annotations=READ_ONLY)
async def get_issue_tool(
    repo: str,
    issue_number: Annotated[int, Field(ge=1)],
    owner: str | None = None,
) -> dict[str, Any]:
    """Get a single GitHub issue by number.

    Args:
        repo: Repository name
        issue_number: Issue number (e.g., #42)
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Issue details
    """
    return await get_issue(owner=owner, repo=repo, issue_number=issue_number)


@mcp.tool(annotations=READ_ONLY)
async def list_issue_comments_tool(
    repo: str,
    issue_number: Annotated[int, Field(ge=1)],
    owner: str | None = None,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """List the comments on a GitHub issue or pull request conversation, oldest first.

    Works for plain issues, which list_pull_request_comments_tool does not.
    On a pull request it returns only the conversation comments; diff
    comments and reviews come from list_pull_request_comments_tool.

    Args:
        repo: Repository name
        issue_number: Issue or pull request number
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        per_page: Results per page, max 100 (default: 30)
        page: Page number (default: 1)

    Returns:
        {"issue_number", "items", "pagination"?}; each item carries id,
        author, author_association, created_at, updated_at, body, html_url
    """
    return await list_issue_comments(
        owner=owner,
        repo=repo,
        issue_number=issue_number,
        per_page=per_page,
        page=page,
    )


@mcp.tool()
async def create_issue_tool(
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """Create a new issue in a GitHub repository.

    Args:
        repo: Repository name
        title: Issue title (required, non-empty)
        body: Issue body (Markdown)
        labels: Optional list of label names to apply
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Created issue details (number, html_url, title)
    """
    return await create_issue(owner=owner, repo=repo, title=title, body=body, labels=labels)


@mcp.tool()
async def create_issue_comment_tool(
    repo: str,
    issue_number: int,
    body: str,
    owner: str | None = None,
) -> dict[str, Any]:
    """Create a comment on a GitHub issue or pull request.

    Args:
        repo: Repository name
        issue_number: Issue or pull request number
        body: Comment body (Markdown)
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Created comment details
    """
    return await create_issue_comment(owner=owner, repo=repo, issue_number=issue_number, body=body)


@mcp.tool()
async def update_issue_tool(
    repo: str,
    issue_number: int,
    state: str | None = None,
    state_reason: str | None = None,
    title: str | None = None,
    body: str | None = None,
    labels: list[str] | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """Update a GitHub issue, including closing or reopening it.

    Set state="closed" to close an issue. Set state="open" with
    state_reason="reopened" to reopen.

    Args:
        repo: Repository name
        issue_number: Issue number
        state: "open" or "closed"
        state_reason: "completed", "not_planned", or "reopened"
        title: New title (optional)
        body: New body (optional)
        labels: Replacement list of label names (optional)
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Updated issue details (number, state, html_url, title)
    """
    return await update_issue(
        owner=owner,
        repo=repo,
        issue_number=issue_number,
        state=state,
        state_reason=state_reason,
        title=title,
        body=body,
        labels=labels,
    )


@mcp.tool(annotations=READ_ONLY)
async def list_pull_requests_tool(
    repo: str,
    owner: str | None = None,
    state: str = "open",
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """List pull requests for a GitHub repository.

    Args:
        repo: Repository name
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        state: Filter by state (open, closed, all)
        per_page: Results per page, max 100 (default: 30)
        page: Page number (default: 1)

    Returns:
        List of pull requests with pagination info
    """
    return await list_pull_requests(
        owner=owner,
        repo=repo,
        state=state,
        per_page=per_page,
        page=page,
    )


@mcp.tool(annotations=READ_ONLY)
async def get_pull_request_tool(
    repo: str,
    pull_number: Annotated[int, Field(ge=1)],
    owner: str | None = None,
) -> dict[str, Any]:
    """Get a single GitHub pull request by number.

    Args:
        repo: Repository name
        pull_number: Pull request number
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Pull request details including head/base refs and merge status
    """
    return await get_pull_request(owner=owner, repo=repo, pull_number=pull_number)


@mcp.tool(annotations=READ_ONLY)
async def get_pull_request_diff_tool(
    repo: str,
    pull_number: Annotated[int, Field(ge=1)],
    owner: str | None = None,
) -> dict[str, Any]:
    """Get the unified diff for a GitHub pull request.

    Args:
        repo: Repository name
        pull_number: Pull request number
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Dictionary with the diff text under the "content" key
    """
    return await get_pull_request_diff(owner=owner, repo=repo, pull_number=pull_number)


@mcp.tool(annotations=READ_ONLY)
async def get_pull_request_checks_tool(
    repo: str,
    pull_number: Annotated[int, Field(ge=1)],
    owner: str | None = None,
) -> dict[str, Any]:
    """Get a CI verdict for a PR that distinguishes skipped from failed.

    Classifies every check-run and commit-status context into passed,
    failing, pending, or skipped. SKIPPED checks are NOT failures. Use the
    returned ``ready_to_merge`` boolean as the signal for whether the PR is
    clear to merge (True only when nothing is failing or pending and the PR
    is not known-unmergeable). A token that cannot read check-runs (any
    fine-grained token) gets the Actions jobs instead; ``checks_source`` says
    which, and only Actions-reported checks are then visible.

    Args:
        repo: Repository name
        pull_number: Pull request number
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        A verdict with head SHA, mergeability, ready_to_merge, a summary
        count, and per-bucket check lists
    """
    return await get_pull_request_checks(owner=owner, repo=repo, pull_number=pull_number)


@mcp.tool()
async def update_pull_request_tool(
    repo: str,
    pull_number: int,
    state: str | None = None,
    title: str | None = None,
    body: str | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """Update a GitHub pull request, including closing or reopening it.

    This does NOT merge. Set state="closed" to close a PR without merging.

    Args:
        repo: Repository name
        pull_number: Pull request number
        state: "open" or "closed"
        title: New title (optional)
        body: New body (optional)
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Updated PR details (number, state, html_url, title)
    """
    return await update_pull_request(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        state=state,
        title=title,
        body=body,
    )


@mcp.tool()
async def create_pull_request_tool(
    repo: str,
    title: str,
    head: str,
    base: str,
    body: str = "",
    draft: bool = False,
    owner: str | None = None,
) -> dict[str, Any]:
    """Open a GitHub pull request.

    Args:
        repo: Repository name
        title: Pull request title (required, non-empty)
        head: Branch holding the changes; "owner:branch" for a fork
        base: Branch the changes should be merged into (e.g. "main")
        body: Pull request description (Markdown)
        draft: Open the pull request as a draft (default: false)
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Created PR details (number, html_url, title, state, draft)
    """
    return await create_pull_request(
        owner=owner,
        repo=repo,
        title=title,
        head=head,
        base=base,
        body=body,
        draft=draft,
    )


@mcp.tool()
async def merge_pull_request_tool(
    repo: str,
    pull_number: int,
    merge_method: str = "merge",
    sha: str | None = None,
    allow_no_required_checks: bool = False,
    owner: str | None = None,
) -> dict[str, Any]:
    """Merge a GitHub pull request, only once its required checks are green.

    The tool enforces the base branch's required status checks itself before
    merging, because an organization owner's token (or one on a ruleset's
    bypass list) lets GitHub merge past failing required checks. It refuses,
    naming each offending check, when a required check run or status on the
    PR head is missing, pending or failed; when ``sha`` is not the current
    head; when branch protection cannot be read; and when the base branch
    requires no checks at all, unless ``allow_no_required_checks`` is True.
    Passing check runs conclude success, skipped or neutral. The merge is
    pinned to the head SHA that was checked. A token that cannot read
    check-runs (any fine-grained token) is judged on the Actions jobs, and a
    required check not reported by GitHub Actions is refused as missing.

    Args:
        repo: Repository name
        pull_number: Pull request number
        merge_method: "merge", "squash", or "rebase" (default: merge)
        sha: Full commit SHA the PR head must still be at (optional)
        allow_no_required_checks: Merge even if the base branch requires no
            status checks (default: False, refuse)
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Merge result (merged, sha of the merge commit, message), the
        head_sha that was checked, and the required_checks
    """
    return await merge_pull_request(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        merge_method=merge_method,
        sha=sha,
        allow_no_required_checks=allow_no_required_checks,
    )


@mcp.tool(annotations=READ_ONLY)
async def list_pull_request_comments_tool(
    repo: str,
    pull_number: Annotated[int, Field(ge=1)],
    owner: str | None = None,
) -> dict[str, Any]:
    """List everything said on a GitHub pull request, in one list.

    Combines the PR's conversation comments (kind "issue_comment"), comments
    on the diff (kind "review_comment", with path, line, review_id and
    in_reply_to_id) and submitted reviews (kind "review", with state), oldest
    first. Every item carries kind, id, author, created_at, body and html_url.

    Each kind is capped at 300 items; ``truncated`` and ``truncated_kinds``
    say when newer items were left out.

    Args:
        repo: Repository name
        pull_number: Pull request number
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        {"pull_number", "total_count", "truncated", "truncated_kinds", "items"}
    """
    return await list_pull_request_comments(owner=owner, repo=repo, pull_number=pull_number)


@mcp.tool()
async def reply_to_review_comment_tool(
    repo: str,
    pull_number: int,
    comment_id: int,
    body: str,
    owner: str | None = None,
) -> dict[str, Any]:
    """Reply in the thread of a pull request review comment.

    ``comment_id`` is the id of a "review_comment" item from
    list_pull_request_comments_tool whose in_reply_to_id is empty; GitHub
    rejects a reply to a reply, so answer the comment that started the thread.

    Args:
        repo: Repository name
        pull_number: Pull request number
        comment_id: ID of the review comment to reply to
        body: Reply body (Markdown)
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Created reply details (id, html_url, in_reply_to_id)
    """
    return await reply_to_review_comment(
        owner=owner,
        repo=repo,
        pull_number=pull_number,
        comment_id=comment_id,
        body=body,
    )


@mcp.tool(annotations=READ_ONLY)
async def get_file_content_tool(
    repo: str,
    path: str,
    owner: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    """Get the decoded text content of a file in a GitHub repository.

    Args:
        repo: Repository name
        path: Path to the file within the repository
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        ref: Branch, tag, or commit SHA (default: the default branch)

    Returns:
        File metadata plus decoded text (or a notice if binary/too large)
    """
    return await get_file_content(owner=owner, repo=repo, path=path, ref=ref)


@mcp.tool(annotations=READ_ONLY)
async def list_repo_tree_tool(
    repo: str,
    owner: str | None = None,
    tree_sha: str = "HEAD",
    recursive: bool = False,
) -> dict[str, Any]:
    """List the git tree (files and directories) of a GitHub repository.

    Args:
        repo: Repository name
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        tree_sha: Tree SHA, branch name, or "HEAD" (default: HEAD)
        recursive: Recurse into subtrees (default: false)

    Returns:
        Tree listing with entries and a truncation flag
    """
    return await list_repo_tree(owner=owner, repo=repo, tree_sha=tree_sha, recursive=recursive)


@mcp.tool(annotations=READ_ONLY)
async def search_code_tool(
    query: str,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """Search for code across GitHub.

    Uses GitHub code search syntax (e.g., "addClass repo:jquery/jquery").

    Args:
        query: Search query string
        per_page: Results per page, max 100 (default: 30)
        page: Page number (default: 1)

    Returns:
        Search results with total count and matched code items
    """
    return await search_code(query=query, per_page=per_page, page=page)


@mcp.tool(annotations=READ_ONLY)
async def search_issues_tool(
    query: str,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """Search for issues and pull requests across GitHub.

    Uses GitHub issue search syntax (e.g., "is:open is:pr author:octocat").

    Args:
        query: Search query string
        per_page: Results per page, max 100 (default: 30)
        page: Page number (default: 1)

    Returns:
        Search results with total count and matched issues/PRs
    """
    return await search_issues(query=query, per_page=per_page, page=page)


@mcp.tool(annotations=READ_ONLY)
async def list_workflow_runs_tool(
    repo: str,
    owner: str | None = None,
    branch: str | None = None,
    status: str | None = None,
    per_page: int = 20,
    page: int = 1,
) -> dict[str, Any]:
    """List GitHub Actions workflow runs for a repository.

    Args:
        repo: Repository name
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        branch: Filter by head branch name
        status: Filter by status or conclusion (e.g., "completed",
            "in_progress", "queued", "failure", "success")
        per_page: Results per page, max 100 (default: 20)
        page: Page number (default: 1)

    Returns:
        Trimmed list of workflow runs with total count
    """
    return await list_workflow_runs(
        owner=owner,
        repo=repo,
        branch=branch,
        status=status,
        per_page=per_page,
        page=page,
    )


@mcp.tool()
async def trigger_workflow_tool(
    repo: str,
    workflow_id: str,
    ref: str | None = None,
    inputs: dict[str, Any] | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """Trigger a fresh GitHub Actions run via the workflow_dispatch event.

    Use this to force a new build. Unlike rerun_workflow_run_tool (which
    re-runs an existing run and is rejected by GitHub for runs older than 30
    days), this starts a brand-new run regardless of when the workflow last
    ran. The target workflow must declare an ``on: workflow_dispatch`` trigger.

    Args:
        repo: Repository name
        workflow_id: Workflow file name (e.g. "build.yml") or its numeric ID
        ref: Git ref (branch or tag) to run on (default: the repo's
            default branch)
        inputs: Optional workflow_dispatch inputs as name/value pairs
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        A confirmation dict:
        {"status": "dispatch_requested", "workflow": ..., "ref": ...}
    """
    return await trigger_workflow(
        owner=owner,
        repo=repo,
        workflow_id=workflow_id,
        ref=ref,
        inputs=inputs,
    )


@mcp.tool()
async def rerun_workflow_run_tool(
    repo: str,
    run_id: int,
    owner: str | None = None,
) -> dict[str, Any]:
    """Re-run all jobs in a GitHub Actions workflow run.

    Args:
        repo: Repository name
        run_id: Workflow run ID
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        A confirmation dict: {"status": "rerun_requested", "run_id": run_id}
    """
    return await rerun_workflow_run(owner=owner, repo=repo, run_id=run_id)


@mcp.tool()
async def rerun_failed_jobs_tool(
    repo: str,
    run_id: int,
    owner: str | None = None,
) -> dict[str, Any]:
    """Re-run only the failed jobs in a GitHub Actions workflow run.

    Args:
        repo: Repository name
        run_id: Workflow run ID
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        A confirmation dict: {"status": "rerun_requested", "run_id": run_id}
    """
    return await rerun_failed_jobs(owner=owner, repo=repo, run_id=run_id)


@mcp.tool(annotations=READ_ONLY)
async def get_workflow_run_tool(
    repo: str,
    run_id: Annotated[int, Field(ge=1)],
    owner: str | None = None,
) -> dict[str, Any]:
    """Get one GitHub Actions workflow run and its jobs (no logs).

    Args:
        repo: Repository name
        run_id: Workflow run ID
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        The run's status, conclusion, head_sha, head_branch, event and
        html_url, plus its jobs (id, name, status, conclusion)
    """
    return await get_workflow_run(owner=owner, repo=repo, run_id=run_id)


@mcp.tool(annotations=READ_ONLY)
async def get_failed_job_logs_tool(
    repo: str,
    run_id: Annotated[int, Field(ge=1)],
    tail_lines: int = 200,
    owner: str | None = None,
) -> dict[str, Any]:
    """Get the end of the log of each failed job in a GitHub Actions run.

    Returns the last ``tail_lines`` lines of every job that failed or timed
    out, with ANSI escapes and timestamps removed, and the names of the steps
    that failed. Logs are fetched for at most 5 failed jobs and all log text
    together is capped at 256 KiB; ``truncated`` and ``failed_jobs_omitted``
    say when something was cut. ``jobs_truncated`` means the run has more than
    the 300 jobs examined, so the failed-job counts cover only those.

    Args:
        repo: Repository name
        run_id: Workflow run ID
        tail_lines: Lines to return from the end of each log (default 200,
            max 1000)
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        {"run_id", "tail_lines", "failed_job_count", "failed_jobs_omitted",
        "jobs_truncated", "truncated", "jobs": [{"id", "name", "conclusion",
        "html_url", "failed_steps", "log", "log_lines", "truncated"}]}
    """
    return await get_failed_job_logs(
        owner=owner,
        repo=repo,
        run_id=run_id,
        tail_lines=tail_lines,
    )


@mcp.tool()
async def create_release_tool(
    repo: str,
    tag_name: str,
    target_commitish: str | None = None,
    name: str | None = None,
    body: str = "",
    draft: bool = False,
    prerelease: bool = False,
    generate_release_notes: bool = False,
    owner: str | None = None,
) -> dict[str, Any]:
    """Create a GitHub release, creating its tag if the tag does not exist.

    Publishing a release (draft=false) fires the repository's
    ``on: release`` workflows, such as package and image publishing.

    Args:
        repo: Repository name
        tag_name: Tag of the release (e.g. "v1.2.0")
        target_commitish: Branch or commit SHA to tag when the tag does not
            exist yet (default: the repository's default branch)
        name: Release title (default: the tag name)
        body: Release notes (Markdown)
        draft: Create an unpublished draft (default: false)
        prerelease: Mark the release as a prerelease (default: false)
        generate_release_notes: Let GitHub generate the notes, with ``body``
            in front of them (default: false)
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Created release details (id, tag_name, name, html_url, draft,
        prerelease)
    """
    return await create_release(
        owner=owner,
        repo=repo,
        tag_name=tag_name,
        target_commitish=target_commitish,
        name=name,
        body=body,
        draft=draft,
        prerelease=prerelease,
        generate_release_notes=generate_release_notes,
    )
