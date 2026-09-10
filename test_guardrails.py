"""Manual validation for PayInChaos guardrails."""

from app.agent import RerouteAction
from app.config import DEFAULT_SETTINGS
from app.guardrails import GuardrailEngine
from app.switch import BankName


def print_decision(name: str, decision) -> None:
    """Pretty-print a guardrail decision."""

    print(f"\n{name}")
    print("-" * 70)

    print("Status:", decision.status)
    print("Approved:", decision.approved)
    print("Isolated:", decision.isolated_bank)
    print("Target:", decision.target_bank)
    print("Scope:", decision.scope)
    print(
        "Requested:",
        decision.requested_percentage,
        "%",
    )
    print(
        "Approved:",
        decision.approved_percentage,
        "%",
    )
    print(
        "Policy intervention:",
        decision.policy_intervention,
    )

    print("Reasons:")

    for reason in decision.reasons:
        print("  -", reason)


def test_normal_approval() -> None:
    """A valid recommendation should be approved."""

    guardrails = GuardrailEngine()

    action = RerouteAction(
        isolated_bank="SBI",
        target_bank="HDFC",
        scope="UPI",
        traffic_percentage=30,
        root_cause_summary="SBI UPI latency spike.",
        cooling_period_seconds=120,
    )

    decision = guardrails.evaluate(
        action,
        now=0.0,
        healthy_banks={
            BankName.HDFC,
            BankName.ICICI,
            BankName.AXIS,
        },
    )

    print_decision(
        "1. NORMAL APPROVAL",
        decision,
    )


def test_percentage_clamp() -> None:
    """A recommendation above 40% must be clamped."""

    guardrails = GuardrailEngine()

    action = RerouteAction(
        isolated_bank="SBI",
        target_bank="HDFC",
        scope="UPI",
        traffic_percentage=80,
        root_cause_summary="Severe SBI UPI outage.",
        cooling_period_seconds=120,
    )

    decision = guardrails.evaluate(
        action,
        now=0.0,
        healthy_banks={
            BankName.HDFC,
            BankName.ICICI,
            BankName.AXIS,
        },
    )

    print_decision(
        "2. TRAFFIC CLAMP",
        decision,
    )


def test_unhealthy_target() -> None:
    """An unhealthy target must be rejected."""

    guardrails = GuardrailEngine()

    action = RerouteAction(
        isolated_bank="SBI",
        target_bank="HDFC",
        scope="UPI",
        traffic_percentage=30,
        root_cause_summary="SBI UPI outage.",
        cooling_period_seconds=120,
    )

    decision = guardrails.evaluate(
        action,
        now=0.0,
        healthy_banks={
            BankName.ICICI,
            BankName.AXIS,
        },
    )

    print_decision(
        "3. UNHEALTHY TARGET",
        decision,
    )


def test_same_bank_target() -> None:
    """Rerouting to the failing bank must be rejected."""

    guardrails = GuardrailEngine()

    action = RerouteAction(
        isolated_bank="SBI",
        target_bank="SBI",
        scope="UPI",
        traffic_percentage=30,
        root_cause_summary="SBI UPI outage.",
        cooling_period_seconds=120,
    )

    decision = guardrails.evaluate(
        action,
        now=0.0,
        healthy_banks={
            BankName.HDFC,
            BankName.ICICI,
            BankName.AXIS,
        },
    )

    print_decision(
        "4. SAME-BANK TARGET",
        decision,
    )


def test_cooldown() -> None:
    """Second route change inside 60s must be blocked."""

    guardrails = GuardrailEngine()

    action = RerouteAction(
        isolated_bank="SBI",
        target_bank="HDFC",
        scope="UPI",
        traffic_percentage=30,
        root_cause_summary="SBI UPI outage.",
        cooling_period_seconds=120,
    )

    healthy_banks = {
        BankName.HDFC,
        BankName.ICICI,
        BankName.AXIS,
    }

    first = guardrails.evaluate(
        action,
        now=0.0,
        healthy_banks=healthy_banks,
    )

    second = guardrails.evaluate(
        action,
        now=30.0,
        healthy_banks=healthy_banks,
    )

    print_decision(
        "5A. FIRST ROUTE CHANGE",
        first,
    )

    print_decision(
        "5B. SECOND ROUTE CHANGE — SHOULD BLOCK",
        second,
    )

    print(
        "\nCooldown remaining:",
        guardrails.cooldown_remaining(
            bank=BankName.SBI,
            now=30.0,
        ),
        "seconds",
    )


def main() -> None:
    """Run guardrail validation."""

    print("\nPAYINCHAOS GUARDRAIL VALIDATION")
    print("=" * 70)

    test_normal_approval()
    test_percentage_clamp()
    test_unhealthy_target()
    test_same_bank_target()
    test_cooldown()

    print("\n" + "=" * 70)
    print("GUARDRAIL VALIDATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()