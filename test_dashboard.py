from app.agent import AIAgent
from app.chaos_engine import ChaosEngine, ChaosScenario
from app.dashboard import DashboardBuilder
from app.recovery import RecoveryController
from app.router import TrafficRouter
from app.switch import BankName, PaymentMethod, PaymentSwitch
from app.telemetry import Telemetry


def build_controller() -> RecoveryController:
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
        chaos=chaos,
        telemetry=telemetry,
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
    return [
        (
            amount_paise,
            method,
            bank,
        )
        for _ in range(count)
    ]


def test_dashboard_contains_all_four_banks():
    controller = build_controller()

    before = build_transactions(
        20,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    after = build_transactions(
        20,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    run = controller.run_recovery_cycle(
        scenario=ChaosScenario.UPI_LATENCY_SPIKE,
        transactions_before_recovery=before,
        transactions_after_recovery=after,
    )

    dashboard = DashboardBuilder().build(run)

    banks = {card.bank for card in dashboard.banks}

    assert banks == {
        BankName.HDFC,
        BankName.ICICI,
        BankName.SBI,
        BankName.AXIS,
    }


def test_dashboard_contains_real_chaos_event():
    controller = build_controller()

    before = build_transactions(
        20,
        method=PaymentMethod.CARD_RUPAY,
        bank=BankName.AXIS,
    )

    after = build_transactions(
        20,
        method=PaymentMethod.CARD_RUPAY,
        bank=BankName.AXIS,
    )

    run = controller.run_recovery_cycle(
        scenario=ChaosScenario.BIN_ISOLATED_FAILURE,
        transactions_before_recovery=before,
        transactions_after_recovery=after,
    )

    dashboard = DashboardBuilder().build(run)

    assert dashboard.chaos is not None
    assert dashboard.chaos.scenario == "BIN_ISOLATED_FAILURE"
    assert dashboard.chaos.bank is BankName.AXIS
    assert dashboard.chaos.affected_method == "CARD_RUPAY"


def test_dashboard_contains_ai_and_guardrail_decisions():
    controller = build_controller()

    before = build_transactions(
        20,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    after = build_transactions(
        20,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    run = controller.run_recovery_cycle(
        scenario=ChaosScenario.UPI_LATENCY_SPIKE,
        transactions_before_recovery=before,
        transactions_after_recovery=after,
    )

    dashboard = DashboardBuilder().build(run)

    assert dashboard.ai.source == "deterministic_fallback"
    assert dashboard.ai.target_bank is not None
    assert dashboard.ai.scope == "UPI"
    assert dashboard.ai.requested_percentage is not None

    assert dashboard.guardrails is not None
    assert dashboard.guardrails.approved is True


def test_dashboard_contains_recovery_metrics():
    controller = build_controller()

    before = build_transactions(
        20,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    after = build_transactions(
        20,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    run = controller.run_recovery_cycle(
        scenario=ChaosScenario.UPI_LATENCY_SPIKE,
        transactions_before_recovery=before,
        transactions_after_recovery=after,
    )

    dashboard = DashboardBuilder().build(run)

    assert dashboard.recovery.mttd_seconds is not None
    assert dashboard.recovery.mttr_seconds is not None
    assert dashboard.recovery.recovered_amount_rupees >= 0.0
    assert dashboard.recovery.failed_amount_rupees >= 0.0


def test_dashboard_reports_recovered_state():
    controller = build_controller()

    before = build_transactions(
        20,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    after = build_transactions(
        20,
        method=PaymentMethod.UPI,
        bank=BankName.SBI,
    )

    run = controller.run_recovery_cycle(
        scenario=ChaosScenario.UPI_LATENCY_SPIKE,
        transactions_before_recovery=before,
        transactions_after_recovery=after,
    )

    dashboard = DashboardBuilder().build(run)

    assert dashboard.recovery.recovered is True
    assert dashboard.overall_status == "RECOVERED"