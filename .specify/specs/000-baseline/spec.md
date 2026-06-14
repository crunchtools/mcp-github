# Baseline Specification: mcp-github-crunchtools

> **Spec ID:** 000-baseline
> **Status:** Implemented
> **Version:** 0.1.0

## Overview

mcp-github-crunchtools is a secure MCP server for the GitHub REST API. The MVP
provides 11 tools across four categories: issues, pull requests, repository
files, and search. It works with github.com and GitHub Enterprise Server via a
configurable API base URL.

---

## Tool Inventory

Tool names registered with FastMCP end in `_tool`; the underlying async
functions (in `tools/*.py`) omit the suffix.

### Issues (3 tools)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_issues_tool` | GET | `/repos/{owner}/{repo}/issues` | List issues (PRs filtered out) |
| `get_issue_tool` | GET | `/repos/{owner}/{repo}/issues/{issue_number}` | Get issue details |
| `create_issue_comment_tool` | POST | `/repos/{owner}/{repo}/issues/{issue_number}/comments` | Comment on issue/PR (write) |

### Pull Requests (4 tools)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `list_pull_requests_tool` | GET | `/repos/{owner}/{repo}/pulls` | List pull requests |
| `get_pull_request_tool` | GET | `/repos/{owner}/{repo}/pulls/{pull_number}` | Get PR details |
| `get_pull_request_diff_tool` | GET | `/repos/{owner}/{repo}/pulls/{pull_number}` (Accept: diff) | Get unified diff |
| `get_pull_request_checks_tool` | GET | `.../commits/{sha}/check-runs` + `.../status` | Combined CI summary |

### Files (2 tools)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `get_file_content_tool` | GET | `/repos/{owner}/{repo}/contents/{path}` | Decoded file content |
| `list_repo_tree_tool` | GET | `/repos/{owner}/{repo}/git/trees/{tree_sha}` | List git tree |

### Search (2 tools)

| Tool | Method | Endpoint | Description |
|------|--------|----------|-------------|
| `search_code_tool` | GET | `/search/code?q=` | Search code |
| `search_issues_tool` | GET | `/search/issues?q=` | Search issues and PRs |

---

## Security Architecture

### Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `GITHUB_TOKEN` | Yes | — | Personal Access Token |
| `GITHUB_API_URL` | No | `https://api.github.com` | API base URL (set for GHES) |
| `GITHUB_DEFAULT_ORG` | No | — | Default owner when omitted |
| `SSL_CERT_FILE` | No | — | Custom CA bundle path |
| `GITHUB_SSL_VERIFY` | No | `true` | Disable SSL verification |

### Authentication & Headers

- `Authorization: Bearer <token>`
- `Accept: application/vnd.github+json` (overridable per request, e.g. diffs)
- `X-GitHub-Api-Version: 2022-11-28`

### Pagination

GitHub uses the RFC 5988 `Link` header (rel="next"/"prev"/"first"/"last")
rather than `x-total-*` headers. List responses return
`{"items": [...], "pagination": {...}}` where pagination carries the rel URLs
and their page numbers.

### Error Hierarchy

```
UserError (base)
├── ConfigurationError
├── GitHubApiError (sanitizes token from messages)
├── NotFoundError (truncates long identifiers)
├── PermissionDeniedError (401, 403 non-rate-limit)
├── RateLimitError (429, or 403 + x-ratelimit-remaining: 0)
└── ValidationError
```

### Input Validation Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `MAX_NAME_LENGTH` | 100 | Owner/repo names |
| `MAX_PATH_LENGTH` | 1000 | File paths |
| `MAX_COMMENT_LENGTH` | 65536 | Comment bodies |
| `MAX_QUERY_LENGTH` | 1000 | Search queries |
| `MAX_PER_PAGE` | 100 | Page size clamp |
| `MAX_RESPONSE_SIZE` | 10MB | Response body limit |
| `REQUEST_TIMEOUT` | 30s | HTTP request timeout |

---

## Module Structure

```
src/mcp_github_crunchtools/
├── __init__.py          # Entry point, argparse (stdio/sse/streamable-http)
├── __main__.py          # python -m entry point
├── client.py            # Hardened httpx async client (Bearer, Link pagination)
├── config.py            # SecretStr config, SSL, URL validation, default org
├── errors.py            # Safe error hierarchy
├── models.py            # Validation helpers + comment input model
├── server.py            # FastMCP tool registrations (11 tools)
└── tools/
    ├── __init__.py      # Re-exports all 11 functions
    ├── issues.py        # list, get, comment
    ├── pull_requests.py # list, get, diff, checks
    ├── files.py         # content, tree
    └── search.py        # code, issues
```

---

## Test Coverage

| Category | What |
|----------|------|
| Registration | Imports, callable, tool count (11) |
| Error safety | Token sanitization, ID truncation |
| Config safety | Token, API URL, SSL, default org |
| Client | Bearer/version headers, Link pagination |
| Mocked API | All tool groups with httpx mocks |
| Input validation | Name/int/per-page helpers, comment model |
| Error handling | 401, 403 (rate-limit and permission), 404, 429 |

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2026-06-14 | Initial MVP: 11 tools (issues, PRs, files, search), ported from mcp-gitlab-crunchtools |
