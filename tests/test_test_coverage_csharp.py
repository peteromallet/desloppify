"""C# branches in test coverage mapping should be safe and usable."""

from pathlib import Path

from desloppify.detectors.test_coverage_mapping import _analyze_test_quality, _map_test_to_source


def test_map_test_to_source_csharp_name_convention():
    prod = {"src/UserService.cs"}
    test = "src/Tests/UserServiceTests.cs"
    assert _map_test_to_source(test, prod, "csharp") == "src/UserService.cs"


def test_analyze_test_quality_csharp_assertions(tmp_path):
    test_file = tmp_path / "AuthTests.cs"
    test_file.write_text(
        """
using Xunit;
public class AuthTests
{
    [Fact]
    public void Works()
    {
        Assert.True(true);
    }
}
"""
    )
    result = _analyze_test_quality({str(test_file)}, "csharp")
    quality = result[str(test_file)]["quality"]
    assert quality in {"adequate", "thorough", "smoke"}
