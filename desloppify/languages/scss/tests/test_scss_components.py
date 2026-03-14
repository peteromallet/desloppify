"""
Test suite for SCSS analysis components.

This module tests the individual analysis components after removing the SCSSConfig class.
"""

import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from desloppify.languages.scss import (
    SCSSSecurityAnalyzer,
    SCSSMetricsCalculator,
    SCSSDependencyAnalyzer,
    SCSSAnalysisResult
)


class TestSCSSComponents:
    """Test suite for SCSS analysis components."""

    def setup_method(self):
        """Set up test fixtures."""
        self.security = SCSSSecurityAnalyzer()
        self.metrics = SCSSMetricsCalculator()
        self.dependencies = SCSSDependencyAnalyzer()
        self.test_content = """
// Test SCSS file
$primary-color: #4285f4;

.button {
  background-color: $primary-color;
  
  &--large {
    padding: 1rem;
  }
}

@import "variables";
@mixin flex-center {
  display: flex;
  justify-content: center;
}
"""

    def test_initialization(self):
        """Test that components initialize correctly."""
        assert self.security is not None
        assert self.metrics is not None
        assert self.dependencies is not None

    def test_analyze_file_success(self):
        """Test successful file analysis."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.scss', delete=False) as f:
            f.write(self.test_content)
            temp_path = f.name

        try:
            # Test metrics calculation
            metrics = self.metrics.calculate_metrics(self.test_content)
            assert metrics['total_lines'] == 18
            assert metrics['non_empty_lines'] == 13
            assert metrics['comment_lines'] == 1
            assert metrics['variable_count'] == 2
            assert metrics['mixin_count'] == 1
            assert metrics['function_count'] == 0
            assert metrics['import_count'] == 1
            
            # Test dependency finding
            dependencies = self.dependencies.find_dependencies(self.test_content, os.path.dirname(temp_path))
            assert len(dependencies) == 1
            assert dependencies[0].endswith('variables.scss')
            
            # Test security analysis
            unsafe_code = 'url("javascript:alert(1)")'
            issues = self.security.analyze(unsafe_code, "test.scss")
            assert len(issues) == 1
            assert issues[0]['type'] == 'security'
             
        finally:
            os.unlink(temp_path)

    def test_calculate_metrics(self):
        """Test metrics calculation."""
        content = """
// Comment line
$var: value;

.selector {
  color: red;
  
  &--modifier {
    color: blue;
  }
}

@mixin test {}
@function test() {}
@import "file";
"""
        
        metrics = self.metrics.calculate_metrics(content)
        assert metrics['total_lines'] == 16
        assert metrics['non_empty_lines'] == 11
        assert metrics['comment_lines'] == 1
        assert metrics['variable_count'] == 1
        assert metrics['mixin_count'] == 1
        assert metrics['function_count'] == 1
        assert metrics['import_count'] == 1

    def test_nesting_depth_calculation(self):
        """Test nesting depth calculation."""
        # Simple nesting
        simple = """
.outer {
  .inner {
    color: red;
  }
}
"""
        assert self.metrics._calculate_nesting_depth(simple) == 2

        # Deep nesting
        deep = """
.a {
  .b {
    .c {
      .d {
        .e {
          color: red;
        }
      }
    }
  }
}
"""
        assert self.metrics._calculate_nesting_depth(deep) == 5

        # No nesting
        flat = """
.a { color: red; }
.b { color: blue; }
"""
        assert self.metrics._calculate_nesting_depth(flat) == 0

    def test_security_analysis(self):
        """Test security issue detection."""
        unsafe_code = """
.unsafe {
  background: url("javascript:alert('XSS')");
  content: "{{ user_input }}";
}
"""
        
        issues = self.security.analyze(unsafe_code, "test.scss")
        assert len(issues) == 2
        assert all(issue['type'] == 'security' for issue in issues)

    def test_dependency_analysis(self):
        """Test dependency finding."""
        content = """
@import "variables";
@import "mixins.scss";
@import "~bootstrap/scss/bootstrap";
@import url("https://fonts.googleapis.com/css");
"""
        
        dependencies = self.dependencies.find_dependencies(content, "/project/styles")
        assert len(dependencies) == 3
        assert any("variables.scss" in dep for dep in dependencies)
        assert any("mixins.scss" in dep for dep in dependencies)
        assert any("bootstrap" in dep for dep in dependencies)
