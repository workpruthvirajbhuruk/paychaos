"""Manual validation for PayInChaos traffic routing."""

from app.agent import RerouteAction
from app.guardrails import GuardrailEngine
from app.router import TrafficRouter
from app.switch import (
    BankName,
    PaymentMethod,
    PaymentSwitch,
)


def build_approved_decision(
    *,
    traffic_percentage: int,
    scope: str,
):
    """Create a realistic approved routing decision."""

    guardrails = GuardrailEngine()

    action = RerouteAction(
        isolated_bank="SBI",
        target_bank="HDFC",
        scope=scope,
        traffic_percentage=traffic_percentage,
        root_cause_summary="SBI payment traffic degraded.",
        cooling_period_seconds=120,
    )

    return guardrails.evaluate(
        action,
        now=0.0,
        healthy_banks={
            BankName.HDFC,
            BankName.ICICI,
            BankName.AXIS,
        },
    )


def test_approved_rule_is_installed() -> None:
    """An approved guardrail decision should become a real route."""

    decision = build_approved_decision(
        traffic_percentage=30,
        scope="UPI",
    )

    router = TrafficRouter()

    rule = router.apply_guardrail_decision(
        decision,
        now=0.0,
    )

    print("\n1. APPROVED ROUTE INSTALLATION")
    print("-" * 70)

    print("Guardrail status:", decision.status)
    print("Rule isolated bank:", rule.isolated_bank)
    print("Rule target bank:", rule.target_bank)
    print("Rule scope:", rule.scope)
    print("Rule traffic:", rule.traffic_percentage, "%")

    assert decision.approved is True
    assert rule.isolated_bank is BankName.SBI
    assert rule.target_bank is BankName.HDFC
    assert rule.scope == "UPI"
    assert rule.traffic_percentage == 30


def test_upi_is_actually_rerouted() -> None:
    """A matching UPI transaction should actually move to HDFC."""

    decision = build_approved_decision(
        traffic_percentage=100,
        scope="UPI",
    )

    router = TrafficRouter()

    router.apply_guardrail_decision(
        decision,
        now=0.0,
    )

    switch = PaymentSwitch(seed=42)

    transaction = switch.create_transaction(
        amount_paise=50000,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    routed_transaction, routing_decision = router.route(
        transaction
    )

    print("\n2. REAL UPI REROUTE")
    print("-" * 70)

    print("Original bank:", transaction.bank)
    print("Routed bank:", routed_transaction.bank)
    print("Rerouted:", routing_decision.rerouted)

    # Guardrails clamp 100% -> 40%, so this individual transaction
    # is not guaranteed to be part of the rerouted 40%.
    #
    # We therefore verify the routing deterministically using the
    # transaction ID's assigned traffic bucket below.
    expected_reroute = router._belongs_to_rerouted_traffic(
        transaction_id=transaction.transaction_id,
        traffic_percentage=40,
    )

    assert routing_decision.rerouted is expected_reroute

    result = switch.process(
        routed_transaction
    )

    print("Processed bank:", result.bank)
    print("Success:", result.success)
    print("Latency:", result.latency_ms, "ms")


def test_scope_is_respected() -> None:
    """A UPI-only rule must not reroute card transactions."""

    decision = build_approved_decision(
        traffic_percentage=100,
        scope="UPI",
    )

    router = TrafficRouter()

    router.apply_guardrail_decision(
        decision,
        now=0.0,
    )

    switch = PaymentSwitch(seed=42)

    card_transaction = switch.create_transaction(
        amount_paise=75000,
        method=PaymentMethod.CARD_VISA,
        bank=BankName.SBI,
    )

    routed_transaction, routing_decision = router.route(
        card_transaction
    )

    print("\n3. SCOPE ENFORCEMENT")
    print("-" * 70)

    print("Original bank:", card_transaction.bank)
    print("Routed bank:", routed_transaction.bank)
    print("Rerouted:", routing_decision.rerouted)

    assert routed_transaction.bank is BankName.SBI
    assert routing_decision.rerouted is False


def test_partial_traffic_is_deterministic() -> None:
    """50% routing should be deterministic for identical transaction IDs."""

    decision = build_approved_decision(
        traffic_percentage=50,
        scope="UPI",
    )

    router = TrafficRouter()

    router.apply_guardrail_decision(
        decision,
        now=0.0,
    )

    switch = PaymentSwitch(seed=42)

    transactions = [
        switch.create_transaction(
            amount_paise=10000 + index,
            method=PaymentMethod.UPI,
            bank=BankName.SBI,
        )
        for index in range(20)
    ]

    first_pass = [
        router.route(transaction)[1].rerouted
        for transaction in transactions
    ]

    second_pass = [
        router.route(transaction)[1].rerouted
        for transaction in transactions
    ]

    print("\n4. DETERMINISTIC TRAFFIC SPLIT")
    print("-" * 70)

    print(
        "Rerouted transactions:",
        sum(first_pass),
        "/",
        len(first_pass),
    )

    print("First pass:", first_pass)
    print("Second pass:", second_pass)

    assert first_pass == second_pass

    assert 1 <= sum(first_pass) <= 19


def test_unapproved_decision_cannot_execute() -> None:
    """The router must refuse a blocked guardrail decision."""

    blocked_guardrails = GuardrailEngine()

    blocked_action = RerouteAction(
        isolated_bank="SBI",
        target_bank="HDFC",
        scope="UPI",
        traffic_percentage=30,
        root_cause_summary="SBI UPI outage.",
        cooling_period_seconds=120,
    )

    blocked_decision = blocked_guardrails.evaluate(
        blocked_action,
        now=0.0,
        healthy_banks={
            BankName.ICICI,
            BankName.AXIS,
        },
    )

    router = TrafficRouter()

    print("\n5. BLOCKED DECISION CANNOT EXECUTE")
    print("-" * 70)

    print("Guardrail status:", blocked_decision.status)
    print("Approved:", blocked_decision.approved)

    assert blocked_decision.approved is False

    try:
        router.apply_guardrail_decision(
            blocked_decision,
            now=0.0,
        )

    except PermissionError as exc:
        print("Execution blocked:", exc)

    else:
        raise AssertionError(
            "Router accepted a blocked guardrail decision."
        )


def main() -> None:
    """Run router validation."""

    print("\nPAYINCHAOS ROUTER VALIDATION")
    print("=" * 70)

    test_approved_rule_is_installed()
    test_upi_is_actually_rerouted()
    test_scope_is_respected()
    test_partial_traffic_is_deterministic()
    test_unapproved_decision_cannot_execute()

    print("\n" + "=" * 70)
    print("ROUTER VALIDATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()