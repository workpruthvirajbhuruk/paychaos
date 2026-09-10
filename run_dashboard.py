"""Run the PayInChaos operator dashboard."""

from app.agent import AIAgent
from app.chaos_engine import ChaosEngine, ChaosScenario
from app.dashboard import DashboardBuilder, render_dashboard
from app.recovery import RecoveryController
from app.router import TrafficRouter
from app.switch import BankName, PaymentMethod, PaymentSwitch
from app.telemetry import Telemetry


def build_controller() -> RecoveryController:
    """Build a deterministic dashboard demo controller."""

    switch = PaymentSwitch(
        seed=42,
        transaction_id_prefix="dashboard",
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


def main() -> None:
    """Run one complete recovery scenario and render it."""

    controller = build_controller()

    before = build_transactions(
        40,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    after = build_transactions(
        40,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

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