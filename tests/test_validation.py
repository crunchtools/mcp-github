"""Tests for input validation."""

import os

import pytest
from pydantic import ValidationError

from mcp_github_crunchtools.models import (
    CreateIssueCommentInput,
    CreateReleaseInput,
    clamp_per_page,
    resolve_owner,
    validate_commit_sha,
    validate_head,
    validate_name,
    validate_positive_int,
    validate_ref,
    validate_workflow_inputs,
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


class TestValidateRef:
    """Tests for git ref validation."""

    def test_simple_branch(self) -> None:
        assert validate_ref("main") == "main"

    def test_slash_allowed(self) -> None:
        assert validate_ref("release/1.2") == "release/1.2"

    def test_strips_whitespace(self) -> None:
        assert validate_ref("  main  ") == "main"

    def test_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            validate_ref("")

    def test_path_traversal(self) -> None:
        with pytest.raises(ValueError, match="not a valid git ref"):
            validate_ref("../evil")

    def test_double_slash(self) -> None:
        with pytest.raises(ValueError, match="not a valid git ref"):
            validate_ref("feature//branch")

    def test_dot_slash(self) -> None:
        with pytest.raises(ValueError, match="not a valid git ref"):
            validate_ref("./branch")

    def test_leading_dot(self) -> None:
        with pytest.raises(ValueError, match="not a valid git ref"):
            validate_ref(".hidden")

    def test_leading_slash(self) -> None:
        with pytest.raises(ValueError, match="not a valid git ref"):
            validate_ref("/main")

    def test_shell_injection(self) -> None:
        with pytest.raises(ValueError, match="only letters"):
            validate_ref("main;rm -rf")


class TestValidateWorkflowInputs:
    """Tests for workflow_dispatch input validation."""

    def test_valid_primitives(self) -> None:
        inputs = {"reason": "cve", "count": 3, "force": True}
        assert validate_workflow_inputs(inputs) == inputs

    def test_bad_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="only letters"):
            validate_workflow_inputs({"bad key": "x"})

    def test_non_primitive_value_rejected(self) -> None:
        with pytest.raises(ValueError, match="string, number, or boolean"):
            validate_workflow_inputs({"nested": {"a": 1}})

    def test_too_many_inputs(self) -> None:
        with pytest.raises(ValueError, match="may not exceed"):
            validate_workflow_inputs({f"k{i}": "v" for i in range(33)})


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


class TestValidateHead:
    """Tests for the head of a new pull request."""

    def test_branch_in_same_repo(self) -> None:
        assert validate_head("feature/widgets") == "feature/widgets"

    def test_branch_in_fork(self) -> None:
        assert validate_head("  alice:fix/typo  ") == "alice:fix/typo"

    def test_empty(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            validate_head("   ")

    def test_fork_without_branch(self) -> None:
        with pytest.raises(ValueError, match="head must not be empty"):
            validate_head("alice:")

    def test_fork_without_owner(self) -> None:
        with pytest.raises(ValueError, match="head owner must not be empty"):
            validate_head(":fix")

    def test_injection_in_owner(self) -> None:
        with pytest.raises(ValueError, match="only letters"):
            validate_head("alice/../bob:fix")

    def test_second_colon_lands_in_owner(self) -> None:
        with pytest.raises(ValueError, match="only letters"):
            validate_head("alice:bob:fix")

    def test_path_traversal_in_branch(self) -> None:
        with pytest.raises(ValueError, match="not a valid git ref"):
            validate_head("alice:../main")


class TestValidateCommitSha:
    """Tests for the optional expected-head SHA."""

    def test_sha1(self) -> None:
        assert validate_commit_sha("a1" * 20) == "a1" * 20

    def test_sha256(self) -> None:
        assert validate_commit_sha("b2" * 32) == "b2" * 32

    def test_upper_case_and_whitespace_normalized(self) -> None:
        assert validate_commit_sha("  " + "AB" * 20 + " ") == "ab" * 20

    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_blank_means_not_given(self, blank: str | None) -> None:
        assert validate_commit_sha(blank) is None

    @pytest.mark.parametrize("bad", ["abc123", "a" * 41, "g" * 40, "main", "a" * 39 + "/"])
    def test_not_a_full_sha(self, bad: str) -> None:
        with pytest.raises(ValueError, match="full 40 or 64 character commit SHA"):
            validate_commit_sha(bad)


class TestCreateReleaseInput:
    """Tests for the release input model."""

    def test_valid_minimal(self) -> None:
        release = CreateReleaseInput()
        assert release.name is None
        assert release.body == ""

    def test_valid_full(self) -> None:
        release = CreateReleaseInput(name="v1.2.0", body="## Added")
        assert release.name == "v1.2.0"
        assert release.body == "## Added"

    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_blank_name_means_not_given(self, blank: str | None) -> None:
        assert CreateReleaseInput(name=blank).name is None

    def test_name_too_long(self) -> None:
        with pytest.raises(ValidationError):
            CreateReleaseInput(name="n" * 257)

    def test_body_too_long(self) -> None:
        with pytest.raises(ValidationError):
            CreateReleaseInput(body="b" * 65537)

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CreateReleaseInput(name="v1", tag_name="v1")  # type: ignore[call-arg]
