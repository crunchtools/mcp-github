# Security Design Document

This document describes the security architecture of mcp-github-crunchtools.

## 1. Threat Model

### 1.1 Assets to Protect

| Asset | Sensitivity | Impact if Compromised |
|-------|-------------|----------------------|
| GitHub Personal Access Token | Critical | Full account access, code access, CI/CD manipulation |
| Repository Source Code | High | Intellectual property theft, supply chain attacks |
| Pull Requests / Issues | Medium | Information disclosure, workflow manipulation |
| CI Check Results | Medium | Infrastructure details |

### 1.2 Threat Actors

| Actor | Capability | Motivation |
|-------|------------|------------|
| Malicious AI Agent | Can craft tool inputs | Data exfiltration, privilege escalation |
| Local Attacker | Access to filesystem | Token theft, configuration tampering |
| Network Attacker | Man-in-the-middle | Token interception (mitigated by TLS) |

### 1.3 Attack Vectors

| Vector | Description | Mitigation |
|--------|-------------|------------|
| **Token Leakage** | Token exposed in logs, errors, or outputs | Never log tokens, scrub from errors |
| **Input Injection** | Malicious owner/repo or path | Strict input validation |
| **Path Traversal** | Manipulated file paths | Allowlist validation, reject `..` |
| **SSRF** | Redirect API calls to internal services | HTTPS enforcement, URL validation |
| **Denial of Service** | Exhaust GitHub rate limits | Rate-limit awareness |
| **Privilege Escalation** | Access beyond token scope | Server relies on token scope |
| **Supply Chain** | Compromised dependencies | Automated CVE scanning |

## 2. Security Architecture

### 2.1 Defense in Depth Layers

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Input Validation                                    │
│ - Allowlist for owner/repo characters                        │
│ - Positive-integer validation for issue/PR numbers           │
│ - Path traversal rejection for file reads                    │
├─────────────────────────────────────────────────────────────┤
│ Layer 2: Token Handling                                      │
│ - Environment variable only (never file, never arg)          │
│ - Never log, never include in errors                         │
│ - Use Authorization: Bearer header (not in URL)              │
├─────────────────────────────────────────────────────────────┤
│ Layer 3: API Client Hardening                                │
│ - Configurable base URL with HTTPS enforcement (GHES)        │
│ - Pinned X-GitHub-Api-Version                                 │
│ - TLS certificate validation (default in httpx)              │
│ - Request timeout enforcement (30s)                          │
│ - Response size limits (10MB)                                │
├─────────────────────────────────────────────────────────────┤
│ Layer 4: Output Sanitization                                 │
│ - Redact tokens from any error messages                      │
│ - Limit response sizes to prevent memory exhaustion          │
│ - Structured errors without internal details                 │
├─────────────────────────────────────────────────────────────┤
│ Layer 5: Runtime Protection                                  │
│ - No filesystem writes                                       │
│ - No shell execution (subprocess)                            │
│ - No dynamic code evaluation (eval/exec)                     │
├─────────────────────────────────────────────────────────────┤
│ Layer 6: Supply Chain Security                               │
│ - Automated CVE scanning via GitHub Actions                  │
│ - Dependabot alerts enabled                                  │
│ - Container built on Hummingbird for minimal CVEs            │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Token Security

The API token is handled with multiple protections:

```python
from pydantic import SecretStr

class Config:
    def __init__(self):
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ConfigurationError("GITHUB_TOKEN required")

        # Store as SecretStr to prevent accidental logging
        self._token = SecretStr(token)

    @property
    def token(self) -> str:
        """Get token value - use sparingly."""
        return self._token.get_secret_value()

    def __repr__(self) -> str:
        return "Config(token=***)"
```

### 2.3 URL Security

The API base URL is validated to prevent SSRF:

- Must be a valid URL with scheme and netloc
- Must use HTTPS unless connecting to localhost
- Trailing slashes are stripped
- Defaults to `https://api.github.com`; override with `GITHUB_API_URL` for GHES

### 2.4 Input Validation Rules

All inputs are validated:

- **Owner / repo names**: letters, digits, dots, hyphens, underscores only
- **Issue / PR / page numbers**: must be positive integers
- **File paths**: rejected if they contain `..`
- **States**: allowlist of "open", "closed", "all"
- **Comment bodies**: 1-65536 characters, extra fields rejected (extra="forbid")

### 2.5 Error Handling

Errors are sanitized before being returned:

```python
class GitHubApiError(UserError):
    def __init__(self, code: int, message: str):
        # Sanitize message to remove any token references
        token = os.environ.get("GITHUB_TOKEN", "")
        safe_message = message.replace(token, "***") if token else message
        super().__init__(f"GitHub API error {code}: {safe_message}")
```

GitHub signals primary rate limiting with HTTP 403 plus
`x-ratelimit-remaining: 0`; the client maps this (and HTTP 429) to a
`RateLimitError` that surfaces the retry window.

## 3. Minimum Permission Scopes

### 3.1 Read-Only Token (Safest)

Grant read access to repository **contents**, **issues**, and **pull requests**
(fine-grained PAT), or `repo:status` + `public_repo` for classic tokens limited
to public repositories.

**Capabilities:** list/read issues, PRs, diffs, checks, files; search
**Risk:** Information disclosure only

### 3.2 Standard Token

Add **write** access to **issues** and **pull requests** if you need
`create_issue_comment_tool`.

**Capabilities:** the above plus commenting on issues/PRs
**Risk:** Can post comments if the token is compromised

### 3.3 Recommended Scopes

For minimum privilege, grant only:
- Read contents/issues/pull-requests — if you only need to read
- Add write issues/pull-requests — only if you need to comment

## 4. Supply Chain Security

### 4.1 Automated CVE Scanning

This project uses GitHub Actions to automatically scan for CVEs:

1. **Scheduled Scans**: dependency audits on a regular cadence
2. **PR Checks**: every pull request is scanned before merge
3. **Dependabot**: enabled for automatic security updates

### 4.2 Container Security

The container image is built on **[Hummingbird Python](https://quay.io/repository/hummingbird/python)** from [Project Hummingbird](https://github.com/hummingbird-project):

| Advantage | Description |
|-----------|-------------|
| **Minimal CVE Count** | Dramatically reduced attack surface |
| **Rapid Security Updates** | Security patches applied promptly |
| **Python Optimized** | Pre-configured Python environment |
| **Non-Root Default** | Runs as non-root user |
| **Production Ready** | Proper signal handling, minimal footprint |

### 4.3 Events Logged

| Event | Level | Fields |
|-------|-------|--------|
| Server startup | INFO | version, GitHub API URL |
| GitHub API call | DEBUG | method, path (no auth headers) |
| Permission denied | WARN | required_scope |
| Rate limited | WARN | retry_after |
| Error | ERROR | error_type (no internals) |

### 4.4 Never Logged

- API tokens (any form)
- Full request/response bodies
- Issue/PR descriptions (may contain secrets)
- File content

## 5. Security Checklist

Before each release:

- [ ] All inputs validated
- [ ] No token exposure in logs or errors
- [ ] No filesystem writes
- [ ] No shell execution
- [ ] No eval/exec
- [ ] Rate limiting considered
- [ ] Error messages don't leak internals
- [ ] Dependencies scanned for CVEs
- [ ] Container rebuilt with latest Hummingbird base

## 6. Reporting Security Issues

Report security vulnerabilities using [GitHub's private security advisory](https://github.com/crunchtools/mcp-github/security/advisories/new). This creates a private channel visible only to maintainers.

Do NOT open public issues for security vulnerabilities.
