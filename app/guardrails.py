"""Deterministic safety guardrails for PayInChaos.

The AI agent recommends actions.

This module decides whether those recommendations are safe to execute.

ARCHITECTURAL RULE:

    AI recommendation != authorization

Only this layer can approve a routing change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from app.config import DEFAULT_SETTINGS, Settings
from app.agent import RerouteAction
from app.switch import BankName


logger = logging.getLogger(__name__)


GuardrailStatus = Literal[
    "APPROVED",
    "CLAMPED",
    "BLOCKED",
]


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    """Result of deterministic guardrail evaluation."""

    status: GuardrailStatus

    approved: bool

    isolated_bank: BankName | None
    target_bank: BankName | None

    scope: str | None

    requested_percentage: int | None
    approved_percentage: int | None

    cooling_period_seconds: int | None

    reasons: tuple[str, ...]

    policy_intervention: bool


class GuardrailEngine:
    """Validate and authorize AI routing recommendations.

    Guardrails are intentionally deterministic and do not use an LLM.
    """

    def __init__(
        self,
        *,
        settings: Settings = DEFAULT_SETTINGS,
    ) -> None:
        self._settings = settings

        # Last approved route-change timestamp per isolated bank.
        self._last_route_change: dict[BankName, float] = {}

    def evaluate(
        self,
        action: RerouteAction,
        *,
        now: float,
        healthy_banks: set[BankName],
    ) -> GuardrailDecision:
        """Evaluate an AI recommendation.

        Args:
            action: AI-generated routing recommendation.
            now: Current monotonic/simulated timestamp.
            healthy_banks: Banks currently considered healthy.

        Returns:
            Deterministic authorization decision.
        """

        reasons: list[str] = []

        isolated_bank = self._parse_bank(
            action.isolated_bank
        )

        target_bank = self._parse_bank(
            action.target_bank
        )

        if isolated_bank is None:
            return self._blocked(
                requested_percentage=action.traffic_percentage,
                scope=action.scope,
                reasons=("Unknown isolated bank.",),
            )

        if target_bank is None:
            return self._blocked(
                isolated_bank=isolated_bank,
                requested_percentage=action.traffic_percentage,
                scope=action.scope,
                reasons=("Unknown target bank.",),
            )

        # Never route traffic to the bank currently being isolated.
        if target_bank is isolated_bank:
            return self._blocked(
                isolated_bank=isolated_bank,
                target_bank=target_bank,
                requested_percentage=action.traffic_percentage,
                scope=action.scope,
                reasons=(
                    "Target bank cannot be the isolated bank.",
                ),
            )

        # Target must be healthy at execution time.
        if target_bank not in healthy_banks:
            return self._blocked(
                isolated_bank=isolated_bank,
                target_bank=target_bank,
                requested_percentage=action.traffic_percentage,
                scope=action.scope,
                reasons=(
                    f"Target bank {target_bank.value} "
                    "is not currently healthy.",
                ),
            )

        # Validate scope.
        valid_scopes = {
            "ALL",
            "UPI",
            "CARD_RUPAY",
            "CARD_VISA",
        }

        if action.scope not in valid_scopes:
            return self._blocked(
                isolated_bank=isolated_bank,
                target_bank=target_bank,
                requested_percentage=action.traffic_percentage,
                scope=action.scope,
                reasons=(
                    f"Invalid routing scope: {action.scope}.",
                ),
            )

        # Enforce minimum cooldown.
        previous_change = self._last_route_change.get(
            isolated_bank
        )

        if previous_change is not None:
            elapsed = now - previous_change

            if elapsed < self._settings.minimum_cooldown_seconds:
                remaining = (
                    self._settings.minimum_cooldown_seconds
                    - elapsed
                )

                return self._blocked(
                    isolated_bank=isolated_bank,
                    target_bank=target_bank,
                    requested_percentage=action.traffic_percentage,
                    scope=action.scope,
                    cooling_period_seconds=(
                        action.cooling_period_seconds
                    ),
                    reasons=(
                        f"Cooldown active for {isolated_bank.value}; "
                        f"{remaining:.1f}s remaining.",
                    ),
                )

        requested_percentage = action.traffic_percentage

        # Hard policy cap.
        approved_percentage = min(
            requested_percentage,
            self._settings.max_reroute_percentage,
        )

        policy_intervention = (
            approved_percentage != requested_percentage
        )

        if policy_intervention:
            reasons.append(
                (
                    f"AI requested {requested_percentage}% traffic shift; "
                    f"policy capped it at "
                    f"{self._settings.max_reroute_percentage}%."
                )
            )

            logger.warning(
                "Guardrail intervention: %s -> %s, requested=%s%%, "
                "approved=%s%%",
                isolated_bank.value,
                target_bank.value,
                requested_percentage,
                approved_percentage,
            )

        else:
            reasons.append(
                "AI recommendation is within traffic policy."
            )

        # Cooling period itself cannot be below the system minimum.
        approved_cooling = max(
            action.cooling_period_seconds,
            self._settings.minimum_cooldown_seconds,
        )

        if action.cooling_period_seconds < (
            self._settings.minimum_cooldown_seconds
        ):
            policy_intervention = True

            reasons.append(
                (
                    f"AI requested {action.cooling_period_seconds}s "
                    f"cooling period; policy raised it to "
                    f"{self._settings.minimum_cooldown_seconds}s."
                )
            )

        self._last_route_change[isolated_bank] = now

        status: GuardrailStatus = (
            "CLAMPED"
            if policy_intervention
            else "APPROVED"
        )

        reasons.append(
            (
                f"Traffic shift authorized: "
                f"{approved_percentage}% "
                f"{action.scope} traffic from "
                f"{isolated_bank.value} to "
                f"{target_bank.value}."
            )
        )

        return GuardrailDecision(
            status=status,
            approved=True,
            isolated_bank=isolated_bank,
            target_bank=target_bank,
            scope=action.scope,
            requested_percentage=requested_percentage,
            approved_percentage=approved_percentage,
            cooling_period_seconds=approved_cooling,
            reasons=tuple(reasons),
            policy_intervention=policy_intervention,
        )

    def clear_cooldown(
        self,
        bank: BankName | None = None,
    ) -> None:
        """Clear cooldown state.

        This is mainly useful for deterministic benchmark resets.
        """

        if bank is None:
            self._last_route_change.clear()
        else:
            self._last_route_change.pop(
                bank,
                None,
            )

    def cooldown_remaining(
        self,
        *,
        bank: BankName,
        now: float,
    ) -> float:
        """Return remaining cooldown seconds."""

        previous_change = self._last_route_change.get(bank)

        if previous_change is None:
            return 0.0

        elapsed = now - previous_change

        return max(
            0.0,
            self._settings.minimum_cooldown_seconds
            - elapsed,
        )

    @staticmethod
    def _parse_bank(
        value: str,
    ) -> BankName | None:
        """Convert an AI bank name into a known enum."""

        try:
            return BankName(value.upper())

        except ValueError:
            return None

    @staticmethod
    def _blocked(
        *,
        isolated_bank: BankName | None = None,
        target_bank: BankName | None = None,
        requested_percentage: int | None = None,
        scope: str | None = None,
        cooling_period_seconds: int | None = None,
        reasons: tuple[str, ...],
    ) -> GuardrailDecision:
        """Build a blocked decision."""

        return GuardrailDecision(
            status="BLOCKED",
            approved=False,
            isolated_bank=isolated_bank,
            target_bank=target_bank,
            scope=scope,
            requested_percentage=requested_percentage,
            approved_percentage=None,
            cooling_period_seconds=cooling_period_seconds,
            reasons=reasons,
            policy_intervention=False,
        )