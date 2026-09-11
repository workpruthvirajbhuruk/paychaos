from __future__ import annotations

import argparse

from app.chaos_engine import ChaosScenario
from app.dashboard import DashboardBuilder, render_dashboard
from app.recovery import RecoveryController
from app.switch import BankName, PaymentMethod


class FakeClock:
    """Deterministic simulation clock for the dashboard demo."""

    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def build_controller(clock: FakeClock) -> RecoveryController:
    """Create the recovery controller used by the dashboard demo."""
    return RecoveryController(clock=clock)


def build_transactions(
    count: int,
    *,
    method: PaymentMethod,
    bank: BankName,
) -> list[tuple[int, PaymentMethod, BankName]]:
    """Create synthetic transactions for a specific bank and method."""
    return [
        (10000 + i * 1000, method, bank)
        for i in range(count)
    ]


def build_baseline_traffic() -> list[tuple[int, PaymentMethod, BankName]]:
    """Create healthy traffic across the simulated switch network."""
    return (
        build_transactions(
            40,
            method=PaymentMethod.UPI,
            bank=BankName.HDFC,
        )
        + build_transactions(
            40,
            method=PaymentMethod.UPI,
            bank=BankName.ICICI,
        )
        + build_transactions(
            40,
            method=PaymentMethod.CARD_RUPAY,
            bank=BankName.AXIS,
        )
    )


def build_affected_traffic(
    count: int,
    *,
    bank: BankName = BankName.SBI,
    method: PaymentMethod = PaymentMethod.UPI,
) -> list[tuple[int, PaymentMethod, BankName]]:
    """Create traffic that will be affected by the chaos event."""
    return build_transactions(
        count,
        method=method,
        bank=bank,
    )


def parse_args() -> argparse.Namespace:
    """Parse the dashboard demo scenario."""
    parser = argparse.ArgumentParser(
        description="Run the PayInChaos operator dashboard demo."
    )

    parser.add_argument(
        "--scenario",
        choices=("normal", "cascade"),
        default="normal",
        help=(
            "Demo scenario to run. "
            "'normal' runs UPI latency recovery; "
            "'cascade' demonstrates target failure and escalation."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Run one complete recovery scenario and render the dashboard."""

    args = parse_args()

    clock = FakeClock()
    controller = build_controller(clock)

    baseline = build_baseline_traffic()

    if args.scenario == "cascade":
        scenario = ChaosScenario.CASCADING_SWITCH_FAILURE
    else:
        scenario = ChaosScenario.UPI_LATENCY_SPIKE

    affected_before = build_affected_traffic(100)
    affected_after = build_affected_traffic(100)

    transactions_before_recovery = (
        baseline
        + affected_before
    )

    transactions_after_recovery = (
        baseline
        + affected_after
    )

    run = controller.run_recovery_cycle(
        scenario=scenario,
        transactions_before_recovery=transactions_before_recovery,
        transactions_after_recovery=transactions_after_recovery,
    )

    dashboard = DashboardBuilder(
        ai_model="deterministic-fallback",
    ).build(run)

    render_dashboard(dashboard)


if __name__ == "__main__":
    main()
