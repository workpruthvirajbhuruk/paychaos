"""Manual validation for PayInChaos health-aware telemetry."""

from app.switch import (
    BankName,
    ErrorCode,
    PaymentMethod,
    PaymentSwitch,
    TransactionResult,
)
from app.telemetry import Telemetry


def make_result(
    *,
    bank: BankName,
    method: PaymentMethod,
    success: bool,
    amount_paise: int,
    latency_ms: float,
    timestamp: float,
    error_code: ErrorCode | None = None,
) -> TransactionResult:
    """Build a deterministic synthetic result."""

    return TransactionResult(
        transaction_id=(
            f"test_{bank.value}_{timestamp}_{amount_paise}"
        ),
        bank=bank,
        method=method,
        amount_paise=amount_paise,
        success=success,
        latency_ms=latency_ms,
        error_code=error_code,
        timestamp=timestamp,
    )


def test_healthy_bank() -> None:
    """A healthy bank should be classified as healthy."""

    telemetry = Telemetry()

    for index in range(10):
        telemetry.record(
            make_result(
                bank=BankName.HDFC,
                method=PaymentMethod.UPI,
                success=True,
                amount_paise=10000,
                latency_ms=180.0,
                timestamp=float(index),
            )
        )

    health = telemetry.bank_health(
        bank=BankName.HDFC,
        now=9.0,
    )

    print("\n1. HEALTHY BANK")
    print("-" * 70)

    print("Bank:", health.bank)
    print("Success rate:", health.success_rate, "%")
    print("P99:", health.p99_latency_ms, "ms")
    print("Healthy:", health.healthy)
    print("Anomaly:", health.anomaly_detected)

    assert health.healthy is True
    assert health.anomaly_detected is False
    assert health.success_rate == 100.0


def test_unhealthy_bank() -> None:
    """A severely degraded bank should be unhealthy."""

    telemetry = Telemetry()

    for index in range(10):
        telemetry.record(
            make_result(
                bank=BankName.SBI,
                method=PaymentMethod.UPI,
                success=index == 0,
                amount_paise=10000,
                latency_ms=4500.0,
                timestamp=float(index),
                error_code=(
                    None
                    if index == 0
                    else ErrorCode.GATEWAY_TIMEOUT
                ),
            )
        )

    health = telemetry.bank_health(
        bank=BankName.SBI,
        now=9.0,
    )

    print("\n2. UNHEALTHY BANK")
    print("-" * 70)

    print("Bank:", health.bank)
    print("Success rate:", health.success_rate, "%")
    print("P99:", health.p99_latency_ms, "ms")
    print("Healthy:", health.healthy)
    print("Anomaly:", health.anomaly_detected)
    print("Reasons:", health.anomaly_reasons)

    assert health.healthy is False
    assert health.anomaly_detected is True
    assert health.success_rate < 85.0
    assert health.p99_latency_ms > 2500.0


def test_healthy_bank_set() -> None:
    """Only banks without detected anomalies should be routable."""

    telemetry = Telemetry()

    # SBI is unhealthy.
    for index in range(10):
        telemetry.record(
            make_result(
                bank=BankName.SBI,
                method=PaymentMethod.UPI,
                success=False,
                amount_paise=10000,
                latency_ms=4500.0,
                timestamp=float(index),
                error_code=ErrorCode.GATEWAY_TIMEOUT,
            )
        )

    # HDFC is healthy.
    for index in range(10):
        telemetry.record(
            make_result(
                bank=BankName.HDFC,
                method=PaymentMethod.UPI,
                success=True,
                amount_paise=10000,
                latency_ms=180.0,
                timestamp=float(index),
            )
        )

    healthy = telemetry.healthy_banks(
        now=9.0,
        exclude={BankName.SBI},
    )

    print("\n3. HEALTHY BANK SET")
    print("-" * 70)

    print(
        "Healthy banks:",
        sorted(
            bank.value
            for bank in healthy
        ),
    )

    assert BankName.HDFC in healthy
    assert BankName.SBI not in healthy


def test_revenue_metrics() -> None:
    """Revenue metrics should correctly sum transaction values."""

    telemetry = Telemetry()

    telemetry.record(
        make_result(
            bank=BankName.HDFC,
            method=PaymentMethod.UPI,
            success=True,
            amount_paise=50000,
            latency_ms=180.0,
            timestamp=0.0,
        )
    )

    telemetry.record(
        make_result(
            bank=BankName.SBI,
            method=PaymentMethod.UPI,
            success=False,
            amount_paise=25000,
            latency_ms=4500.0,
            timestamp=1.0,
            error_code=ErrorCode.GATEWAY_TIMEOUT,
        )
    )

    telemetry.record(
        make_result(
            bank=BankName.AXIS,
            method=PaymentMethod.CARD_VISA,
            success=True,
            amount_paise=75000,
            latency_ms=200.0,
            timestamp=2.0,
        )
    )

    revenue = telemetry.revenue_metrics(
        now=2.0
    )

    print("\n4. REVENUE METRICS")
    print("-" * 70)

    print(
        "Total processed: ₹",
        revenue.total_processed_rupees,
    )

    print(
        "Successful: ₹",
        revenue.successful_processed_rupees,
    )

    print(
        "Failed: ₹",
        revenue.failed_processed_rupees,
    )

    print(
        "Successful transactions:",
        revenue.successful_transactions,
    )

    print(
        "Failed transactions:",
        revenue.failed_transactions,
    )

    assert revenue.total_processed_paise == 150000
    assert revenue.successful_processed_paise == 125000
    assert revenue.failed_processed_paise == 25000
    assert revenue.successful_transactions == 2
    assert revenue.failed_transactions == 1


def test_real_switch_results_still_work() -> None:
    """Telemetry remains compatible with real switch results."""

    switch = PaymentSwitch(seed=42)
    telemetry = Telemetry()

    transaction = switch.create_transaction(
        amount_paise=100000,
        method=PaymentMethod.UPI,
        bank=BankName.HDFC,
    )

    result = switch.process(transaction)

    telemetry.record(result)

    snapshot = telemetry.snapshot(
        bank=BankName.HDFC,
        now=result.timestamp,
    )

    print("\n5. REAL SWITCH COMPATIBILITY")
    print("-" * 70)

    print("Success:", result.success)
    print("Latency:", result.latency_ms, "ms")
    print("Telemetry transactions:", snapshot.total_transactions)

    assert snapshot.total_transactions == 1


def main() -> None:
    """Run telemetry health validation."""

    print("\nPAYINCHAOS TELEMETRY HEALTH VALIDATION")
    print("=" * 70)

    test_healthy_bank()
    test_unhealthy_bank()
    test_healthy_bank_set()
    test_revenue_metrics()
    test_real_switch_results_still_work()

    print("\n" + "=" * 70)
    print("TELEMETRY HEALTH VALIDATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()