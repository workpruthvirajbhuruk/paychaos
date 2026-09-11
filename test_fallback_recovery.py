"""Validation that recovery works without Gemini."""

from __future__ import annotations

from app.agent import AIAgent
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


def test_recovery_without_gemini() -> None:
    """Recovery should succeed using the deterministic fallback."""

    clock = FakeClock()

    agent = AIAgent(
        use_gemini=False,
    )

    controller = RecoveryController(
        clock=clock,
        agent=agent,
    )

    transactions = [
        (
            10000 + i * 1000,
            PaymentMethod.UPI,
            BankName.SBI,
        )
        for i in range(100)
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

    assert run.diagnosis.source == "deterministic_fallback"

    assert run.guardrail_decision is not None
    assert run.guardrail_decision.approved is True

    assert run.routing_rule is not None
    assert run.routing_rule.target_bank is BankName.AXIS

    assert run.verification is not None
    assert run.verification.recovered is True
