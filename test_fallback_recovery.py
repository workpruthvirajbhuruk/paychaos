"""Validate autonomous recovery without Gemini."""

from __future__ import annotations

from app.chaos_engine import ChaosScenario
from app.recovery import RecoveryController
from app.switch import BankName, PaymentMethod


class FakeClock:
    """Deterministic clock for instant simulation."""

    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def test_recovery_without_gemini() -> None:
    """The complete recovery pipeline must work without an LLM."""

    clock = FakeClock()

    controller = RecoveryController(
        clock=clock,
        use_gemini=False,
    )

    transactions = [
        (10000, PaymentMethod.UPI, BankName.SBI),
        (20000, PaymentMethod.UPI, BankName.SBI),
        (15000, PaymentMethod.UPI, BankName.SBI),
        (25000, PaymentMethod.UPI, BankName.SBI),
        (30000, PaymentMethod.UPI, BankName.SBI),
    ]

    run = controller.run_recovery_cycle(
        scenario=ChaosScenario.UPI_LATENCY_SPIKE,
        transactions_before_recovery=transactions,
        transactions_after_recovery=transactions,
        detection_delay_seconds=5.0,
        diagnosis_delay_seconds=2.0,
        execution_delay_seconds=2.0,
        verification_delay_seconds=3.0,
    )

    print()
    print("PAYINCHAOS LLM-INDEPENDENT RECOVERY")
    print("=" * 70)

    print()
    print("1. AI AVAILABILITY")
    print("-" * 70)
    print("Gemini enabled:", controller.agent.use_gemini)
    print("Gemini available:", controller.agent.gemini_available)

    print()
    print("2. DETERMINISTIC DIAGNOSIS")
    print("-" * 70)
    print("Source:", run.diagnosis.source)
    print("Diagnosis:", run.diagnosis.diagnosis)

    if run.diagnosis.action:
        print(
            "Target:",
            run.diagnosis.action.target_bank,
        )
        print(
            "Scope:",
            run.diagnosis.action.scope,
        )
        print(
            "Traffic:",
            run.diagnosis.action.traffic_percentage,
            "%",
        )

    print()
    print("3. GUARDRAILS")
    print("-" * 70)

    if run.guardrail_decision:
        print(
            "Status:",
            run.guardrail_decision.status,
        )
        print(
            "Approved:",
            run.guardrail_decision.approved,
        )

    print()
    print("4. REAL ROUTING")
    print("-" * 70)

    if run.routing_rule:
        print(
            "Route:",
            run.routing_rule.isolated_bank.value,
            "->",
            run.routing_rule.target_bank.value,
        )
        print(
            "Traffic:",
            run.routing_rule.traffic_percentage,
            "%",
        )

    print()
    print("5. RECOVERY")
    print("-" * 70)

    if run.verification:
        print(
            "Recovered:",
            run.verification.recovered,
        )
        print(
            "Post-recovery SR:",
            run.verification.after_success_rate,
            "%",
        )
        print(
            "Recovered ₹:",
            run.verification.recovered_amount_paise / 100,
        )

    print()
    print("6. RECOVERY METRICS")
    print("-" * 70)
    print(
        "MTTD:",
        run.metrics.mttd_seconds,
        "seconds",
    )
    print(
        "MTTR:",
        run.metrics.mttr_seconds,
        "seconds",
    )

    assert controller.agent.use_gemini is False
    assert controller.agent.gemini_available is False

    assert run.diagnosis.source == "deterministic_fallback"
    assert run.diagnosis.action is not None

    assert run.guardrail_decision is not None
    assert run.guardrail_decision.approved is True

    assert run.routing_rule is not None
    assert run.routing_rule.target_bank is not BankName.SBI

    assert run.verification is not None
    assert run.verification.recovered is True

    assert run.metrics.mttd_seconds == 5.0
    assert run.metrics.mttr_seconds == 12.0
    assert run.metrics.recovered_amount_paise > 0

    print()
    print("=" * 70)
    print("LLM-INDEPENDENT RECOVERY VALIDATION PASSED")
    print("=" * 70)


if __name__ == "__main__":
    test_recovery_without_gemini()
