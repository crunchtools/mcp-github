# Claude Code Instructions

Secure MCP server for the GitHub REST API with 25 tools across issues, pull requests, Actions, releases, files, and search. Works with github.com and GitHub Enterprise Server.

## Quick Start

```bash
# uvx (recommended)
claude mcp add mcp-github-crunchtools \
    --env GITHUB_TOKEN=your_token_here \
    -- uvx mcp-github-crunchtools

# Container
claude mcp add mcp-github-crunchtools \
    --env GITHUB_TOKEN=your_token_here \
    -- podman run -i --rm -e GITHUB_TOKEN quay.io/crunchtools/mcp-github

# GitHub Enterprise Server
claude mcp add mcp-github-crunchtools \
    --env GITHUB_TOKEN=your_token_here \
    --env GITHUB_API_URL=https://ghe.example.com/api/v3 \
    -- uvx mcp-github-crunchtools

# Local development
cd ~/Projects/crunchtools/mcp-github
claude mcp add mcp-github-crunchtools \
    --env GITHUB_TOKEN=your_token_here \
    -- uv run mcp-github-crunchtools
```

## Creating a GitHub Personal Access Token

1. Go to https://github.com/settings/tokens
2. Create a fine-grained or classic PAT named `mcp-github-crunchtools`
3. Grant read access to repository contents, issues, pull requests, and
   Actions. Add write only for the write tools you use: Issues and Pull
   requests for commenting, opening and updating; Contents for
   `merge_pull_request_tool` and `create_release_tool`; Actions for
   `trigger_workflow_tool` and `rerun_*`. The per-tool table is in README.md
   under "Token permissions".
4. Copy the token immediately (shown only once)

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_TOKEN` | Yes | — | GitHub Personal Access Token |
| `GITHUB_API_URL` | No | `https://api.github.com` | API base URL (set for GHES) |
| `GITHUB_DEFAULT_ORG` | No | — | Default owner when a tool omits `owner` |
| `SSL_CERT_FILE` | No | — | Custom CA bundle for self-hosted instances |
| `GITHUB_SSL_VERIFY` | No | `true` | Set `false` to disable SSL verification |

## Available Tools (25)

| Category | Tools |
|----------|-------|
| Issues | `list_issues_tool`, `get_issue_tool`, `create_issue_tool`, `create_issue_comment_tool`, `update_issue_tool` |
| Pull Requests | `list_pull_requests_tool`, `get_pull_request_tool`, `get_pull_request_diff_tool`, `get_pull_request_checks_tool`, `list_pull_request_comments_tool`, `create_pull_request_tool`, `update_pull_request_tool`, `reply_to_review_comment_tool`, `merge_pull_request_tool` |
| Files | `get_file_content_tool`, `list_repo_tree_tool` |
| Search | `search_code_tool`, `search_issues_tool` |
| Actions | `list_workflow_runs_tool`, `get_workflow_run_tool`, `get_failed_job_logs_tool`, `trigger_workflow_tool`, `rerun_workflow_run_tool`, `rerun_failed_jobs_tool` |
| Releases | `create_release_tool` |

Write tools (`create_*`, `update_*`, `merge_pull_request_tool`,
`reply_to_review_comment_tool`, `trigger_workflow_tool`, `rerun_*`)
are scoped per-profile by the gateway. `trigger_workflow_tool` dispatches a
fresh run (via `workflow_dispatch`) and is the way to *force* a build —
`rerun_*` only re-run an existing run and GitHub rejects runs older than 30
days.

`get_failed_job_logs_tool` is the one tool that talks to a host other than the
API: GitHub redirects a job log to a storage URL. `GitHubClient.get_redirected_tail`
follows it with a separate client that has no token. Keep it that way.

## Example Usage

```
List open issues for crunchtools/mcp-github
Get the diff for PR #5 in crunchtools/mcp-github
Show CI checks for pull request 5
Show the failed job logs for run 123456
List the review comments on PR 5 and reply to the first one
Squash-merge PR 5 in crunchtools/mcp-github
Create release v1.2.0 for crunchtools/mcp-github
Read src/server.py from crunchtools/mcp-github
Search code for "FastMCP" in repo:crunchtools/mcp-github
Search issues for "is:open label:bug org:crunchtools"
```

## Development

```bash
uv sync --all-extras          # Install dependencies
uv run ruff check src tests   # Lint
uv run mypy src               # Type check
uv run pytest -v              # Tests
gourmand --full .             # AI slop detection
```

Quality gates, testing standards, and architecture: `.specify/memory/constitution.md`
