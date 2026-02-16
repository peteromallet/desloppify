"""Tests for desloppify.scorecard — helper functions (no PIL/image generation)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


from desloppify.output._scorecard_left_panel import draw_left_panel as draw_left_panel_impl
from desloppify.output._scorecard_meta import (
    resolve_package_version as resolve_package_version_impl,
)
from desloppify.output._scorecard_meta import resolve_project_name as resolve_project_name_impl
from desloppify.output._scorecard_right_panel import draw_right_panel as draw_right_panel_impl
from desloppify.output.scorecard import (
    _SCALE,
    _get_package_version,
    _scorecard_ignore_warning,
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
# _scorecard_ignore_warning
# ===========================================================================

class TestIgnoreWarning:
    def test_none_when_no_ignored_findings(self):
        assert _scorecard_ignore_warning({"ignore_integrity": {"ignored": 0, "suppressed_pct": 80.0}}) is None

    def test_warning_when_suppression_medium(self):
        msg = _scorecard_ignore_warning({"ignore_integrity": {"ignored": 10, "suppressed_pct": 35.0}})
        assert msg is not None
        assert "35%" in msg

    def test_warning_when_suppression_high(self):
        msg = _scorecard_ignore_warning({"ignore_integrity": {"ignored": 10, "suppressed_pct": 60.0}})
        assert msg is not None
        assert "high" in msg.lower()


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


# ===========================================================================
# _get_package_version
# ===========================================================================

class TestGetPackageVersion:
    def test_uses_installed_package_metadata(self, monkeypatch):
        from desloppify.output import scorecard

        monkeypatch.setattr(
            scorecard.importlib_metadata,
            "version",
            lambda name: "0.4.0",
        )
        assert _get_package_version() == "0.4.0"

    def test_falls_back_to_pyproject_version(self, monkeypatch, tmp_path):
        from desloppify.output import scorecard

        def _missing(_name):
            raise scorecard.importlib_metadata.PackageNotFoundError

        monkeypatch.setattr(scorecard.importlib_metadata, "version", _missing)
        monkeypatch.setattr(scorecard, "PROJECT_ROOT", tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "desloppify"\nversion = "0.4.0"\n',
            encoding="utf-8",
        )
        assert _get_package_version() == "0.4.0"

    def test_returns_unknown_when_unavailable(self, monkeypatch, tmp_path):
        from desloppify.output import scorecard

        def _missing(_name):
            raise scorecard.importlib_metadata.PackageNotFoundError

        monkeypatch.setattr(scorecard.importlib_metadata, "version", _missing)
        monkeypatch.setattr(scorecard, "PROJECT_ROOT", tmp_path)
        assert _get_package_version() == "unknown"


# ===========================================================================
# scorecard helper submodules (direct coverage)
# ===========================================================================


class _StubDraw:
    def __init__(self):
        self.calls: list[str] = []

    def textbbox(self, _xy, text, font=None):
        width = len(str(text)) * 6
        height = 10 if font is None else 12
        return (0, 0, width, height)

    def textlength(self, text, font=None):
        return float(len(str(text)) * 6)

    def rounded_rectangle(self, *_args, **_kwargs):
        self.calls.append("rounded_rectangle")

    def rectangle(self, *_args, **_kwargs):
        self.calls.append("rectangle")

    def text(self, *_args, **_kwargs):
        self.calls.append("text")

    def polygon(self, *_args, **_kwargs):
        self.calls.append("polygon")


class TestScorecardSubmodules:
    def test_meta_resolve_project_name_falls_back_to_directory(self, monkeypatch, tmp_path):
        monkeypatch.setattr("subprocess.check_output", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError))
        assert resolve_project_name_impl(tmp_path) == tmp_path.name

    def test_meta_resolve_package_version_reads_pyproject(self, tmp_path):
        class MissingVersionError(Exception):
            pass

        def _missing(_name: str) -> str:
            raise MissingVersionError

        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "desloppify"\nversion = "9.9.9"\n',
            encoding="utf-8",
        )
        version = resolve_package_version_impl(
            tmp_path,
            version_getter=_missing,
            package_not_found_error=MissingVersionError,
        )
        assert version == "9.9.9"

    def test_left_panel_draw_smoke(self, monkeypatch):
        from desloppify.output import _scorecard_left_panel as left_panel

        monkeypatch.setattr(left_panel, "_load_font", lambda *a, **k: object())
        draw = _StubDraw()
        draw_left_panel_impl(
            draw,
            main_score=95.0,
            strict_score=92.0,
            project_name="owner/repo",
            package_version="1.2.3",
            ignore_warning=None,
            lp_left=0,
            lp_right=300,
            lp_top=0,
            lp_bot=200,
            draw_rule_with_ornament_fn=lambda *a, **k: None,
        )
        assert "text" in draw.calls
        assert "rounded_rectangle" in draw.calls

    def test_right_panel_draw_smoke(self, monkeypatch):
        from desloppify.output import _scorecard_right_panel as right_panel

        monkeypatch.setattr(right_panel, "_load_font", lambda *a, **k: object())
        draw = _StubDraw()
        draw_right_panel_impl(
            draw,
            active_dims=[
                ("File health", {"score": 95.0, "strict": 90.0}),
                ("Code quality", {"score": 88.0, "strict": 85.0}),
            ],
            row_h=20,
            table_x1=0,
            table_x2=400,
            table_top=0,
            table_bot=200,
        )
        assert "rounded_rectangle" in draw.calls
