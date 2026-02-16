"""Tests for C#-specific security detection."""

from pathlib import Path

from desloppify.lang.csharp.detectors.security import detect_csharp_security
from desloppify.zones import FileZoneMap


def test_detect_csharp_security_flags_sql_interpolation(tmp_path):
    source = tmp_path / "Repo.cs"
    source.write_text(
        "\n".join(
            [
                "using System.Data.SqlClient;",
                'var cmd = new SqlCommand($"SELECT * FROM Users WHERE Id={userId}", conn);',
            ]
        )
    )

    entries, scanned = detect_csharp_security([str(source)], None)

    assert scanned == 1
    assert any(e["detail"]["kind"] == "sql_injection" for e in entries)


def test_detect_csharp_security_ignores_comment_lines(tmp_path):
    source = tmp_path / "Commented.cs"
    source.write_text(
        "\n".join(
            [
                "// var cmd = new SqlCommand($\"SELECT * FROM Users WHERE Id={userId}\", conn);",
                "// ServicePointManager.ServerCertificateValidationCallback += (_, __, ___, ____) => true;",
            ]
        )
    )

    entries, scanned = detect_csharp_security([str(source)], None)

    assert scanned == 1
    assert entries == []


def test_detect_csharp_security_random_outside_security_context_not_flagged(tmp_path):
    source = tmp_path / "RandomUi.cs"
    source.write_text(
        "\n".join(
            [
                "using System;",
                "var rng = new Random();",
                "var hue = rng.Next(0, 360);",
            ]
        )
    )

    entries, scanned = detect_csharp_security([str(source)], None)

    assert scanned == 1
    assert not any(e["detail"]["kind"] == "insecure_random" for e in entries)


def test_detect_csharp_security_skips_generated_zone(tmp_path):
    generated = tmp_path / "Generated.g.cs"
    generated.write_text("var formatter = new BinaryFormatter();")

    zone_map = FileZoneMap(
        [str(generated)],
        [],
        rel_fn=lambda p: Path(p).name,
        overrides={generated.name: "generated"},
    )

    entries, scanned = detect_csharp_security([str(generated)], zone_map)

    assert scanned == 0
    assert entries == []
