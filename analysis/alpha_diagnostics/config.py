from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlphaDiagnosticsConfig:
    """Configuration for a single alphalens-reloaded diagnostics run."""

    forward_return_horizons: tuple[int, ...] = (1, 5, 10)
    quantiles: int = 5
    long_short: bool = False
    max_loss: float = 0.35
    """Passed to ``get_clean_factor_and_forward_returns``; lower = stricter alignment."""
    disabled: bool = False
    return_basis: str = "close_to_close_unadjusted"
    """Label only; caller must supply prices consistent with this basis."""
