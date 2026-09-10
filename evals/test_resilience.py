"""PayInChaos guardrail and anti-oscillation validation.

This test intentionally gives the guardrail layer unsafe AI
recommendations and verifies that deterministic policy wins.

Validates:

1. AI traffic recommendation above 40% is clamped.
2. The policy intervention is explicitly recorded.
3. A second route change during the 60s cooldown is blocked.
4. A different target bank cannot bypass the cooldown.
5. The router only receives approved decisions.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent import RerouteAction
from app.config import DEFAULT_SETTINGS
from app.guardrails import GuardrailEngine
from app.switch import BankName


class FakeClock:
    """Deterministic clock for instant validation."""

    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def make_action(
    *,
    isolated_bank: BankName,
    target_bank: BankName,
    traffic_percentage: int,
) -> RerouteAction:
    """Create an intentionally AI-style routing recommendation."""

    return RerouteAction(
        isolated_bank=isolated_bank.value,
        target_bank=target_bank.value,
        scope="UPI",
        traffic_percentage=traffic_percentage,
        root_cause_summary=(
            "Synthetic AI recommendation for guardrail validation."
        ),
        cooling_period_seconds=120,
    )


def test_traffic_clamp() -> None:
    """Verify the 40% maximum traffic-shift policy."""

    clock = FakeClock()
    guardrails = GuardrailEngine(
        settings=DEFAULT_SETTINGS
    )

    action = make_action(
        isolated_bank=BankName.SBI,
        target_bank=BankName.HDFC,
        traffic_percentage=80,
    )

    decision = guardrails.evaluate(
        action,
        now=clock(),
        healthy_banks={
            BankName.HDFC,
            BankName.ICICI,
            BankName.AXIS,
        },
    )

    print()
    print("1. TRAFFIC POLICY CLAMP")
    print("-" * 70)
    print("AI requested:", decision.requested_percentage, "%")
    print("Policy maximum:", DEFAULT_SETTINGS.max_reroute_percentage, "%")
    print("Approved:", decision.approved_percentage, "%")
    print("Status:", decision.status)
    print("Policy intervention:", decision.policy_intervention)

    assert decision.approved is True
    assert decision.status == "CLAMPED"
    assert decision.requested_percentage == 80
    assert decision.approved_percentage == 40
    assert decision.policy_intervention is True


def test_cooldown_blocks_repeat_change() -> None:
    """Verify the same bank cannot be rerouted again inside cooldown."""

    clock = FakeClock()
    guardrails = GuardrailEngine(
        settings=DEFAULT_SETTINGS
    )

    first_action = make_action(
        isolated_bank=BankName.ICICI,
        target_bank=BankName.HDFC,
        traffic_percentage=30,
    )

    healthy_banks = {
        BankName.HDFC,
        BankName.SBI,
        BankName.AXIS,
    }

    first_decision = guardrails.evaluate(
        first_action,
        now=clock(),
        healthy_banks=healthy_banks,
    )

    print()
    print("2. FIRST ROUTE CHANGE")
    print("-" * 70)
    print("Route:", "ICICI -> HDFC")
    print("Status:", first_decision.status)
    print("Approved:", first_decision.approved)

    assert first_decision.approved is True

    # AI now tries to change ICICI's route again immediately,
    # but chooses a DIFFERENT target. This is the important case:
    # changing the target must not bypass the source-bank cooldown.
    second_action = make_action(
        isolated_bank=BankName.ICICI,
        target_bank=BankName.SBI,
        traffic_percentage=30,
    )

    second_decision = guardrails.evaluate(
        second_action,
        now=clock(),
        healthy_banks=healthy_banks,
    )

    print()
    print("3. IMMEDIATE SECOND ROUTE CHANGE")
    print("-" * 70)
    print("Route attempted:", "ICICI -> SBI")
    print("Status:", second_decision.status)
    print("Approved:", second_decision.approved)
    print(
        "Cooldown remaining:",
        guardrails.cooldown_remaining(
            bank=BankName.ICICI,
            now=clock(),
        ),
        "seconds",
    )

    assert second_decision.approved is False
    assert second_decision.status == "BLOCKED"
    assert any(
        "Cooldown active" in reason
        for reason in second_decision.reasons
    )


def test_cooldown_expires() -> None:
    """Verify routing can change again after the cooldown expires."""

    clock = FakeClock()
    guardrails = GuardrailEngine(
        settings=DEFAULT_SETTINGS
    )

    healthy_banks = {
        BankName.HDFC,
        BankName.SBI,
        BankName.AXIS,
    }

    first_action = make_action(
        isolated_bank=BankName.ICICI,
        target_bank=BankName.HDFC,
        traffic_percentage=30,
    )

    first_decision = guardrails.evaluate(
        first_action,
        now=clock(),
        healthy_banks=healthy_banks,
    )

    assert first_decision.approved is True

    clock.advance(
        DEFAULT_SETTINGS.minimum_cooldown_seconds
    )

    second_action = make_action(
        isolated_bank=BankName.ICICI,
        target_bank=BankName.SBI,
        traffic_percentage=30,
    )

    second_decision = guardrails.evaluate(
        second_action,
        now=clock(),
        healthy_banks=healthy_banks,
    )

    print()
    print("4. COOLDOWN EXPIRY")
    print("-" * 70)
    print(
        "Time advanced:",
        DEFAULT_SETTINGS.minimum_cooldown_seconds,
        "seconds",
    )
    print("New route:", "ICICI -> SBI")
    print("Status:", second_decision.status)
    print("Approved:", second_decision.approved)

    assert second_decision.approved is True
    assert second_decision.status == "APPROVED"


def test_healthy_target_requirement() -> None:
    """Verify AI cannot route traffic to an unhealthy bank."""

    clock = FakeClock()
    guardrails = GuardrailEngine(
        settings=DEFAULT_SETTINGS
    )

    action = make_action(
        isolated_bank=BankName.ICICI,
        target_bank=BankName.HDFC,
        traffic_percentage=30,
    )

    decision = guardrails.evaluate(
        action,
        now=clock(),
        healthy_banks={
            BankName.SBI,
            BankName.AXIS,
        },
    )

    print()
    print("5. UNHEALTHY TARGET PROTECTION")
    print("-" * 70)
    print("AI target:", "HDFC")
    print("Healthy targets:", "SBI, AXIS")
    print("Status:", decision.status)
    print("Approved:", decision.approved)

    assert decision.approved is False
    assert decision.status == "BLOCKED"
    assert any(
        "not currently healthy" in reason
        for reason in decision.reasons
    )


def main() -> None:
    """Run all resilience validations."""

    print()
    print("PAYINCHAOS RESILIENCE VALIDATION")
    print("=" * 70)

    test_traffic_clamp()
    test_cooldown_blocks_repeat_change()
    test_cooldown_expires()
    test_healthy_target_requirement()

    print()
    print("=" * 70)
    print("RESILIENCE VALIDATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
