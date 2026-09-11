"""Run the PayInChaos operator dashboard.

This demo intentionally mirrors the benchmark's UPI latency-spike
scenario so the operator view tells the same story as the measured
resilience benchmark:

    SBI -> AXIS | UPI | 30%

The dashboard uses deterministic fallback reasoning because Gemini
quota is currently unavailable. Recovery remains fully operational
without the LLM.
"""

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
    """Build the deterministic dashboard demo controller."""

    switch = PaymentSwitch(
        seed=20260911,
        transaction_id_prefix="dashboard",
        clock=clock,
    )

    chaos = ChaosEngine(switch)
    telemetry = Telemetry()
    router = TrafficRouter()

    # Gemini is intentionally disabled for this demo.
    # This proves that the recovery controller remains operational
    # when the LLM is unavailable.
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
    """Create healthy background traffic across the payment network."""

    traffic: list[tuple[int, PaymentMethod, BankName]] = []

    # Healthy HDFC traffic.
    traffic.extend(
        build_transactions(
            20,
            method=PaymentMethod.UPI,
            bank=BankName.HDFC,
        )
    )

    # Healthy ICICI traffic.
    traffic.extend(
        build_transactions(
            20,
            method=PaymentMethod.UPI,
            bank=BankName.ICICI,
        )
    )

    # Healthy AXIS traffic.
    #
    # Keep a sufficiently large healthy target population so that
    # SBI -> AXIS is visibly demonstrated as a viable recovery route.
    traffic.extend(
        build_transactions(
            40,
            method=PaymentMethod.UPI,
            bank=BankName.AXIS,
        )
    )

    return traffic


def build_affected_traffic(
    count: int,
) -> list[tuple[int, PaymentMethod, BankName]]:
    """Create SBI UPI traffic that will be affected by the chaos event."""

    return build_transactions(
        count,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )


def main() -> None:
    """Run one complete recovery scenario and render the dashboard."""

    clock = FakeClock()
    controller = build_controller(clock)

    # ------------------------------------------------------------------
    # DEMO SCENARIO
    # ------------------------------------------------------------------
    #
    # SBI UPI is intentionally degraded by UPI_LATENCY_SPIKE.
    #
    # Expected deterministic recovery:
    #
    #     SBI -> AXIS
    #     UPI
    #     30% traffic
    #
    # This is the same recovery path demonstrated by the benchmark.
    # ------------------------------------------------------------------

    baseline = build_baseline_traffic()

    # Use enough affected traffic to produce a stable telemetry sample.
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
        scenario=ChaosScenario.UPI_LATENCY_SPIKE,
        transactions_before_recovery=transactions_before_recovery,
        transactions_after_recovery=transactions_after_recovery,
    )

    # Keep the dashboard label explicit so the operator view clearly
    # communicates that this demo is using the deterministic fallback.
    dashboard = DashboardBuilder(
        ai_model="deterministic-fallback",
    ).build(run)

    render_dashboard(dashboard)


if __name__ == "__main__":
    main()
