"""Validate health-aware target-bank protection."""

from __future__ import annotations

from app.agent import RerouteAction
from app.config import DEFAULT_SETTINGS
from app.guardrails import GuardrailEngine
from app.switch import BankName


def test_unhealthy_target_is_blocked() -> None:
    """An unhealthy target bank must never receive rerouted traffic."""

    guardrails = GuardrailEngine(
        settings=DEFAULT_SETTINGS
    )

    action = RerouteAction(
        isolated_bank="SBI",
        target_bank="HDFC",
        scope="UPI",
        traffic_percentage=30,
        root_cause_summary=(
            "SBI UPI latency anomaly requires rerouting."
        ),
        cooling_period_seconds=120,
    )

    # HDFC is intentionally absent because it is unhealthy.
    healthy_banks = {
        BankName.ICICI,
        BankName.AXIS,
    }

    decision = guardrails.evaluate(
        action,
        now=0.0,
        healthy_banks=healthy_banks,
    )

    print()
    print("PAYINCHAOS HEALTH-AWARE ROUTING VALIDATION")
    print("=" * 70)

    print()
    print("1. AI RECOMMENDATION")
    print("-" * 70)
    print("Isolated bank:", action.isolated_bank)
    print("AI target:", action.target_bank)
    print("Scope:", action.scope)
    print("Traffic:", action.traffic_percentage, "%")

    print()
    print("2. CURRENT HEALTHY TARGETS")
    print("-" * 70)
    print(
        "Healthy banks:",
        ", ".join(
            bank.value
            for bank in sorted(
                healthy_banks,
                key=lambda bank: bank.value,
            )
        ),
    )
    print("HDFC healthy:", BankName.HDFC in healthy_banks)

    print()
    print("3. GUARDRAIL DECISION")
    print("-" * 70)
    print("Status:", decision.status)
    print("Approved:", decision.approved)

    for reason in decision.reasons:
        print("Reason:", reason)

    assert decision.approved is False
    assert decision.status == "BLOCKED"
    assert decision.target_bank is BankName.HDFC
    assert any(
        "not currently healthy" in reason
        for reason in decision.reasons
    )

    print()
    print("=" * 70)
    print("HEALTH-AWARE ROUTING VALIDATION PASSED")
    print("=" * 70)


def test_healthy_alternative_is_allowed() -> None:
    """A healthy alternative should be allowed."""

    guardrails = GuardrailEngine(
        settings=DEFAULT_SETTINGS
    )

    action = RerouteAction(
        isolated_bank="SBI",
        target_bank="AXIS",
        scope="UPI",
        traffic_percentage=30,
        root_cause_summary=(
            "SBI UPI latency anomaly requires rerouting."
        ),
        cooling_period_seconds=120,
    )

    healthy_banks = {
        BankName.AXIS,
        BankName.ICICI,
    }

    decision = guardrails.evaluate(
        action,
        now=0.0,
        healthy_banks=healthy_banks,
    )

    print()
    print("4. HEALTHY ALTERNATIVE")
    print("-" * 70)
    print("AI target:", action.target_bank)
    print("Status:", decision.status)
    print("Approved:", decision.approved)

    assert decision.approved is True
    assert decision.status == "APPROVED"
    assert decision.target_bank is BankName.AXIS

    print("Route authorized: SBI -> AXIS")


def main() -> None:
    test_unhealthy_target_is_blocked()
    test_healthy_alternative_is_allowed()

    print()
    print("=" * 70)
    print("ALL HEALTH-AWARE ROUTING TESTS PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
