"""Validate deterministic fallback recovery policy."""

from __future__ import annotations

from app.agent import AIAgent
from app.switch import BankName, ErrorCode, PaymentMethod
from app.telemetry import TelemetrySnapshot


def make_snapshot(
    *,
    bank: BankName,
    method: PaymentMethod | None,
    success_rate: float,
    p99_latency_ms: float,
    errors: dict[str, int],
) -> TelemetrySnapshot:
    """Create a synthetic anomalous telemetry snapshot."""

    return TelemetrySnapshot(
        bank=bank,
        method=method,
        total_transactions=100,
        successful_transactions=int(success_rate),
        failed_transactions=100 - int(success_rate),
        success_rate=success_rate,
        p99_latency_ms=p99_latency_ms,
        error_distribution=errors,
        anomaly_detected=True,
        anomaly_reasons=("synthetic_test_anomaly",),
    )


def test_method_specific_policy() -> None:
    """Method-specific incidents should shift 30%."""

    agent = AIAgent(
        use_gemini=False,
    )

    snapshot = make_snapshot(
        bank=BankName.AXIS,
        method=PaymentMethod.CARD_RUPAY,
        success_rate=0.0,
        p99_latency_ms=220.0,
        errors={
            ErrorCode.ISSUER_UNAVAILABLE.value: 100,
        },
    )

    diagnosis = agent.diagnose(
        snapshot,
        available_banks=[
            BankName.HDFC,
            BankName.ICICI,
            BankName.SBI,
        ],
    )

    print()
    print("1. METHOD-SPECIFIC FAILURE")
    print("-" * 70)
    print("Diagnosis:", diagnosis.diagnosis)
    print("Scope:", diagnosis.action.scope)
    print(
        "Traffic policy:",
        diagnosis.action.traffic_percentage,
        "%",
    )

    assert diagnosis.source == "deterministic_fallback"
    assert diagnosis.action is not None
    assert diagnosis.action.scope == "CARD_RUPAY"
    assert diagnosis.action.traffic_percentage == 30


def test_latency_policy() -> None:
    """Latency-driven incidents should shift 30%."""

    agent = AIAgent(
        use_gemini=False,
    )

    snapshot = make_snapshot(
        bank=BankName.SBI,
        method=PaymentMethod.UPI,
        success_rate=0.0,
        p99_latency_ms=4500.0,
        errors={
            ErrorCode.GATEWAY_TIMEOUT.value: 100,
        },
    )

    diagnosis = agent.diagnose(
        snapshot,
        available_banks=[
            BankName.HDFC,
            BankName.ICICI,
            BankName.AXIS,
        ],
    )

    print()
    print("2. LATENCY-DRIVEN FAILURE")
    print("-" * 70)
    print("Diagnosis:", diagnosis.diagnosis)
    print("Scope:", diagnosis.action.scope)
    print(
        "Traffic policy:",
        diagnosis.action.traffic_percentage,
        "%",
    )

    assert diagnosis.source == "deterministic_fallback"
    assert diagnosis.action is not None
    assert diagnosis.action.scope == "UPI"
    assert diagnosis.action.traffic_percentage == 30


def test_bank_wide_policy() -> None:
    """Bank-wide availability incidents should shift 40%."""

    agent = AIAgent(
        use_gemini=False,
    )

    snapshot = make_snapshot(
        bank=BankName.ICICI,
        method=None,
        success_rate=20.0,
        p99_latency_ms=220.0,
        errors={
            ErrorCode.BANK_ERROR.value: 80,
        },
    )

    diagnosis = agent.diagnose(
        snapshot,
        available_banks=[
            BankName.HDFC,
            BankName.SBI,
            BankName.AXIS,
        ],
    )

    print()
    print("3. BANK-WIDE FAILURE")
    print("-" * 70)
    print("Diagnosis:", diagnosis.diagnosis)
    print("Scope:", diagnosis.action.scope)
    print(
        "Traffic policy:",
        diagnosis.action.traffic_percentage,
        "%",
    )

    assert diagnosis.source == "deterministic_fallback"
    assert diagnosis.action is not None
    assert diagnosis.action.scope == "ALL"
    assert diagnosis.action.traffic_percentage == 40


def test_policy_never_exceeds_guardrail() -> None:
    """Fallback policy must never exceed the configured maximum."""

    agent = AIAgent(
        use_gemini=False,
    )

    snapshot = make_snapshot(
        bank=BankName.HDFC,
        method=None,
        success_rate=10.0,
        p99_latency_ms=300.0,
        errors={
            ErrorCode.BANK_ERROR.value: 90,
        },
    )

    diagnosis = agent.diagnose(
        snapshot,
        available_banks=[
            BankName.ICICI,
            BankName.SBI,
            BankName.AXIS,
        ],
    )

    print()
    print("4. GUARDRAIL BOUNDARY")
    print("-" * 70)
    print(
        "Fallback traffic:",
        diagnosis.action.traffic_percentage,
        "%",
    )
    print("Maximum policy:", 40, "%")

    assert diagnosis.action is not None
    assert diagnosis.action.traffic_percentage <= 40


def main() -> None:
    print()
    print("PAYINCHAOS DETERMINISTIC FALLBACK POLICY")
    print("=" * 70)

    test_method_specific_policy()
    test_latency_policy()
    test_bank_wide_policy()
    test_policy_never_exceeds_guardrail()

    print()
    print("=" * 70)
    print("DETERMINISTIC FALLBACK POLICY VALIDATION PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()
