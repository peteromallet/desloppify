"""Tests for desloppify.scorecard — helper functions (no PIL/image generation)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from desloppify.output.scorecard import (
    _SCALE,
    _s,
    _score_color,
    get_badge_config,
)


# ===========================================================================
# _score_color
# ===========================================================================

class TestScoreColor:
    def test_high_score_returns_deep_sage(self):
        color = _score_color(95)
        assert color == (68, 120, 68)

    def test_score_exactly_90_returns_deep_sage(self):
        color = _score_color(90)
        assert color == (68, 120, 68)

    def test_mid_score_returns_olive_green(self):
        color = _score_color(80)
        assert color == (120, 140, 72)

    def test_score_exactly_70_returns_olive_green(self):
        color = _score_color(70)
        assert color == (120, 140, 72)

    def test_low_score_returns_yellow_green(self):
        color = _score_color(50)
        assert color == (145, 155, 80)

    def test_zero_score_returns_yellow_green(self):
        color = _score_color(0)
        assert color == (145, 155, 80)

    def test_score_100_returns_deep_sage(self):
        color = _score_color(100)
        assert color == (68, 120, 68)

    def test_muted_differs_from_base(self):
        base = _score_color(95, muted=False)
        muted = _score_color(95, muted=True)
        assert base != muted

    def test_muted_returns_tuple_of_ints(self):
        color = _score_color(80, muted=True)
        assert isinstance(color, tuple)
        assert len(color) == 3
        assert all(isinstance(c, int) for c in color)

    def test_muted_is_pastel_variant(self):
        """Muted color should be a lighter/warmer variant of the base."""
        base = _score_color(50, muted=False)
        muted = _score_color(50, muted=True)
        # Muted should be distinctly different (pastel orange family)
        assert base != muted
        # Muted should be lighter overall (higher average channel value)
        assert sum(muted) > sum(base)

    def test_boundary_at_69_is_yellow_green(self):
        color = _score_color(69.9)
        assert color == (145, 155, 80)

    def test_boundary_at_89_is_olive_green(self):
        color = _score_color(89.9)
        assert color == (120, 140, 72)


# ===========================================================================
# _s (scaling helper)
# ===========================================================================

class TestScaleHelper:
    def test_integer_scaling(self):
        assert _s(10) == 10 * _SCALE

    def test_zero(self):
        assert _s(0) == 0

    def test_float_truncated_to_int(self):
        result = _s(5)
        assert isinstance(result, int)

    def test_scale_factor_is_2(self):
        """Verify the module-level _SCALE constant is 2 for retina."""
        assert _SCALE == 2


# ===========================================================================
# get_badge_config
# ===========================================================================

class TestGetBadgeConfig:
    def test_default_returns_scorecard_png(self):
        args = SimpleNamespace()
        path, disabled = get_badge_config(args)
        assert disabled is False
        assert path is not None
        assert path.name == "scorecard.png"

    def test_no_badge_flag_disables(self):
        args = SimpleNamespace(no_badge=True)
        path, disabled = get_badge_config(args)
        assert disabled is True
        assert path is None

    def test_custom_badge_path(self):
        args = SimpleNamespace(no_badge=False, badge_path="/tmp/custom_badge.png")
        path, disabled = get_badge_config(args)
        assert disabled is False
        assert path == Path("/tmp/custom_badge.png")

    def test_relative_badge_path_resolved_from_project_root(self):
        args = SimpleNamespace(no_badge=False, badge_path="badges/score.png")
        path, disabled = get_badge_config(args)
        assert disabled is False
        assert path.is_absolute()
        assert path.name == "score.png"

    def test_env_var_disables(self, monkeypatch):
        monkeypatch.setenv("DESLOPPIFY_NO_BADGE", "true")
        args = SimpleNamespace()
        path, disabled = get_badge_config(args)
        assert disabled is True
        assert path is None

    def test_env_var_disable_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("DESLOPPIFY_NO_BADGE", "TRUE")
        args = SimpleNamespace()
        _, disabled = get_badge_config(args)
        assert disabled is True

    def test_env_var_disable_with_1(self, monkeypatch):
        monkeypatch.setenv("DESLOPPIFY_NO_BADGE", "1")
        args = SimpleNamespace()
        _, disabled = get_badge_config(args)
        assert disabled is True

    def test_env_var_disable_with_yes(self, monkeypatch):
        monkeypatch.setenv("DESLOPPIFY_NO_BADGE", "yes")
        args = SimpleNamespace()
        _, disabled = get_badge_config(args)
        assert disabled is True

    def test_env_var_badge_path(self, monkeypatch):
        monkeypatch.setenv("DESLOPPIFY_BADGE_PATH", "/custom/env/badge.png")
        monkeypatch.delenv("DESLOPPIFY_NO_BADGE", raising=False)
        args = SimpleNamespace()
        path, disabled = get_badge_config(args)
        assert disabled is False
        assert path == Path("/custom/env/badge.png")

    def test_cli_badge_path_overrides_env(self, monkeypatch):
        monkeypatch.setenv("DESLOPPIFY_BADGE_PATH", "/env/path.png")
        monkeypatch.delenv("DESLOPPIFY_NO_BADGE", raising=False)
        args = SimpleNamespace(no_badge=False, badge_path="/cli/path.png")
        path, disabled = get_badge_config(args)
        assert path == Path("/cli/path.png")

    def test_no_badge_flag_takes_precedence_over_env_path(self, monkeypatch):
        monkeypatch.setenv("DESLOPPIFY_BADGE_PATH", "/some/path.png")
        monkeypatch.delenv("DESLOPPIFY_NO_BADGE", raising=False)
        args = SimpleNamespace(no_badge=True)
        path, disabled = get_badge_config(args)
        assert disabled is True
        assert path is None

    def test_unset_env_var_does_not_disable(self, monkeypatch):
        monkeypatch.delenv("DESLOPPIFY_NO_BADGE", raising=False)
        monkeypatch.delenv("DESLOPPIFY_BADGE_PATH", raising=False)
        args = SimpleNamespace()
        path, disabled = get_badge_config(args)
        assert disabled is False
        assert path is not None

    def test_config_generate_scorecard_false_disables(self, monkeypatch):
        monkeypatch.delenv("DESLOPPIFY_NO_BADGE", raising=False)
        args = SimpleNamespace()
        config = {"generate_scorecard": False}
        path, disabled = get_badge_config(args, config)
        assert disabled is True
        assert path is None

    def test_config_badge_path_used(self, monkeypatch):
        monkeypatch.delenv("DESLOPPIFY_NO_BADGE", raising=False)
        monkeypatch.delenv("DESLOPPIFY_BADGE_PATH", raising=False)
        args = SimpleNamespace()
        config = {"badge_path": "badges/custom.png"}
        path, disabled = get_badge_config(args, config)
        assert disabled is False
        assert path.name == "custom.png"

    def test_cli_badge_path_overrides_config(self, monkeypatch):
        monkeypatch.delenv("DESLOPPIFY_NO_BADGE", raising=False)
        args = SimpleNamespace(no_badge=False, badge_path="/cli/path.png")
        config = {"badge_path": "config/path.png"}
        path, disabled = get_badge_config(args, config)
        assert path == Path("/cli/path.png")


# ===========================================================================
# _get_project_name (tested via mocking subprocess)
# ===========================================================================

class TestGetProjectName:
    def test_gh_cli_success(self, monkeypatch):
        from desloppify.output import scorecard
        monkeypatch.setattr(
            "subprocess.check_output",
            lambda cmd, **kw: "owner/repo\n" if "gh" in cmd else (_ for _ in ()).throw(FileNotFoundError),
        )
        result = scorecard._get_project_name()
        assert result == "owner/repo"

    def test_falls_back_to_git_remote_ssh(self, monkeypatch):
        from desloppify.output import scorecard

        def mock_check_output(cmd, **kw):
            if "gh" in cmd:
                raise FileNotFoundError
            return "git@github.com:myuser/myrepo.git\n"

        monkeypatch.setattr("subprocess.check_output", mock_check_output)
        result = scorecard._get_project_name()
        assert result == "myuser/myrepo"

    def test_falls_back_to_git_remote_https(self, monkeypatch):
        from desloppify.output import scorecard

        def mock_check_output(cmd, **kw):
            if "gh" in cmd:
                raise FileNotFoundError
            return "https://github.com/owner/repo.git\n"

        monkeypatch.setattr("subprocess.check_output", mock_check_output)
        result = scorecard._get_project_name()
        assert result == "owner/repo"

    def test_falls_back_to_directory_name(self, monkeypatch):
        from desloppify.output import scorecard

        def mock_check_output(cmd, **kw):
            raise FileNotFoundError

        monkeypatch.setattr("subprocess.check_output", mock_check_output)
        result = scorecard._get_project_name()
        # Should return the PROJECT_ROOT directory name
        assert isinstance(result, str)
        assert len(result) > 0

    def test_https_with_token_stripped(self, monkeypatch):
        from desloppify.output import scorecard

        def mock_check_output(cmd, **kw):
            if "gh" in cmd:
                raise FileNotFoundError
            return "https://TOKEN@github.com/owner/repo.git\n"

        monkeypatch.setattr("subprocess.check_output", mock_check_output)
        result = scorecard._get_project_name()
        assert result == "owner/repo"
