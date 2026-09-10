"""Manual validation for PayInChaos switch, chaos and telemetry."""

from app.chaos_engine import ChaosEngine, ChaosScenario
from app.switch import (
    BankName,
    PaymentMethod,
    PaymentSwitch,
)
from app.telemetry import Telemetry


def run_transaction(
    switch: PaymentSwitch,
    telemetry: Telemetry,
    bank: BankName,
    method: PaymentMethod,
) -> None:
    """Create, process and record one transaction."""

    transaction = switch.create_transaction(
        amount_paise=50000,
        method=method,
        bank=bank,
    )

    result = switch.process(transaction)

    telemetry.record(result)

    status = "SUCCESS" if result.success else "FAILED"

    error = result.error_code.value if result.error_code else "-"

    print(
        f"  {bank.value:<6} "
        f"{method.value:<12} "
        f"{status:<7} "
        f"{result.latency_ms:>8.2f} ms "
        f"{error}"
    )


def print_snapshot(telemetry: Telemetry, bank: BankName) -> None:
    """Print telemetry for one bank."""

    snapshot = telemetry.snapshot(bank=bank)

    print()
    print(f"  TELEMETRY — {bank.value}")
    print(f"  Transactions : {snapshot.total_transactions}")
    print(f"  Success Rate : {snapshot.success_rate:.2f}%")
    print(f"  P99 Latency  : {snapshot.p99_latency_ms:.2f} ms")
    print(f"  Errors       : {snapshot.error_distribution}")
    print(f"  Anomaly      : {snapshot.anomaly_detected}")

    if snapshot.anomaly_reasons:
        print(f"  Reasons      : {snapshot.anomaly_reasons}")


def test_otp_silent_drop() -> None:
    """Verify HDFC OTP failure and telemetry."""

    print("\n[1] OTP SILENT DROP")
    print("=" * 70)

    switch = PaymentSwitch(seed=42)
    chaos = ChaosEngine(switch)
    telemetry = Telemetry()

    chaos.inject(ChaosScenario.OTP_SILENT_DROP)

    run_transaction(
        switch,
        telemetry,
        BankName.HDFC,
        PaymentMethod.UPI,
    )

    run_transaction(
        switch,
        telemetry,
        BankName.HDFC,
        PaymentMethod.CARD_RUPAY,
    )

    run_transaction(
        switch,
        telemetry,
        BankName.HDFC,
        PaymentMethod.CARD_VISA,
    )

    print_snapshot(
        telemetry,
        BankName.HDFC,
    )


def test_upi_latency_spike() -> None:
    """Verify SBI UPI latency anomaly."""

    print("\n[2] UPI LATENCY SPIKE")
    print("=" * 70)

    switch = PaymentSwitch(seed=42)
    chaos = ChaosEngine(switch)
    telemetry = Telemetry()

    chaos.inject(ChaosScenario.UPI_LATENCY_SPIKE)

    run_transaction(
        switch,
        telemetry,
        BankName.SBI,
        PaymentMethod.UPI,
    )

    run_transaction(
        switch,
        telemetry,
        BankName.SBI,
        PaymentMethod.CARD_RUPAY,
    )

    run_transaction(
        switch,
        telemetry,
        BankName.SBI,
        PaymentMethod.CARD_VISA,
    )

    print_snapshot(
        telemetry,
        BankName.SBI,
    )

    upi_snapshot = telemetry.method_snapshot(
        bank=BankName.SBI,
        method=PaymentMethod.UPI,
    )

    print()
    print("  UPI-SPECIFIC TELEMETRY")
    print(f"  Success Rate : {upi_snapshot.success_rate:.2f}%")
    print(f"  P99 Latency  : {upi_snapshot.p99_latency_ms:.2f} ms")
    print(f"  Anomaly      : {upi_snapshot.anomaly_detected}")
    print(f"  Reasons      : {upi_snapshot.anomaly_reasons}")


def test_bin_isolated_failure() -> None:
    """Verify AXIS RuPay isolation."""

    print("\n[3] BIN ISOLATED FAILURE")
    print("=" * 70)

    switch = PaymentSwitch(seed=42)
    chaos = ChaosEngine(switch)
    telemetry = Telemetry()

    chaos.inject(ChaosScenario.BIN_ISOLATED_FAILURE)

    run_transaction(
        switch,
        telemetry,
        BankName.AXIS,
        PaymentMethod.CARD_RUPAY,
    )

    run_transaction(
        switch,
        telemetry,
        BankName.AXIS,
        PaymentMethod.CARD_VISA,
    )

    run_transaction(
        switch,
        telemetry,
        BankName.AXIS,
        PaymentMethod.UPI,
    )

    print_snapshot(
        telemetry,
        BankName.AXIS,
    )


def test_flapping_gateway() -> None:
    """Verify ICICI flapping behavior."""

    print("\n[4] FLAPPING GATEWAY")
    print("=" * 70)

    switch = PaymentSwitch(seed=42)
    chaos = ChaosEngine(switch)
    telemetry = Telemetry()

    chaos.inject(ChaosScenario.FLAPPING_GATEWAY)

    for elapsed_seconds in (0, 15, 30, 45):
        chaos.tick(elapsed_seconds)

        transaction = switch.create_transaction(
            amount_paise=50000,
            method=PaymentMethod.UPI,
            bank=BankName.ICICI,
        )

        result = switch.process(transaction)
        telemetry.record(result)

        status = "SUCCESS" if result.success else "FAILED"

        print(
            f"  t={elapsed_seconds:>2}s "
            f"{status:<7} "
            f"{result.latency_ms:>8.2f} ms "
            f"{result.error_code.value if result.error_code else '-'}"
        )

    print_snapshot(
        telemetry,
        BankName.ICICI,
    )


def test_rolling_window() -> None:
    """Verify telemetry removes results outside 30 seconds."""

    print("\n[5] ROLLING WINDOW")
    print("=" * 70)

    class FakeClock:
        def __init__(self) -> None:
            self.current = 0.0

        def now(self) -> float:
            return self.current

        def advance(self, seconds: float) -> None:
            self.current += seconds

    clock = FakeClock()

    switch = PaymentSwitch(
        seed=42,
        clock=clock.now,
    )

    telemetry = Telemetry()

    # Transaction at t=0.
    transaction = switch.create_transaction(
        amount_paise=50000,
        method=PaymentMethod.UPI,
        bank=BankName.HDFC,
    )

    result = switch.process(transaction)
    telemetry.record(result)

    print(f"  t={clock.current:.0f}s -> stored: {telemetry.result_count}")

    # Still inside 30-second window.
    clock.advance(20)

    transaction = switch.create_transaction(
        amount_paise=50000,
        method=PaymentMethod.UPI,
        bank=BankName.HDFC,
    )

    result = switch.process(transaction)
    telemetry.record(result)

    print(f"  t={clock.current:.0f}s -> stored: {telemetry.result_count}")

    # First transaction is now exactly 35 seconds old.
    clock.advance(15)

    snapshot = telemetry.snapshot(
        bank=BankName.HDFC,
        now=clock.now(),
    )

    print(f"  t={clock.current:.0f}s -> stored: {telemetry.result_count}")
    print(
        f"  Rolling-window transactions: "
        f"{snapshot.total_transactions}"
    )


def main() -> None:
    """Run all validation tests."""

    print("\nPAYINCHAOS TELEMETRY VALIDATION")
    print("=" * 70)

    test_otp_silent_drop()
    test_upi_latency_spike()
    test_bin_isolated_failure()
    test_flapping_gateway()
    test_rolling_window()

    print("\n" + "=" * 70)
    print("TELEMETRY VALIDATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()