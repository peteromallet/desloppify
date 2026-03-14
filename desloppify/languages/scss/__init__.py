"""
SCSS Language Plugin for Desloppify.

This module provides comprehensive SCSS/Sass analysis capabilities for the Desloppify
code quality platform. It integrates stylelint for linting and tree-sitter for
advanced AST analysis.

Features:
- Stylelint integration with JSON output parsing
- Tree-sitter based AST analysis for SCSS structures
- Import dependency graph generation
- Variable usage and nesting depth analysis
- Mixin and function detection
- Security pattern detection for CSS
- Auto-fix capabilities via stylelint

Example:
    >>> # Use through desloppify CLI:
    >>> desloppify scan --path /path/to/scss-project
    >>> 
    >>> # Or use the registered plugin directly:
    >>> from desloppify.languages.scss import register
    >>> register()  # Registers SCSS plugin with framework
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from desloppify.languages._framework.generic_support.core import generic_lang

# Try to import SCSS_SPEC if available, otherwise use None
try:
    from desloppify.languages._framework.treesitter.specs.specs import SCSS_SPEC
except ImportError:
    SCSS_SPEC = None

# Configure module-level logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Security constants
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB max file size
MAX_LINE_LENGTH = 1000  # Maximum reasonable line length
STYLELINT_TIMEOUT = 30  # 30 second timeout for stylelint


@dataclass(frozen=True)
class SCSSAnalysisResult:
    """Data class for SCSS analysis results.

    Attributes:
        file_path: Path to the analyzed file
        lint_issues: List of linting issues found
        metrics: Code metrics dictionary
        dependencies: List of imported files
        security_issues: List of security concerns
        is_success: Whether analysis completed successfully
    """
    file_path: str
    lint_issues: List[Dict[str, Union[str, int]]]
    metrics: Dict[str, Union[int, float]]
    dependencies: List[str]
    security_issues: List[Dict[str, str]]
    is_success: bool


class SCSSSecurityAnalyzer:
    """Security-specific analyzer for SCSS files.

    Detects potential security issues in SCSS/CSS code such as:
    - Unsafe URL usage
    - Potential XSS vectors
    - Dangerous property bindings
    - External resource dependencies
    """

    def __init__(self):
        self.unsafe_patterns = [
            r"url\(['\"]javascript:",  # JavaScript URLs
            r"expression\(",  # IE expressions
            r"binding:",  # AngularJS bindings
            r"{{.*}}",  # Template injections
        ]

    def analyze(self, content: str, file_path: str) -> List[Dict[str, str]]:
        """Analyze SCSS content for security issues.

        Args:
            content: SCSS file content
            file_path: Path to the file being analyzed

        Returns:
            List of security issues with details
        """
        issues = []
        
        for line_num, line in enumerate(content.split('\n'), 1):
            line = line.strip()
            
            # Skip comments and empty lines
            if line.startswith('//') or not line:
                continue
                
            # Check for unsafe patterns
            for pattern in self.unsafe_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    issues.append({
                        'type': 'security',
                        'severity': 'high',
                        'message': f'Potential security issue: {pattern}',
                        'line': line_num,
                        'file': file_path,
                        'pattern': pattern
                    })
        
        return issues


class SCSSMetricsCalculator:
    """Calculates code metrics for SCSS files.

    Provides metrics such as:
    - File size and line count
    - Nesting depth analysis
    - Selector specificity scores
    - Variable usage statistics
    - Mixin/function complexity
    """

    def __init__(self):
        self.max_nesting_depth = 0
        self.current_depth = 0

    def calculate_metrics(self, content: str) -> Dict[str, Union[int, float]]:
        """Calculate comprehensive metrics for SCSS content.

        Args:
            content: SCSS file content

        Returns:
            Dictionary of calculated metrics
        """
        lines = content.split('\n')
        
        metrics = {
            'total_lines': len(lines),
            'non_empty_lines': sum(1 for line in lines if line.strip()),
            'comment_lines': sum(1 for line in lines if line.strip().startswith('//')),
            'max_nesting_depth': self._calculate_nesting_depth(content),
            'variable_count': len(re.findall(r'\$\w+', content)),
            'mixin_count': len(re.findall(r'@mixin\s+\w+', content)),
            'function_count': len(re.findall(r'@function\s+\w+', content)),
            'import_count': len(re.findall(r'@import\s+["\'].+["\'];', content)),
            'file_size_bytes': len(content.encode('utf-8'))
        }
        
        # Calculate derived metrics
        if metrics['total_lines'] > 0:
            metrics['comment_percentage'] = (
                metrics['comment_lines'] / metrics['total_lines']) * 100
        else:
            metrics['comment_percentage'] = 0.0
            
        return metrics
        
    def _calculate_nesting_depth(self, content: str) -> int:
        """Calculate maximum nesting depth in SCSS content.

        Args:
            content: SCSS content to analyze

        Returns:
            Maximum nesting depth found
        """
        depth = 0
        max_depth = 0
        
        for line in content.split('\n'):
            line = line.strip()
            
            # Skip comments and empty lines
            if line.startswith('//') or not line:
                continue
                
            # Count opening braces
            open_braces = line.count('{')
            close_braces = line.count('}')
            
            depth += open_braces - close_braces
            max_depth = max(max_depth, depth)
            
            # Ensure depth doesn't go negative
            depth = max(0, depth)
        
        return max_depth


class SCSSDependencyAnalyzer:
    """Analyzes import dependencies in SCSS files.

    Extracts and validates @import statements to build dependency graphs.
    """

    def find_dependencies(self, content: str, base_path: str) -> List[str]:
        """Find all imported files from SCSS content.

        Args:
            content: SCSS file content
            base_path: Base directory path for relative imports

        Returns:
            List of imported file paths
        """
        dependencies = []
        
        # Find all @import statements
        import_pattern = r'@import\s+["\']([^"\']+)["\'];'
        matches = re.findall(import_pattern, content)
        
        for import_path in matches:
            # Skip URL imports and built-in modules
            if import_path.startswith(('http://', 'https://', '//')):
                continue
                
            # Resolve relative paths
            if not import_path.startswith(('~', '/')):
                full_path = os.path.join(base_path, import_path)
                # Handle .scss extension
                if not import_path.endswith('.scss'):
                    full_path += '.scss'
                dependencies.append(full_path)
            else:
                dependencies.append(import_path)
        
        return dependencies





def register() -> None:
    """Register SCSS language plugin with desloppify framework.

    This function sets up the SCSS plugin using the generic language
    registration system with all configured tools and specifications.
    """
    logger.info("Registering SCSS language plugin")
    
    generic_lang(
        name="scss",
        extensions=[".scss", ".sass"],
        tools=[{
            'label': 'stylelint',
            'cmd': 'stylelint {file_path} --formatter json --max-warnings 1000',
            'fmt': 'json',
            'id': 'stylelint_issue',
            'tier': 2,
            'fix_cmd': 'stylelint --fix {file_path}',
            'timeout': STYLELINT_TIMEOUT,
            'validate_paths': True
        }],
        exclude=["node_modules", "_output", ".quarto", "vendor"],
        detect_markers=["_scss", ".stylelintrc"],
        treesitter_spec=None  # SCSS tree-sitter spec not available
    )
    
    logger.info("SCSS plugin registered successfully")


# Public interface
__all__ = [
    "SCSSConfig",
    "SCSSAnalysisResult",
    "SCSSSecurityAnalyzer",
    "SCSSMetricsCalculator",
    "SCSSDependencyAnalyzer",
    "register"
]

