# MCP GitHub CrunchTools

A secure MCP (Model Context Protocol) server for GitHub issues, pull requests, Actions runs, releases, repository files, and search. Works with github.com and GitHub Enterprise Server.

## Overview

This MCP server is designed to be:

- **Secure by default** - STRIDE threat model (see [SECURITY.md](SECURITY.md)), Pydantic input validation, and the API token held as a `SecretStr` to prevent accidental logging
- **No third-party services** - Runs locally via stdio, your API token never leaves your machine
- **Multi-instance** - Works with github.com or GitHub Enterprise Server via configurable API URL
- **Cross-platform** - Works on Linux, macOS, and Windows
- **Automatically updated** - GitHub Actions monitor for CVEs and update dependencies
- **Containerized** - Available at `quay.io/crunchtools/mcp-github` built on [Hummingbird Python](https://quay.io/repository/hummingbird/python) base image

## Naming Convention

| Component | Name |
|-----------|------|
| GitHub repo | [crunchtools/mcp-github](https://github.com/crunchtools/mcp-github) |
| Container | `quay.io/crunchtools/mcp-github` |
| Python package (PyPI) | `mcp-github-crunchtools` |
| CLI command | `mcp-github-crunchtools` |
| Module import | `mcp_github_crunchtools` |

## Why Hummingbird?

The container image is built on the [Hummingbird Python base image](https://quay.io/repository/hummingbird/python) from [Project Hummingbird](https://github.com/hummingbird-project), which provides:

- **Minimal CVE exposure** - Built with a minimal package set, dramatically reducing the attack surface
- **Regular updates** - Security patches are applied promptly
- **Optimized for Python** - Pre-configured Python environment
- **Production-ready** - Proper signal handling and non-root user defaults

## Features

25 tools. Tools marked *write* change something on GitHub; the others only
read and publish `readOnlyHint`. The last column is the fine-grained token
permission the tool needs (see [Token permissions](#token-permissions)).

### Issues (5 tools)

| Tool | What it does | Permission |
|------|--------------|------------|
| `list_issues_tool` | List issues for a repository (pull requests excluded) | Issues: read |
| `get_issue_tool` | Get a single issue by number | Issues: read |
| `create_issue_tool` | Open an issue (*write*) | Issues: write |
| `create_issue_comment_tool` | Comment on an issue or pull request (*write*) | Issues: write, or Pull requests: write for a PR |
| `update_issue_tool` | Edit, close or reopen an issue (*write*) | Issues: write |

### Pull Requests (9 tools)

| Tool | What it does | Permission |
|------|--------------|------------|
| `list_pull_requests_tool` | List pull requests for a repository | Pull requests: read |
| `get_pull_request_tool` | Get a single pull request by number | Pull requests: read |
| `get_pull_request_diff_tool` | Get the unified diff for a pull request | Pull requests: read |
| `get_pull_request_checks_tool` | CI verdict from check-runs and commit statuses; skipped is not failed | Pull requests: read, Commit statuses: read (and see the note under Token permissions) |
| `list_pull_request_comments_tool` | Conversation comments, diff comments and reviews in one list, each tagged with its kind | Pull requests: read |
| `create_pull_request_tool` | Open a pull request, optionally as a draft (*write*) | Pull requests: write |
| `update_pull_request_tool` | Edit, close or reopen a pull request; does not merge (*write*) | Pull requests: write |
| `reply_to_review_comment_tool` | Reply in the thread of a diff comment (*write*) | Pull requests: write |
| `merge_pull_request_tool` | Merge, squash or rebase a pull request, optionally only at an expected head SHA (*write*) | Contents: write |

### Actions (6 tools)

| Tool | What it does | Permission |
|------|--------------|------------|
| `list_workflow_runs_tool` | List workflow runs, filtered by branch or status | Actions: read |
| `get_workflow_run_tool` | One run's status, conclusion, head SHA and jobs (no logs) | Actions: read |
| `get_failed_job_logs_tool` | The last lines of the log of each failed job in a run, with ANSI escapes and timestamps removed | Actions: read |
| `trigger_workflow_tool` | Start a fresh run via `workflow_dispatch` (*write*) | Actions: write |
| `rerun_workflow_run_tool` | Re-run every job of a run (*write*) | Actions: write |
| `rerun_failed_jobs_tool` | Re-run only the failed jobs of a run (*write*) | Actions: write |

### Releases (1 tool)

| Tool | What it does | Permission |
|------|--------------|------------|
| `create_release_tool` | Create a release, and its tag if the tag does not exist (*write*) | Contents: write |

### Files (2 tools)

| Tool | What it does | Permission |
|------|--------------|------------|
| `get_file_content_tool` | Read decoded file content from a repository | Contents: read |
| `list_repo_tree_tool` | List the git tree (files and directories) | Contents: read |

### Search (2 tools)

| Tool | What it does | Permission |
|------|--------------|------------|
| `search_code_tool` | Search code across GitHub | Contents: read on a private repository to be searched |
| `search_issues_tool` | Search issues and pull requests across GitHub | Issues: read, Pull requests: read on a private repository to be searched |

### Limits on what a tool returns

- `list_pull_request_comments_tool` reads each of its three kinds oldest
  first, up to 300 items per kind. `truncated` and `truncated_kinds` say when
  newer items were left out.
- `get_workflow_run_tool` lists up to 300 jobs; `jobs_truncated` says when the
  run has more.
- `get_failed_job_logs_tool` returns at most 1000 lines per job (200 by
  default), for at most 5 failed jobs, and at most 256 KiB of log text in
  all, split evenly between the jobs. `tail_lines` in the result is the value
  actually used, `failed_jobs_omitted` counts the jobs left out, and
  `truncated` is set on a job whose log was cut short and on the result when
  anything was. Only the first 300 jobs of a run are examined;
  `jobs_truncated` says when the run has more, and the counts then cover only
  those.

## Installation

### With uvx (Recommended)

```bash
uvx mcp-github-crunchtools
```

### With pip

```bash
pip install mcp-github-crunchtools
```

### With Container

```bash
podman run -e GITHUB_TOKEN=your_token \
    quay.io/crunchtools/mcp-github
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_TOKEN` | Yes | — | GitHub Personal Access Token |
| `GITHUB_API_URL` | No | `https://api.github.com` | API base URL (set for GHES) |
| `GITHUB_DEFAULT_ORG` | No | — | Default owner when a tool omits `owner` |
| `SSL_CERT_FILE` | No | — | Custom CA bundle path, for self-hosted GHES with an internal CA |
| `GITHUB_SSL_VERIFY` | No | `true` | Set `false` to disable TLS verification (not recommended) |

### Creating a GitHub Personal Access Token

1. **Navigate to token settings**
   - Go to https://github.com/settings/tokens

2. **Create a token**
   - **Name**: `mcp-github-crunchtools`
   - **Expiration**: Set an appropriate date (90 days recommended)
   - **Scopes**: Grant only what the tools you use need; see
     [Token permissions](#token-permissions).

3. **Copy and Store Token**
   - Copy the token immediately (shown only once)
   - Store securely in a password manager

### Token permissions

For a fine-grained personal access token, the repository permissions are:

| Permission | Read is enough for | Write is needed for |
|------------|--------------------|---------------------|
| Metadata | every tool (GitHub grants it with any other permission) | — |
| Contents | `get_file_content_tool`, `list_repo_tree_tool` | `merge_pull_request_tool`, `create_release_tool` |
| Issues | `list_issues_tool`, `get_issue_tool` | `create_issue_tool`, `update_issue_tool`, `create_issue_comment_tool` |
| Pull requests | `list_pull_requests_tool`, `get_pull_request_tool`, `get_pull_request_diff_tool`, `get_pull_request_checks_tool`, `list_pull_request_comments_tool` | `create_pull_request_tool`, `update_pull_request_tool`, `reply_to_review_comment_tool`, `create_issue_comment_tool` on a PR |
| Actions | `list_workflow_runs_tool`, `get_workflow_run_tool`, `get_failed_job_logs_tool` | `trigger_workflow_tool`, `rerun_workflow_run_tool`, `rerun_failed_jobs_tool` |
| Commit statuses | `get_pull_request_checks_tool` | — |

`get_pull_request_checks_tool` reads check-runs, and GitHub's permission table
for fine-grained tokens lists no permission for that endpoint. It is readable
on public repositories; on a private repository use a classic token or a
GitHub App token. The search tools likewise have no permission of their own:
they return what the token can already read.

Three things worth knowing before granting write:

- **Contents: write is the merge and release permission.** GitHub has no
  narrower one: the same grant lets the token push commits and tags. A
  release published with `create_release_tool` also fires the repository's
  `on: release` workflows.
- **A release whose target commit changes a workflow file** under
  `.github/workflows/`, relative to the default branch, additionally needs
  Workflows: write; without it GitHub answers 404. Expect the same of a merge
  that brings workflow changes in.
- **Branch rules still apply.** `merge_pull_request_tool` cannot merge past
  required checks or reviews; GitHub answers 405 and the tool returns its
  message.

With a classic token, `repo` covers all of the above (`public_repo` for public
repositories only), plus `workflow` for the workflow-file case.

### Add to Claude Code

```bash
claude mcp add mcp-github-crunchtools \
    --env GITHUB_TOKEN=your_token_here \
    -- uvx mcp-github-crunchtools
```

For GitHub Enterprise Server:

```bash
claude mcp add mcp-github-crunchtools \
    --env GITHUB_TOKEN=your_token_here \
    --env GITHUB_API_URL=https://ghe.example.com/api/v3 \
    -- uvx mcp-github-crunchtools
```

For the container version:

```bash
claude mcp add mcp-github-crunchtools \
    --env GITHUB_TOKEN=your_token_here \
    -- podman run -i --rm -e GITHUB_TOKEN quay.io/crunchtools/mcp-github
```

## Usage Examples

### List Issues

```
User: List open issues for crunchtools/mcp-github
Assistant: [calls list_issues_tool with owner="crunchtools", repo="mcp-github"]
```

### Review a Pull Request

```
User: Show me the diff for PR #5 in crunchtools/mcp-github
Assistant: [calls get_pull_request_diff_tool with pull_number=5]
```

### Check CI Status

```
User: Did the checks pass on pull request 5?
Assistant: [calls get_pull_request_checks_tool with pull_number=5]
```

### Find Out Why CI Failed

```
User: Why did run 123456 fail?
Assistant: [calls get_failed_job_logs_tool with run_id=123456]
```

### Answer a Review and Merge

```
User: Reply to the review findings on PR 5, then squash-merge it
Assistant: [calls list_pull_request_comments_tool with pull_number=5]
Assistant: [calls reply_to_review_comment_tool with comment_id=..., body="fixed in abc1234"]
Assistant: [calls get_pull_request_checks_tool with pull_number=5]
Assistant: [calls merge_pull_request_tool with merge_method="squash", sha=<head_sha from the checks>]
```

### Read a File

```
User: Show me src/server.py from crunchtools/mcp-github
Assistant: [calls get_file_content_tool with path="src/server.py"]
```

### Search

```
User: Find code using FastMCP in crunchtools repos
Assistant: [calls search_code_tool with query="FastMCP org:crunchtools"]
```

## Security

This server was designed with security as a primary concern. See [SECURITY.md](SECURITY.md) for details.

### Key Security Features

1. **Token Protection**
   - Stored as SecretStr (never accidentally logged)
   - Environment variable only (never in files or args)
   - Sanitized from all error messages

2. **Input Validation**
   - Pydantic models for write inputs
   - Allowlist character validation for owner/repo names
   - Path traversal prevention for file reads

3. **API Hardening**
   - Bearer-token auth and pinned GitHub API version
   - HTTPS enforcement (except localhost)
   - TLS certificate validation
   - Request timeouts (30s)
   - Response size limits (10MB)
   - Job-log downloads follow GitHub's redirect without the token, over
     HTTPS only, and keep just the tail (20MB download limit)

4. **Automated CVE Scanning**
   - GitHub Actions scan dependencies
   - Container security scanning with Trivy

## Development

### Setup

```bash
git clone https://github.com/crunchtools/mcp-github.git
cd mcp-github
uv sync --all-extras
```

### Run Tests

```bash
uv run pytest
```

### Lint and Type Check

```bash
uv run ruff check src tests
uv run mypy src
```

### Build Container

```bash
podman build -t mcp-github .
```

## License

AGPL-3.0-or-later

## Contributing

Contributions welcome! Please read SECURITY.md before submitting security-related changes.

## Links

- [GitHub REST API Documentation](https://docs.github.com/en/rest)
- [FastMCP Documentation](https://gofastmcp.com/)
- [MCP Specification](https://modelcontextprotocol.io/)
- [crunchtools.com](https://crunchtools.com)

<!-- mcp-name: io.github.crunchtools/github -->
