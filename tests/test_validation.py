"""Tests for input validation."""

import os

import pytest
from pydantic import ValidationError

from mcp_github_crunchtools.models import (
    CreateIssueCommentInput,
    clamp_per_page,
    resolve_owner,
    validate_name,
    validate_positive_int,
)


class TestValidateName:
    """Tests for owner/repo name validation."""

    def test_valid_simple(self) -> None:
        assert validate_name("octocat", "owner") == "octocat"

    def test_valid_with_punctuation(self) -> None:
        assert validate_name("my-repo.test_1", "repo") == "my-repo.test_1"

    def test_strips_whitespace(self) -> None:
        assert validate_name("  octocat  ", "owner") == "octocat"

    def test_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            validate_name("", "owner")

    def test_injection_slash(self) -> None:
        with pytest.raises(ValueError, match="only letters"):
            validate_name("owner/repo", "owner")

    def test_injection_shell(self) -> None:
        with pytest.raises(ValueError, match="only letters"):
            validate_name("repo$(whoami)", "repo")


class TestResolveOwner:
    """Tests for owner resolution with default-org fallback."""

    def test_explicit_owner(self) -> None:
        os.environ["GITHUB_TOKEN"] = "ghp_test"
        try:
            assert resolve_owner("octocat") == "octocat"
        finally:
            del os.environ["GITHUB_TOKEN"]

    def test_default_org_fallback(self) -> None:
        os.environ["GITHUB_TOKEN"] = "ghp_test"
        os.environ["GITHUB_DEFAULT_ORG"] = "crunchtools"
        try:
            assert resolve_owner(None) == "crunchtools"
        finally:
            del os.environ["GITHUB_TOKEN"]
            del os.environ["GITHUB_DEFAULT_ORG"]

    def test_no_owner_no_default(self) -> None:
        os.environ["GITHUB_TOKEN"] = "ghp_test"
        os.environ.pop("GITHUB_DEFAULT_ORG", None)
        try:
            with pytest.raises(ValueError, match="owner is required"):
                resolve_owner(None)
        finally:
            del os.environ["GITHUB_TOKEN"]


class TestValidatePositiveInt:
    """Tests for positive integer validation."""

    def test_valid(self) -> None:
        assert validate_positive_int(42, "issue_number") == 42

    def test_zero(self) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            validate_positive_int(0, "issue_number")

    def test_negative(self) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            validate_positive_int(-1, "page")


class TestClampPerPage:
    """Tests for per_page clamping."""

    def test_within_range(self) -> None:
        assert clamp_per_page(30) == 30

    def test_over_max(self) -> None:
        assert clamp_per_page(500) == 100

    def test_under_min(self) -> None:
        assert clamp_per_page(0) == 1


class TestCreateIssueCommentInput:
    """Tests for the comment input model."""

    def test_valid(self) -> None:
        comment = CreateIssueCommentInput(body="Looks good to me")
        assert comment.body == "Looks good to me"

    def test_empty(self) -> None:
        with pytest.raises(ValidationError):
            CreateIssueCommentInput(body="")

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateIssueCommentInput(body="hi", extra="x")  # type: ignore[call-arg]
