"""Release tools.

Tools for publishing GitHub releases.
"""

from typing import Any

from ..client import get_client
from ..models import (
    CreateReleaseInput,
    resolve_owner,
    validate_name,
    validate_ref,
)


async def create_release(
    owner: str | None,
    repo: str,
    tag_name: str,
    target_commitish: str | None = None,
    name: str | None = None,
    body: str = "",
    draft: bool = False,
    prerelease: bool = False,
    generate_release_notes: bool = False,
) -> dict[str, Any]:
    """Create a GitHub release, creating its tag if the tag does not exist.

    Publishing a release (draft=False) fires the repository's
    ``on: release`` workflows, which is how packages and images get built
    and pushed.

    GitHub answers 404 when the target commit changes a workflow file
    relative to the default branch and the token may not modify workflows.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        tag_name: Tag of the release (e.g. "v1.2.0")
        target_commitish: Branch or commit SHA to tag when the tag does not
            exist yet (default: the repository's default branch)
        name: Release title (default: the tag name)
        body: Release notes (Markdown)
        draft: Create an unpublished draft
        prerelease: Mark the release as a prerelease
        generate_release_notes: Let GitHub generate the notes; ``body`` is
            put in front of them

    Returns:
        Created release details (id, tag_name, name, html_url, draft,
        prerelease)
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")
    validated = CreateReleaseInput(name=name, body=body)

    json_data: dict[str, Any] = {
        "tag_name": validate_ref(tag_name, "tag_name"),
        "body": validated.body,
        "draft": draft,
        "prerelease": prerelease,
        "generate_release_notes": generate_release_notes,
    }
    if target_commitish and target_commitish.strip():
        json_data["target_commitish"] = validate_ref(target_commitish, "target_commitish")
    if validated.name:
        json_data["name"] = validated.name

    client = get_client()
    result = await client.post(
        f"/repos/{owner}/{repo}/releases",
        json_data=json_data,
    )
    return {
        "id": result.get("id"),
        "tag_name": result.get("tag_name"),
        "name": result.get("name"),
        "html_url": result.get("html_url"),
        "draft": result.get("draft"),
        "prerelease": result.get("prerelease"),
    }
