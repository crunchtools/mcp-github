"""Safe error types that can be shown to users.

This module defines exception classes that are safe to expose to MCP clients.
Internal errors should be caught and converted to UserError before propagating.
"""

import os
from contextvars import ContextVar

SAFE_ID_MAX_LENGTH = 40

# The token a caller sent with the current HTTP request, when the server
# accepts one. The client sets it per request; asyncio gives each MCP request
# its own context, so one request never sees another's token here.
request_token: ContextVar[str | None] = ContextVar("request_token", default=None)


def scrub_tokens(message: str) -> str:
    """Replace the environment token and the current request token with ***."""
    for token in (os.environ.get("GITHUB_TOKEN", ""), request_token.get()):
        if token:
            message = message.replace(token, "***")
    return message


class UserError(Exception):
    """Base class for safe errors that can be shown to users.

    All error messages in UserError subclasses must be carefully crafted
    to avoid leaking sensitive information like API tokens or internal paths.
    """


class ConfigurationError(UserError):
    """Error in server configuration."""


class GitHubApiError(UserError):
    """Error from GitHub API.

    The message is sanitized to remove the environment token and the token
    of the current request.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"GitHub API error {code}: {scrub_tokens(message)}")


class NotFoundError(UserError):
    """Resource not found or not accessible."""

    def __init__(self, identifier: str) -> None:
        if len(identifier) > SAFE_ID_MAX_LENGTH:
            safe_id = identifier[:SAFE_ID_MAX_LENGTH] + "..."
        else:
            safe_id = identifier
        super().__init__(f"Not found or not accessible: {safe_id}")


class PermissionDeniedError(UserError):
    """Permission denied for the requested operation."""

    def __init__(self, required_scope: str) -> None:
        super().__init__(f"Permission denied. Required scope: {required_scope}")


class RateLimitError(UserError):
    """Rate limit exceeded."""

    def __init__(self, retry_after: int | None = None) -> None:
        msg = "Rate limit exceeded."
        if retry_after:
            msg += f" Retry after {retry_after} seconds."
        super().__init__(msg)


class MergeRefusedError(UserError):
    """merge_pull_request refused to merge: a required check is not green,
    or the checks could not be established."""


class ValidationError(UserError):
    """Input validation error."""
