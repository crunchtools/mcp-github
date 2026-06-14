"""FastMCP server setup for GitHub MCP.

This module creates and configures the MCP server with all tools.
"""

import logging
from typing import Any

from fastmcp import FastMCP

from .tools import (
    create_issue_comment,
    get_file_content,
    get_issue,
    get_pull_request,
    get_pull_request_checks,
    get_pull_request_diff,
    list_issues,
    list_pull_requests,
    list_repo_tree,
    search_code,
    search_issues,
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="mcp-github",
    version="0.1.0",
    instructions=(
        "Secure MCP server for GitHub repositories: issues, pull requests "
        "(diffs and CI checks), repository files, and code/issue search. "
        "Works with github.com and GitHub Enterprise Server."
    ),
)


@mcp.tool()
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


@mcp.tool()
async def get_issue_tool(
    repo: str,
    issue_number: int,
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
    return await create_issue_comment(
        owner=owner, repo=repo, issue_number=issue_number, body=body
    )


@mcp.tool()
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


@mcp.tool()
async def get_pull_request_tool(
    repo: str,
    pull_number: int,
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


@mcp.tool()
async def get_pull_request_diff_tool(
    repo: str,
    pull_number: int,
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
    return await get_pull_request_diff(
        owner=owner, repo=repo, pull_number=pull_number
    )


@mcp.tool()
async def get_pull_request_checks_tool(
    repo: str,
    pull_number: int,
    owner: str | None = None,
) -> dict[str, Any]:
    """Get a combined CI status summary for a GitHub pull request.

    Combines check-runs and the legacy commit status into one summary,
    including the overall state and per-check conclusions.

    Args:
        repo: Repository name
        pull_number: Pull request number
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)

    Returns:
        Summary with head SHA, overall state, and per-check conclusions
    """
    return await get_pull_request_checks(
        owner=owner, repo=repo, pull_number=pull_number
    )


@mcp.tool()
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


@mcp.tool()
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
    return await list_repo_tree(
        owner=owner, repo=repo, tree_sha=tree_sha, recursive=recursive
    )


@mcp.tool()
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


@mcp.tool()
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
