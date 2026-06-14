"""Repository file tools.

Tools for reading file content and listing the git tree of a repository.
"""

import base64
import binascii
from typing import Any
from urllib.parse import quote

from ..client import get_client
from ..errors import ValidationError
from ..models import (
    MAX_PATH_LENGTH,
    resolve_owner,
    validate_name,
)

MAX_DECODE_SIZE = 1024 * 1024


async def get_file_content(
    owner: str | None,
    repo: str,
    path: str,
    ref: str | None = None,
) -> dict[str, Any]:
    """Get the decoded text content of a file in a repository.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        path: Path to the file within the repository
        ref: Branch, tag, or commit SHA (default: the repository's default branch)

    Returns:
        File metadata plus the decoded text under "text", or a notice if the
        content is binary or too large to decode
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")

    if not path or not path.strip():
        raise ValidationError("path must not be empty")
    if len(path) > MAX_PATH_LENGTH:
        raise ValidationError("path is too long")
    if ".." in path:
        raise ValidationError("path must not contain '..'")

    encoded_path = quote(path.strip(), safe="/")

    client = get_client()
    params = {"ref": ref} if ref else None
    result = await client.get(
        f"/repos/{owner}/{repo}/contents/{encoded_path}", params=params
    )

    if isinstance(result.get("content"), list):
        raise ValidationError("path refers to a directory, not a file")

    encoding = result.get("encoding")
    raw_content = result.get("content", "")
    size = result.get("size", 0)

    summary: dict[str, Any] = {
        "name": result.get("name"),
        "path": result.get("path"),
        "sha": result.get("sha"),
        "size": size,
        "encoding": encoding,
        "html_url": result.get("html_url"),
        "download_url": result.get("download_url"),
    }

    if encoding != "base64" or not raw_content:
        summary["text"] = None
        summary["notice"] = "Content not available as base64 (binary or empty)."
        return summary

    if size and size > MAX_DECODE_SIZE:
        summary["text"] = None
        summary["notice"] = "File too large to decode; use download_url."
        return summary

    try:
        decoded = base64.b64decode(raw_content)
        summary["text"] = decoded.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        summary["text"] = None
        summary["notice"] = "Content is binary; use download_url."

    return summary


async def list_repo_tree(
    owner: str | None,
    repo: str,
    tree_sha: str = "HEAD",
    recursive: bool = False,
) -> dict[str, Any]:
    """List the git tree (files and directories) of a repository.

    Args:
        owner: Repository owner (defaults to GITHUB_DEFAULT_ORG if unset)
        repo: Repository name
        tree_sha: Tree SHA, branch name, or "HEAD" (default: HEAD)
        recursive: Recurse into subtrees (default: false)

    Returns:
        Tree listing with entries and a truncation flag
    """
    owner = resolve_owner(owner)
    repo = validate_name(repo, "repo")

    if not tree_sha or not tree_sha.strip():
        raise ValidationError("tree_sha must not be empty")

    encoded_sha = quote(tree_sha.strip(), safe="")

    client = get_client()
    params = {"recursive": "1"} if recursive else None
    return await client.get(
        f"/repos/{owner}/{repo}/git/trees/{encoded_sha}", params=params
    )
