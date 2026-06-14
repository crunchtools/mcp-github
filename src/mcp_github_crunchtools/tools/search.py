"""Search tools.

Tools for searching code and issues/PRs across GitHub.
"""

from typing import Any

from ..client import get_client
from ..errors import ValidationError
from ..models import (
    MAX_QUERY_LENGTH,
    clamp_per_page,
    validate_positive_int,
)


def _validate_query(query: str) -> str:
    if not query or not query.strip():
        raise ValidationError("query must not be empty")
    query = query.strip()
    if len(query) > MAX_QUERY_LENGTH:
        raise ValidationError("query is too long")
    return query


async def search_code(
    query: str,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """Search for code across GitHub.

    Uses GitHub's code search syntax (e.g., "addClass repo:jquery/jquery").

    Args:
        query: Search query string
        per_page: Results per page (max 100)
        page: Page number

    Returns:
        Search results with total count and matched code items
    """
    query = _validate_query(query)

    client = get_client()
    params: dict[str, Any] = {
        "q": query,
        "per_page": clamp_per_page(per_page),
        "page": validate_positive_int(page, "page"),
    }

    return await client.get("/search/code", params=params)


async def search_issues(
    query: str,
    per_page: int = 30,
    page: int = 1,
) -> dict[str, Any]:
    """Search for issues and pull requests across GitHub.

    Uses GitHub's issue search syntax (e.g., "is:open is:pr author:octocat").

    Args:
        query: Search query string
        per_page: Results per page (max 100)
        page: Page number

    Returns:
        Search results with total count and matched issues/PRs
    """
    query = _validate_query(query)

    client = get_client()
    params: dict[str, Any] = {
        "q": query,
        "per_page": clamp_per_page(per_page),
        "page": validate_positive_int(page, "page"),
    }

    return await client.get("/search/issues", params=params)
