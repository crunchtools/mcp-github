# Claude Code Instructions

Secure MCP server for the GitHub REST API with 11 MVP tools across issues, pull requests, files, and search. Works with github.com and GitHub Enterprise Server.

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
3. Grant read access to repository contents, issues, and pull requests
   (add write to issues/PRs only if you need `create_issue_comment_tool`)
4. Copy the token immediately (shown only once)

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_TOKEN` | Yes | — | GitHub Personal Access Token |
| `GITHUB_API_URL` | No | `https://api.github.com` | API base URL (set for GHES) |
| `GITHUB_DEFAULT_ORG` | No | — | Default owner when a tool omits `owner` |
| `SSL_CERT_FILE` | No | — | Custom CA bundle for self-hosted instances |
| `GITHUB_SSL_VERIFY` | No | `true` | Set `false` to disable SSL verification |

## Available Tools (11)

| Category | Tools |
|----------|-------|
| Issues | `list_issues_tool`, `get_issue_tool`, `create_issue_comment_tool` |
| Pull Requests | `list_pull_requests_tool`, `get_pull_request_tool`, `get_pull_request_diff_tool`, `get_pull_request_checks_tool` |
| Files | `get_file_content_tool`, `list_repo_tree_tool` |
| Search | `search_code_tool`, `search_issues_tool` |

`create_issue_comment_tool` is the only write tool; the gateway scopes it.

## Example Usage

```
List open issues for crunchtools/mcp-github
Get the diff for PR #5 in crunchtools/mcp-github
Show CI checks for pull request 5
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
