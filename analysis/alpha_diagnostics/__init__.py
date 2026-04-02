"""
Cross-sectional factor diagnostics via alphalens-reloaded.

Not a strategy backtest engine; not benchmark or risk-free authority.
Install: ``uv sync --group analysis``.
"""

from analysis.alpha_diagnostics.config import AlphaDiagnosticsConfig

__all__ = ["AlphaDiagnosticsConfig"]
