# MCP GitHub CrunchTools

A secure MCP (Model Context Protocol) server for GitHub issues, pull requests, repository files, and search. Works with github.com and GitHub Enterprise Server.

## Overview

This MCP server is designed to be:

- **Secure by default** - Comprehensive input validation and token protection
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

### Issues (3 tools)
- `list_issues_tool` - List issues for a repository (pull requests excluded)
- `get_issue_tool` - Get a single issue by number
- `create_issue_comment_tool` - Comment on an issue or pull request (write)

### Pull Requests (4 tools)
- `list_pull_requests_tool` - List pull requests for a repository
- `get_pull_request_tool` - Get a single pull request by number
- `get_pull_request_diff_tool` - Get the unified diff for a pull request
- `get_pull_request_checks_tool` - Combined CI status (check-runs + commit status)

### Files (2 tools)
- `get_file_content_tool` - Read decoded file content from a repository
- `list_repo_tree_tool` - List the git tree (files and directories)

### Search (2 tools)
- `search_code_tool` - Search code across GitHub
- `search_issues_tool` - Search issues and pull requests across GitHub

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

### Creating a GitHub Personal Access Token

1. **Navigate to token settings**
   - Go to https://github.com/settings/tokens

2. **Create a token**
   - **Name**: `mcp-github-crunchtools`
   - **Expiration**: Set an appropriate date (90 days recommended)
   - **Scopes**: Grant read access to contents, issues, and pull requests.
     Add write to issues/PRs only if you need `create_issue_comment_tool`.

3. **Copy and Store Token**
   - Copy the token immediately (shown only once)
   - Store securely in a password manager

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
