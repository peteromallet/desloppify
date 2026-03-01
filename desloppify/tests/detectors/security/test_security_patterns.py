"""Direct tests for detector security pattern helpers."""

from __future__ import annotations

from desloppify.engine.detectors.patterns.security import (
    SECRET_NAME_RE,
    has_secret_format_match,
    is_comment_line,
    is_env_lookup,
    is_placeholder,
)


def test_has_secret_format_match_detects_aws_key():
    assert has_secret_format_match('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"')


def test_comment_line_detection_covers_common_styles():
    assert is_comment_line("# comment")
    assert is_comment_line("// comment")
    assert not is_comment_line("token = value")


def test_is_env_lookup_detects_common_env_access():
    assert is_env_lookup("const key = process.env.API_KEY")
    assert is_env_lookup('password = os.getenv("API_KEY")')
    assert not is_env_lookup('password = "hardcoded-value"')


def test_placeholder_detection_filters_obvious_placeholders():
    assert is_placeholder("changeme")
    assert is_placeholder("abc")
    assert not is_placeholder("really-secret-value")


def test_secret_name_regex_matches_assignment():
    match = SECRET_NAME_RE.search('const api_key = "super_secret_123"')
    assert match is not None
    assert match.group(1) == "api_key"
