"""Direct coverage tests for app.commands.runner helper modules."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import desloppify.app.commands.runner.codex_batch as codex_batch_mod
import desloppify.app.commands.runner.run_logs as run_logs_mod


def test_wrap_cmd_c_collapses_arguments_into_single_string() -> None:
    """_wrap_cmd_c should join everything after /c into one quoted string."""
    wrap = codex_batch_mod._wrap_cmd_c

    # cmd /c with a path containing spaces — arguments are collapsed
    cmd = ["cmd", "/c", "C:\\Program Files\\codex.cmd", "exec", "-C", "C:\\my project - Copy"]
    result = wrap(cmd)
    assert result[:2] == ["cmd", "/c"]
    assert len(result) == 3  # exactly three elements
    inner = result[2]
    # The inner string should contain the quoted path
    assert '"C:\\my project - Copy"' in inner
    assert "exec" in inner
    assert '"C:\\Program Files\\codex.cmd"' in inner

    # Non-cmd command — returned unchanged
    assert wrap(["codex", "exec", "-C", "path"]) == ["codex", "exec", "-C", "path"]

    # cmd /c with simple paths (no spaces) — still collapses, no quotes needed
    simple = wrap(["cmd", "/c", "codex", "exec", "-C", "repo"])
    assert len(simple) == 3
    assert simple[2] == "codex exec -C repo"


def test_codex_batch_command_on_windows_collapses_cmd_c(monkeypatch, tmp_path: Path) -> None:
    """On Windows with a .cmd wrapper, paths with spaces must be quoted inside a single /c arg."""
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(
        "shutil.which",
        lambda _name: "C:\\Program Files\\npm\\codex.CMD",
    )
    repo = tmp_path / "core_project - Copy"
    repo.mkdir()
    output = repo / ".desloppify" / "out.json"

    cmd = codex_batch_mod.codex_batch_command(
        prompt="review prompt",
        repo_root=repo,
        output_file=output,
    )
    # Should be exactly ["cmd", "/c", "<single quoted command string>"]
    assert cmd[0] == "cmd"
    assert cmd[1] == "/c"
    assert len(cmd) == 3
    inner = cmd[2]
    # The repo path with spaces must be quoted
    assert f'"{repo}"' in inner or f'"{str(repo)}"' in inner
    assert "exec" in inner
    assert "--ephemeral" in inner


def test_resolve_executable_skips_cmd_c_for_exe_on_windows(monkeypatch) -> None:
    """On Windows, .exe binaries should be invoked directly without cmd /c wrapping."""
    resolve = codex_batch_mod._resolve_executable

    # .exe resolved — no cmd /c
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr("shutil.which", lambda _name: "C:\\Users\\me\\codex.exe")
    result = resolve("codex")
    assert result == ["C:\\Users\\me\\codex.exe"]

    # .cmd resolved — gets cmd /c
    monkeypatch.setattr("shutil.which", lambda _name: "C:\\npm\\codex.CMD")
    result = resolve("codex")
    assert result == ["cmd", "/c", "C:\\npm\\codex.CMD"]

    # .bat resolved — gets cmd /c
    monkeypatch.setattr("shutil.which", lambda _name: "C:\\npm\\codex.bat")
    result = resolve("codex")
    assert result == ["cmd", "/c", "C:\\npm\\codex.bat"]

    # not found — fallback through cmd /c with bare name
    monkeypatch.setattr("shutil.which", lambda _name: None)
    result = resolve("codex")
    assert result == ["cmd", "/c", "codex"]

    # non-Windows — direct invocation always
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/local/bin/codex")
    result = resolve("codex")
    assert result == ["/usr/local/bin/codex"]


def test_codex_batch_command_exe_on_windows_no_cmd_c(monkeypatch, tmp_path: Path) -> None:
    """On Windows with a .exe binary, prompts with spaces must not be wrapped in cmd /c."""
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr("shutil.which", lambda _name: "C:\\Users\\me\\codex.exe")

    cmd = codex_batch_mod.codex_batch_command(
        prompt="You are hello",
        repo_root=tmp_path,
        output_file=tmp_path / "out.json",
    )
    # Should NOT go through cmd /c
    assert cmd[0] == "C:\\Users\\me\\codex.exe"
    assert "cmd" not in cmd
    # Prompt should be a standalone argument, not collapsed into a string
    assert "You are hello" in cmd


def test_codex_batch_command_uses_sanitized_reasoning_effort(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DESLOPPIFY_CODEX_REASONING_EFFORT", "HIGH")

    command = codex_batch_mod.codex_batch_command(
        prompt="review prompt",
        repo_root=tmp_path,
        output_file=tmp_path / "out.json",
    )

    # On Windows with .cmd wrappers, prefix may be ["cmd", "/c", "...codex.cmd"]
    assert any(c.endswith("codex") or "codex" in c for c in command[:3])
    assert "exec" in command
    assert "--ephemeral" in command
    assert f'model_reasoning_effort="high"' in command
    assert str(tmp_path) in command

    monkeypatch.setenv("DESLOPPIFY_CODEX_REASONING_EFFORT", "invalid")
    command = codex_batch_mod.codex_batch_command(
        prompt="review prompt",
        repo_root=tmp_path,
        output_file=tmp_path / "out.json",
    )
    assert f'model_reasoning_effort="low"' in command


def test_run_codex_batch_retries_timeout_or_stall_until_success(monkeypatch, tmp_path: Path) -> None:
    attempts: list[int] = []
    sleeps: list[float] = []
    log_file = tmp_path / "batch.log"

    monkeypatch.setattr(
        codex_batch_mod,
        "resolve_retry_config",
        lambda _deps: SimpleNamespace(
            max_attempts=2,
            use_popen=False,
            live_log_interval=0.1,
            stall_seconds=5,
            retry_backoff_seconds=0.25,
        ),
    )

    def fake_run_batch_attempt(**kwargs):
        attempts.append(kwargs["attempt"])
        return (
            f"ATTEMPT {kwargs['attempt']}",
            SimpleNamespace(stdout_text="stdout", stderr_text="stderr", exit_code=1, ok=False),
        )

    monkeypatch.setattr(codex_batch_mod, "run_batch_attempt", fake_run_batch_attempt)
    monkeypatch.setattr(codex_batch_mod, "handle_early_attempt_return", lambda _result: None)
    monkeypatch.setattr(
        codex_batch_mod,
        "handle_timeout_or_stall",
        lambda **kwargs: 7 if kwargs["header"] == "ATTEMPT 1" else 0,
    )
    monkeypatch.setattr(codex_batch_mod, "handle_successful_attempt", lambda **_kwargs: None)
    monkeypatch.setattr(codex_batch_mod, "handle_failed_attempt", lambda **_kwargs: 1)

    code = codex_batch_mod.run_codex_batch(
        prompt="prompt",
        repo_root=tmp_path,
        output_file=tmp_path / "out.json",
        log_file=log_file,
        deps=SimpleNamespace(
            sleep_fn=sleeps.append,
            safe_write_text_fn=lambda path, text: path.write_text(text, encoding="utf-8"),
        ),
        codex_batch_command_fn=lambda **_kwargs: ["codex", "exec"],
    )

    assert code == 0
    assert attempts == [1, 2]
    assert sleeps == [0.25]


def test_run_followup_scan_handles_force_bypass_timeout_and_oserror(
    capsys,
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def timeout_run(cmd, *, cwd, timeout):
        calls.append(cmd)
        raise TimeoutError

    timeout_code = codex_batch_mod.run_followup_scan(
        lang_name="python",
        scan_path="src",
        deps=SimpleNamespace(
            python_executable="python",
            project_root=tmp_path,
            timeout_seconds=10,
            subprocess_run=timeout_run,
            timeout_error=TimeoutError,
            colorize_fn=lambda text, _style: text,
        ),
        force_queue_bypass=True,
    )
    assert timeout_code == 124
    assert "--force-rescan" in calls[0]
    assert "--attest" in calls[0]

    oserror_code = codex_batch_mod.run_followup_scan(
        lang_name="python",
        scan_path="src",
        deps=SimpleNamespace(
            python_executable="python",
            project_root=tmp_path,
            timeout_seconds=10,
            subprocess_run=lambda *_a, **_k: (_ for _ in ()).throw(OSError("boom")),
            timeout_error=TimeoutError,
            colorize_fn=lambda text, _style: text,
        ),
    )
    assert oserror_code == 1
    out = capsys.readouterr()
    assert "Follow-up scan queue bypass enabled" in out.out
    assert "Follow-up scan timed out after 10s." in out.err
    assert "Follow-up scan failed: boom" in out.err


def test_run_followup_scan_default_does_not_force_queue_bypass(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    code = codex_batch_mod.run_followup_scan(
        lang_name="python",
        scan_path="src",
        deps=SimpleNamespace(
            python_executable="python",
            project_root=tmp_path,
            timeout_seconds=10,
            subprocess_run=lambda cmd, *, cwd, timeout: (
                calls.append(cmd),
                SimpleNamespace(returncode=0),
            )[1],
            timeout_error=TimeoutError,
            colorize_fn=lambda text, _style: text,
        ),
    )

    assert code == 0
    assert "--force-rescan" not in calls[0]
    assert "--attest" not in calls[0]


def test_make_run_log_writer_appends_timestamped_lines_and_ignores_oserror(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_log_path = tmp_path / "run.log"
    writer = run_logs_mod.make_run_log_writer(run_log_path)
    writer("started")
    text = run_log_path.read_text(encoding="utf-8")
    assert "started" in text
    assert text.endswith(" started\n")

    writer = run_logs_mod.make_run_log_writer(tmp_path / "missing" / "run.log")

    def fail_open(*_args, **_kwargs):
        raise OSError("nope")

    monkeypatch.setattr(Path, "open", fail_open)
    writer("ignored")
