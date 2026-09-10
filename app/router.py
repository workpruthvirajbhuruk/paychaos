"""Deterministic traffic router for PayInChaos.

Architecture:

    AI Agent
        ↓
    Guardrails
        ↓
    Router
        ↓
    Payment Switch

The router is the execution layer.

It receives an APPROVED GuardrailDecision and applies the
authorized traffic shift to real Transaction objects.

Important:
    - The router never calls an LLM.
    - The router never overrides guardrails.
    - Traffic percentage is deterministic.
    - Routing is scoped by payment method.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from app.guardrails import GuardrailDecision
from app.switch import (
    BankName,
    PaymentMethod,
    Transaction,
)


@dataclass(frozen=True, slots=True)
class RoutingRule:
    """An active, guardrail-approved routing rule."""

    isolated_bank: BankName
    target_bank: BankName
    scope: str
    traffic_percentage: int
    created_at: float
    cooling_period_seconds: int


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Result of evaluating one transaction against routing rules."""

    original_bank: BankName
    routed_bank: BankName
    method: PaymentMethod

    rerouted: bool
    traffic_percentage: int

    rule: RoutingRule | None


class TrafficRouter:
    """Apply approved traffic-routing decisions."""

    def __init__(self) -> None:
        self._rules: list[RoutingRule] = []

    @property
    def active_rules(self) -> tuple[RoutingRule, ...]:
        """Return all currently active routing rules."""

        return tuple(self._rules)

    def apply_guardrail_decision(
        self,
        decision: GuardrailDecision,
        *,
        now: float,
    ) -> RoutingRule:
        """Install an approved guardrail decision as a routing rule.

        Raises:
            PermissionError:
                If the guardrail decision was not approved.
            ValueError:
                If the decision is missing required routing data.
        """

        if not decision.approved:
            raise PermissionError(
                "Cannot install a routing rule from a "
                "non-approved guardrail decision."
            )

        if decision.isolated_bank is None:
            raise ValueError(
                "Approved decision has no isolated bank."
            )

        if decision.target_bank is None:
            raise ValueError(
                "Approved decision has no target bank."
            )

        if decision.scope is None:
            raise ValueError(
                "Approved decision has no routing scope."
            )

        if decision.approved_percentage is None:
            raise ValueError(
                "Approved decision has no approved percentage."
            )

        if decision.cooling_period_seconds is None:
            raise ValueError(
                "Approved decision has no cooling period."
            )

        rule = RoutingRule(
            isolated_bank=decision.isolated_bank,
            target_bank=decision.target_bank,
            scope=decision.scope,
            traffic_percentage=decision.approved_percentage,
            created_at=now,
            cooling_period_seconds=decision.cooling_period_seconds,
        )

        # Replace an existing rule for the same bank/scope.
        self._rules = [
            existing
            for existing in self._rules
            if not (
                existing.isolated_bank
                is rule.isolated_bank
                and existing.scope == rule.scope
            )
        ]

        self._rules.append(rule)

        return rule

    def route(
        self,
        transaction: Transaction,
    ) -> tuple[Transaction, RoutingDecision]:
        """Route a transaction using the currently active rules.

        The returned Transaction is a real transaction with its bank
        changed to the target bank when the traffic-shift rule matches.

        Traffic allocation is deterministic:
            hash(transaction_id) % 100 < traffic_percentage

        This avoids random benchmark behavior and makes results
        reproducible.
        """

        matching_rule = self._find_matching_rule(
            transaction
        )

        if matching_rule is None:
            return (
                transaction,
                RoutingDecision(
                    original_bank=transaction.bank,
                    routed_bank=transaction.bank,
                    method=transaction.method,
                    rerouted=False,
                    traffic_percentage=0,
                    rule=None,
                ),
            )

        if not self._belongs_to_rerouted_traffic(
            transaction_id=transaction.transaction_id,
            traffic_percentage=(
                matching_rule.traffic_percentage
            ),
        ):
            return (
                transaction,
                RoutingDecision(
                    original_bank=transaction.bank,
                    routed_bank=transaction.bank,
                    method=transaction.method,
                    rerouted=False,
                    traffic_percentage=(
                        matching_rule.traffic_percentage
                    ),
                    rule=matching_rule,
                ),
            )

        routed_transaction = replace(
            transaction,
            bank=matching_rule.target_bank,
        )

        return (
            routed_transaction,
            RoutingDecision(
                original_bank=transaction.bank,
                routed_bank=matching_rule.target_bank,
                method=transaction.method,
                rerouted=True,
                traffic_percentage=(
                    matching_rule.traffic_percentage
                ),
                rule=matching_rule,
            ),
        )

    def clear_rules(self) -> None:
        """Remove all active routing rules."""

        self._rules.clear()

    def clear_bank(
        self,
        bank: BankName,
    ) -> None:
        """Remove routing rules associated with one isolated bank."""

        self._rules = [
            rule
            for rule in self._rules
            if rule.isolated_bank is not bank
        ]

    def _find_matching_rule(
        self,
        transaction: Transaction,
    ) -> RoutingRule | None:
        """Find the most specific applicable routing rule."""

        candidates = [
            rule
            for rule in self._rules
            if rule.isolated_bank is transaction.bank
            and self._scope_matches(
                rule.scope,
                transaction.method,
            )
        ]

        if not candidates:
            return None

        # Method-specific rules are more specific than ALL.
        candidates.sort(
            key=lambda rule: (
                rule.scope == "ALL",
            )
        )

        return candidates[0]

    @staticmethod
    def _scope_matches(
        scope: str,
        method: PaymentMethod,
    ) -> bool:
        """Return whether a routing scope matches a transaction."""

        return (
            scope == "ALL"
            or scope == method.value
        )

    @staticmethod
    def _belongs_to_rerouted_traffic(
        *,
        transaction_id: str,
        traffic_percentage: int,
    ) -> bool:
        """Deterministically assign a transaction to shifted traffic."""

        if traffic_percentage <= 0:
            return False

        if traffic_percentage >= 100:
            return True

        digest = hashlib.sha256(
            transaction_id.encode("utf-8")
        ).digest()

        bucket = int.from_bytes(
            digest[:4],
            byteorder="big",
        ) % 100

        return bucket < traffic_percentage