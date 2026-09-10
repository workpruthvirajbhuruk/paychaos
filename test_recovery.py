"""Manual validation for the PayInChaos autonomous recovery loop."""

from __future__ import annotations

from app.chaos_engine import ChaosScenario
from app.recovery import RecoveryController
from app.switch import (
    BankName,
    PaymentMethod,
)


class FakeClock:
    """Deterministic clock for instant simulation."""

    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(
        self,
        seconds: float,
    ) -> None:
        self.current += seconds


def test_sbi_upi_recovery() -> None:
    """SBI UPI latency failure should recover through rerouting."""

    clock = FakeClock()

    controller = RecoveryController(
        clock=clock,
    )

    run = controller.run_recovery_cycle(
        scenario=ChaosScenario.UPI_LATENCY_SPIKE,

        transactions_before_recovery=[
            (
                10000,
                PaymentMethod.UPI,
                BankName.SBI,
            ),
            (
                20000,
                PaymentMethod.UPI,
                BankName.SBI,
            ),
            (
                15000,
                PaymentMethod.UPI,
                BankName.SBI,
            ),
            (
                25000,
                PaymentMethod.UPI,
                BankName.SBI,
            ),
            (
                30000,
                PaymentMethod.UPI,
                BankName.SBI,
            ),
        ],

        transactions_after_recovery=[
            (
                10000,
                PaymentMethod.UPI,
                BankName.SBI,
            ),
            (
                20000,
                PaymentMethod.UPI,
                BankName.SBI,
            ),
            (
                15000,
                PaymentMethod.UPI,
                BankName.SBI,
            ),
            (
                25000,
                PaymentMethod.UPI,
                BankName.SBI,
            ),
            (
                30000,
                PaymentMethod.UPI,
                BankName.SBI,
            ),
        ],

        detection_delay_seconds=5.0,
        diagnosis_delay_seconds=2.0,
        execution_delay_seconds=2.0,
        verification_delay_seconds=3.0,
    )

    print("\n1. AUTONOMOUS SBI UPI RECOVERY")
    print("-" * 70)

    print(
        "Scenario:",
        run.scenario.value,
    )

    print(
        "Affected bank:",
        run.affected_bank.value,
    )

    print(
        "Anomaly:",
        run.anomaly_snapshot.anomaly_detected,
    )

    print(
        "Initial success rate:",
        run.anomaly_snapshot.success_rate,
        "%",
    )

    print(
        "Initial P99:",
        run.anomaly_snapshot.p99_latency_ms,
        "ms",
    )

    print(
        "AI source:",
        run.diagnosis.source,
    )

    print(
        "AI diagnosis:",
        run.diagnosis.diagnosis,
    )

    if run.diagnosis.action:
        print(
            "AI target:",
            run.diagnosis.action.target_bank,
        )

        print(
            "AI scope:",
            run.diagnosis.action.scope,
        )

        print(
            "AI traffic:",
            run.diagnosis.action.traffic_percentage,
            "%",
        )

    if run.guardrail_decision:
        print(
            "Guardrail:",
            run.guardrail_decision.status,
        )

        print(
            "Approved traffic:",
            run.guardrail_decision.approved_percentage,
            "%",
        )

    if run.routing_rule:
        print(
            "Actual route:",
            run.routing_rule.isolated_bank.value,
            "->",
            run.routing_rule.target_bank.value,
        )

        print(
            "Actual traffic:",
            run.routing_rule.traffic_percentage,
            "%",
        )

    if run.verification:
        print(
            "Recovered:",
            run.verification.recovered,
        )

        print(
            "Recovery success rate:",
            run.verification.after_success_rate,
            "%",
        )

        print(
            "Attempted recovery ₹:",
            round(
                run.verification.attempted_recovery_amount_paise
                / 100,
                2,
            ),
        )

        print(
            "Actually recovered ₹:",
            run.verification.recovered_amount_paise
            / 100,
        )

        print(
            "Recovered reason:",
            run.verification.reason,
        )

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

    print(
        "Revenue at risk ₹:",
        run.metrics.failed_amount_rupees,
    )

    print(
        "Recovered ₹:",
        run.metrics.recovered_amount_rupees,
    )

    # ---------------------------------------------------------
    # Assertions
    # ---------------------------------------------------------

    assert run.anomaly_snapshot.anomaly_detected is True

    assert run.diagnosis.action is not None

    assert run.guardrail_decision is not None
    assert run.guardrail_decision.approved is True

    assert run.routing_rule is not None
    assert run.routing_rule.target_bank is not BankName.SBI

    assert run.verification is not None
    assert run.verification.recovered is True

    assert run.metrics.mttd_seconds == 5.0

    # 5s detection + 2s diagnosis + 2s execution + 3s verification.
    assert run.metrics.mttr_seconds == 12.0

    assert (
        run.metrics.recovered_amount_paise > 0
    )


def main() -> None:
    """Run autonomous recovery validation."""

    print("\nPAYINCHAOS AUTONOMOUS RECOVERY VALIDATION")
    print("=" * 70)

    test_sbi_upi_recovery()

    print("\n" + "=" * 70)
    print("AUTONOMOUS RECOVERY VALIDATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()