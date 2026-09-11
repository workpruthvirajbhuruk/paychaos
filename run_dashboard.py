"""Run the PayInChaos operator dashboard."""

from app.agent import AIAgent
from app.chaos_engine import ChaosEngine, ChaosScenario
from app.dashboard import DashboardBuilder, render_dashboard
from app.recovery import RecoveryController
from app.router import TrafficRouter
from app.switch import BankName, PaymentMethod, PaymentSwitch
from app.telemetry import Telemetry


class FakeClock:
    """Deterministic simulation clock for the dashboard demo."""

    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def build_controller(clock: FakeClock) -> RecoveryController:
    """Build a deterministic dashboard demo controller."""

    switch = PaymentSwitch(
        seed=42,
        transaction_id_prefix="dashboard",
        clock=clock,
    )

    chaos = ChaosEngine(switch)
    telemetry = Telemetry()
    router = TrafficRouter()

    agent = AIAgent(
        telemetry=telemetry,
        use_gemini=False,
    )

    return RecoveryController(
        switch=switch,
        telemetry=telemetry,
        chaos=chaos,
        agent=agent,
        router=router,
        clock=clock,
        use_gemini=False,
    )


def build_transactions(
    count: int,
    *,
    method: PaymentMethod,
    bank: BankName,
    amount_paise: int = 10_000,
) -> list[tuple[int, PaymentMethod, BankName]]:
    """Create deterministic synthetic payment traffic."""

    return [
        (
            amount_paise,
            method,
            bank,
        )
        for _ in range(count)
    ]


def build_baseline_traffic() -> list[tuple[int, PaymentMethod, BankName]]:
    """Create healthy background traffic across all four banks."""

    traffic: list[tuple[int, PaymentMethod, BankName]] = []

    traffic.extend(
        build_transactions(
            20,
            method=PaymentMethod.UPI,
            bank=BankName.HDFC,
        )
    )

    traffic.extend(
        build_transactions(
            20,
            method=PaymentMethod.UPI,
            bank=BankName.ICICI,
        )
    )

    traffic.extend(
        build_transactions(
            40,
            method=PaymentMethod.UPI,
            bank=BankName.SBI,
        )
    )

    traffic.extend(
        build_transactions(
            20,
            method=PaymentMethod.UPI,
            bank=BankName.AXIS,
        )
    )

    return traffic


def main() -> None:
    """Run one complete recovery scenario and render it."""

    clock = FakeClock()
    controller = build_controller(clock)

    # Healthy background traffic makes the dashboard
    # represent a live multi-bank payment environment.
    baseline = build_baseline_traffic()

    # The affected bank receives dedicated failure traffic.
    affected_before = build_transactions(
        40,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    affected_after = build_transactions(
        40,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    before = baseline + affected_before
    after = baseline + affected_after

    run = controller.run_recovery_cycle(
        scenario=ChaosScenario.UPI_LATENCY_SPIKE,
        transactions_before_recovery=before,
        transactions_after_recovery=after,
    )

    dashboard = DashboardBuilder(
        ai_model="deterministic-fallback",
    ).build(run)

    render_dashboard(dashboard)


if __name__ == "__main__":
    main()