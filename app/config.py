"""Application configuration for PayInChaos."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration for the PayInChaos simulation."""

    # Telemetry.
    telemetry_window_seconds: int = 30

    # Anomaly detection.
    anomaly_success_rate_threshold: float = 85.0
    anomaly_p99_latency_threshold_ms: float = 2500.0

    # Routing guardrails.
    max_reroute_percentage: int = 40
    minimum_cooldown_seconds: int = 60

    # AI defaults.
    default_ai_cooling_period_seconds: int = 120

    # Payment gateway.
    payment_timeout_threshold_ms: float = 2500.0


DEFAULT_SETTINGS = Settings()