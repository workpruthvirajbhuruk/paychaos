"""Operator dashboard for PayInChaos.

This module contains two layers:

1. DashboardBuilder
   Converts a RecoveryRun into immutable, UI-friendly data.

2. render_dashboard
   Converts that snapshot into a Rich terminal interface.

ARCHITECTURAL RULE:
    Recovery engine -> Dashboard model -> UI

The dashboard must never:
    - make AI decisions
    - authorize routing
    - execute routing
    - modify payment-switch state
    - modify guardrails

It only observes and presents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.recovery import RecoveryRun
from app.switch import BankName


DashboardStatus = Literal[
    "HEALTHY",
    "DEGRADED",
    "RECOVERED",
    "BLOCKED",
]


@dataclass(frozen=True, slots=True)
class BankHealthCard:
    """Dashboard representation of one bank's health."""

    bank: BankName
    success_rate: float
    p99_latency_ms: float
    total_transactions: int
    failed_transactions: int
    status: DashboardStatus


@dataclass(frozen=True, slots=True)
class ChaosPanel:
    """Dashboard representation of the active chaos event."""

    scenario: str
    bank: BankName
    description: str
    affected_method: str | None
    injected_latency_ms: float | None


@dataclass(frozen=True, slots=True)
class AIReasoningPanel:
    """Dashboard representation of the AI decision."""

    source: str
    model: str | None
    diagnosis: str
    confidence: float
    target_bank: BankName | None
    scope: str | None
    requested_percentage: int | None


@dataclass(frozen=True, slots=True)
class GuardrailPanel:
    """Dashboard representation of the authorization decision."""

    status: str
    approved: bool
    policy_intervention: bool
    requested_percentage: int | None
    approved_percentage: int | None
    cooling_period_seconds: int | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecoveryPanel:
    """Dashboard representation of recovery performance."""

    recovered: bool
    mttd_seconds: float | None
    mttr_seconds: float | None
    recovered_amount_rupees: float
    failed_amount_rupees: float
    before_success_rate: float
    after_success_rate: float
    reason: str


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    """Complete immutable snapshot consumed by the UI."""

    banks: tuple[BankHealthCard, ...]
    chaos: ChaosPanel | None
    ai: AIReasoningPanel
    guardrails: GuardrailPanel | None
    recovery: RecoveryPanel
    overall_status: DashboardStatus


class DashboardBuilder:
    """Convert a RecoveryRun into a dashboard snapshot."""

    def __init__(
        self,
        *,
        ai_model: str | None = None,
    ) -> None:
        self._ai_model = ai_model

    def build(
        self,
        run: RecoveryRun,
    ) -> DashboardSnapshot:
        """Build a presentation-safe snapshot from a recovery run."""

        banks = self._build_bank_cards(run)
        chaos = self._build_chaos_panel(run)
        ai = self._build_ai_panel(run)
        guardrails = self._build_guardrail_panel(run)
        recovery = self._build_recovery_panel(run)

        overall_status = self._calculate_overall_status(
            run=run,
            guardrails=guardrails,
        )

        return DashboardSnapshot(
            banks=banks,
            chaos=chaos,
            ai=ai,
            guardrails=guardrails,
            recovery=recovery,
            overall_status=overall_status,
        )

    def _build_bank_cards(
        self,
        run: RecoveryRun,
    ) -> tuple[BankHealthCard, ...]:
        """Build health cards for all supported banks."""

        if run.bank_health:
            cards: list[BankHealthCard] = []

            for bank in BankName:
                health = run.bank_health.get(bank)

                if health is None:
                    continue

                status: DashboardStatus = (
                    "DEGRADED"
                    if health.anomaly_detected
                    else "HEALTHY"
                )

                cards.append(
                    BankHealthCard(
                        bank=bank,
                        success_rate=health.success_rate,
                        p99_latency_ms=health.p99_latency_ms,
                        total_transactions=health.total_transactions,
                        failed_transactions=health.failed_transactions,
                        status=status,
                    )
                )

            return tuple(cards)

        # Backward-compatible fallback.
        snapshot = run.anomaly_snapshot

        status: DashboardStatus = (
            "DEGRADED"
            if snapshot.anomaly_detected
            else "HEALTHY"
        )

        return (
            BankHealthCard(
                bank=snapshot.bank,
                success_rate=snapshot.success_rate,
                p99_latency_ms=snapshot.p99_latency_ms,
                total_transactions=snapshot.total_transactions,
                failed_transactions=snapshot.failed_transactions,
                status=status,
            ),
        )

    def _build_chaos_panel(
        self,
        run: RecoveryRun,
    ) -> ChaosPanel | None:
        """Build the active chaos panel."""

        event = run.chaos_event

        if event is None:
            scenario = run.scenario
            affected_method = run.anomaly_snapshot.method

            return ChaosPanel(
                scenario=scenario.value,
                bank=run.affected_bank,
                description=self._chaos_description(
                    scenario.value,
                ),
                affected_method=(
                    affected_method.value
                    if affected_method is not None
                    else None
                ),
                injected_latency_ms=(
                    run.anomaly_snapshot.p99_latency_ms
                    if scenario.value == "UPI_LATENCY_SPIKE"
                    else None
                ),
            )

        return ChaosPanel(
            scenario=event.scenario.value,
            bank=event.bank,
            description=event.description,
            affected_method=(
                event.affected_method.value
                if event.affected_method is not None
                else None
            ),
            injected_latency_ms=event.injected_latency_ms,
        )

    def _build_ai_panel(
        self,
        run: RecoveryRun,
    ) -> AIReasoningPanel:
        """Build the AI reasoning panel."""

        diagnosis = run.diagnosis
        action = diagnosis.action

        return AIReasoningPanel(
            source=diagnosis.source,
            model=(
                self._ai_model
                if diagnosis.source == "gemini"
                else None
            ),
            diagnosis=diagnosis.diagnosis,
            confidence=diagnosis.confidence,
            target_bank=(
                self._parse_bank(action.target_bank)
                if action is not None
                else None
            ),
            scope=(
                action.scope
                if action is not None
                else None
            ),
            requested_percentage=(
                action.traffic_percentage
                if action is not None
                else None
            ),
        )

    @staticmethod
    def _build_guardrail_panel(
        run: RecoveryRun,
    ) -> GuardrailPanel | None:
        """Build the guardrail panel."""

        decision = run.guardrail_decision

        if decision is None:
            return None

        return GuardrailPanel(
            status=decision.status,
            approved=decision.approved,
            policy_intervention=decision.policy_intervention,
            requested_percentage=decision.requested_percentage,
            approved_percentage=decision.approved_percentage,
            cooling_period_seconds=decision.cooling_period_seconds,
            reasons=decision.reasons,
        )

    @staticmethod
    def _build_recovery_panel(
        run: RecoveryRun,
    ) -> RecoveryPanel:
        """Build the recovery metrics panel."""

        verification = run.verification
        metrics = run.metrics

        if verification is None:
            return RecoveryPanel(
                recovered=False,
                mttd_seconds=metrics.mttd_seconds,
                mttr_seconds=metrics.mttr_seconds,
                recovered_amount_rupees=0.0,
                failed_amount_rupees=metrics.failed_amount_rupees,
                before_success_rate=run.anomaly_snapshot.success_rate,
                after_success_rate=run.anomaly_snapshot.success_rate,
                reason="Recovery verification was not performed.",
            )

        return RecoveryPanel(
            recovered=verification.recovered,
            mttd_seconds=metrics.mttd_seconds,
            mttr_seconds=metrics.mttr_seconds,
            recovered_amount_rupees=metrics.recovered_amount_rupees,
            failed_amount_rupees=metrics.failed_amount_rupees,
            before_success_rate=verification.before_success_rate,
            after_success_rate=verification.after_success_rate,
            reason=verification.reason,
        )

    @staticmethod
    def _calculate_overall_status(
        *,
        run: RecoveryRun,
        guardrails: GuardrailPanel | None,
    ) -> DashboardStatus:
        """Calculate the high-level dashboard status."""

        if guardrails is not None and not guardrails.approved:
            return "BLOCKED"

        if run.verification is not None:
            if run.verification.recovered:
                return "RECOVERED"

        if run.anomaly_snapshot.anomaly_detected:
            return "DEGRADED"

        return "HEALTHY"

    @staticmethod
    def _parse_bank(
        value: str,
    ) -> BankName | None:
        """Safely convert a bank string into BankName."""

        try:
            return BankName(value.upper())
        except ValueError:
            return None

    @staticmethod
    def _chaos_description(
        scenario: str,
    ) -> str:
        """Return a concise dashboard description."""

        descriptions = {
            "OTP_SILENT_DROP": (
                "OTP completion silently timing out."
            ),
            "UPI_LATENCY_SPIKE": (
                "UPI latency spike crossing gateway timeout."
            ),
            "BIN_ISOLATED_FAILURE": (
                "RuPay issuer failure isolated from other methods."
            ),
            "FLAPPING_GATEWAY": (
                "Gateway alternating between healthy and degraded states."
            ),
        }

        return descriptions.get(
            scenario,
            "Unknown chaos scenario.",
        )


# ---------------------------------------------------------------------------
# Rich terminal UI
# ---------------------------------------------------------------------------


def render_dashboard(
    snapshot: DashboardSnapshot,
    *,
    console: Console | None = None,
) -> None:
    """Render one complete PayInChaos operator dashboard.

    This function is deliberately side-effect free with respect to
    the recovery system. It only writes a visual representation of
    the supplied DashboardSnapshot.
    """

    if console is None:
        console = Console()

    console.print()
    console.print(
        Panel(
            _build_header(snapshot),
            box=box.DOUBLE,
            expand=True,
        )
    )

    top_row = Table(
        padding=(0, 1),
        box=None,
        show_header=False,
        show_edge=False,
        expand=True,
    )

    top_row.add_column(ratio=1)
    top_row.add_column(ratio=1)

    top_row.add_row(
        _build_bank_panel(snapshot.banks),
        _build_chaos_panel(snapshot.chaos),
    )

    console.print(top_row)

    bottom_row = Table(
        expand=True,
        padding=(0, 1),
        box=None,
        show_header=False,
        show_edge=False,
    )

    bottom_row.add_column(ratio=1)
    bottom_row.add_column(ratio=1)

    bottom_row.add_row(
        _build_ai_guardrail_panel(
            snapshot.ai,
            snapshot.guardrails,
        ),
        _build_recovery_panel(snapshot.recovery),
    )

    console.print(bottom_row)
    console.print()


def _build_header(
    snapshot: DashboardSnapshot,
) -> Text:
    """Build the dashboard header."""

    status = snapshot.overall_status

    if status == "RECOVERED":
        status_text = "● RECOVERED"
    elif status == "DEGRADED":
        status_text = "● DEGRADED"
    elif status == "BLOCKED":
        status_text = "● BLOCKED"
    else:
        status_text = "● HEALTHY"

    text = Text()

    text.append(
        "PAYINCHAOS",
        style="bold",
    )

    text.append(
        "  /  AUTONOMOUS SWITCH RESILIENCE",
        style="dim",
    )

    text.append("\n\n")

    text.append(
        "OPERATOR STATUS  ",
        style="bold",
    )

    text.append(
        status_text,
        style=_status_style(status),
    )

    return text


def _build_bank_panel(
    banks: tuple[BankHealthCard, ...],
) -> Panel:
    """Build the four-bank health panel."""

    table = Table(
        expand=True,
        box=None,
        padding=(0, 1),
    )

    table.add_column(
        "BANK",
        style="bold",
    )
    table.add_column(
        "SUCCESS",
        justify="right",
    )
    table.add_column(
        "P99",
        justify="right",
    )
    table.add_column(
        "TX",
        justify="right",
    )
    table.add_column(
        "STATUS",
        justify="center",
    )

    for bank in banks:
        table.add_row(
            bank.bank.value,
            f"{bank.success_rate:.1f}%",
            f"{bank.p99_latency_ms:.0f}ms",
            str(bank.total_transactions),
            Text(
                bank.status,
                style=_status_style(bank.status),
            ),
        )

    return Panel(
        table,
        title="[bold]01  SWITCH HEALTH[/bold]",
        subtitle="30s rolling telemetry",
        box=box.ROUNDED,
        expand=True,
    )


def _build_chaos_panel(
    chaos: ChaosPanel | None,
) -> Panel:
    """Build the active chaos panel."""

    if chaos is None:
        return Panel(
            Text(
                "No active chaos event.",
                style="dim",
            ),
            title="[bold]02  ACTIVE CHAOS[/bold]",
            box=box.ROUNDED,
            expand=True,
        )

    content = Table(
        expand=True,
        box=None,
        show_header=False,
        padding=(0, 1),
    )

    content.add_column(
        style="bold",
        no_wrap=True,
    )
    content.add_column(
        ratio=1,
    )

    content.add_row(
        "SCENARIO",
        chaos.scenario,
    )

    content.add_row(
        "BANK",
        chaos.bank.value,
    )

    content.add_row(
        "METHOD",
        chaos.affected_method or "ALL",
    )

    if chaos.injected_latency_ms is not None:
        content.add_row(
            "INJECTED",
            f"{chaos.injected_latency_ms:.0f}ms",
        )

    content.add_row(
        "DETAIL",
        chaos.description,
    )

    return Panel(
        content,
        title="[bold]02  ACTIVE CHAOS[/bold]",
        subtitle="fault injection",
        box=box.ROUNDED,
        expand=True,
    )


def _build_ai_guardrail_panel(
    ai: AIReasoningPanel,
    guardrails: GuardrailPanel | None,
) -> Panel:
    """Build combined AI reasoning and guardrail panel."""

    blocks: list[Table | Text] = []

    ai_table = Table(
        expand=True,
        box=None,
        show_header=False,
        padding=(0, 1),
    )

    ai_table.add_column(
        style="bold",
        no_wrap=True,
    )
    ai_table.add_column(
        ratio=1,
    )

    source_label = ai.source.upper()

    if ai.model:
        source_label = f"{source_label} / {ai.model}"

    ai_table.add_row(
        "SOURCE",
        source_label,
    )

    ai_table.add_row(
        "CONFIDENCE",
        f"{ai.confidence:.0%}",
    )

    ai_table.add_row(
        "DIAGNOSIS",
        ai.diagnosis,
    )

    if ai.target_bank is not None:
        ai_table.add_row(
            "TARGET",
            ai.target_bank.value,
        )

    if ai.scope is not None:
        ai_table.add_row(
            "SCOPE",
            ai.scope,
        )

    if ai.requested_percentage is not None:
        ai_table.add_row(
            "TRAFFIC",
            f"{ai.requested_percentage}%",
        )

    blocks.append(ai_table)

    if guardrails is not None:
        blocks.append(
            Text("\nGUARDRAILS", style="bold"),
        )

        guard_table = Table(
            expand=True,
            box=None,
            show_header=False,
            padding=(0, 1),
        )

        guard_table.add_column(
            style="bold",
            no_wrap=True,
        )
        guard_table.add_column(
            ratio=1,
        )

        guard_table.add_row(
            "DECISION",
            Text(
                guardrails.status,
                style=(
                    "bold green"
                    if guardrails.approved
                    else "bold red"
                ),
            ),
        )

        if (
            guardrails.requested_percentage is not None
            and guardrails.approved_percentage is not None
        ):
            guard_table.add_row(
                "TRAFFIC",
                (
                    f"{guardrails.requested_percentage}%"
                    f" → "
                    f"{guardrails.approved_percentage}%"
                ),
            )

        if guardrails.cooling_period_seconds is not None:
            guard_table.add_row(
                "COOLDOWN",
                f"{guardrails.cooling_period_seconds}s",
            )

        if guardrails.policy_intervention:
            guard_table.add_row(
                "POLICY",
                Text(
                    "INTERVENTION",
                    style="bold yellow",
                ),
            )

        blocks.append(guard_table)

    return Panel(
        Group(*blocks),
        title="[bold]03  AI + GUARDRAILS[/bold]",
        subtitle="recommend → validate",
        box=box.ROUNDED,
        expand=True,
    )


def _build_recovery_panel(
    recovery: RecoveryPanel,
) -> Panel:
    """Build the recovery performance panel."""

    metrics = Table(
        expand=True,
        box=None,
        show_header=False,
        padding=(0, 1),
    )

    metrics.add_column(
        style="bold",
        no_wrap=True,
    )
    metrics.add_column(
        ratio=1,
        justify="right",
    )

    metrics.add_row(
        "RECOVERY",
        Text(
            "SUCCESS" if recovery.recovered else "FAILED",
            style=(
                "bold green"
                if recovery.recovered
                else "bold red"
            ),
        ),
    )

    metrics.add_row(
        "MTTD",
        _format_seconds(recovery.mttd_seconds),
    )

    metrics.add_row(
        "MTTR",
        _format_seconds(recovery.mttr_seconds),
    )

    metrics.add_row(
        "BEFORE",
        f"{recovery.before_success_rate:.1f}%",
    )

    metrics.add_row(
        "AFTER",
        f"{recovery.after_success_rate:.1f}%",
    )

    metrics.add_row(
        "RECOVERED ₹",
        f"₹{recovery.recovered_amount_rupees:,.2f}",
    )

    metrics.add_row(
        "FAILED ₹",
        f"₹{recovery.failed_amount_rupees:,.2f}",
    )

    return Panel(
        Group(
            metrics,
            Text(
                f"\n{recovery.reason}",
                style="dim",
            ),
        ),
        title="[bold]04  RECOVERY[/bold]",
        subtitle="measured outcome",
        box=box.ROUNDED,
        expand=True,
    )


def _format_seconds(
    value: float | None,
) -> str:
    """Format an optional duration."""

    if value is None:
        return "—"

    if value.is_integer():
        return f"{int(value)}s"

    return f"{value:.1f}s"


def _status_style(
    status: str,
) -> str:
    """Return Rich styling for a dashboard status."""

    styles = {
        "HEALTHY": "bold green",
        "DEGRADED": "bold yellow",
        "RECOVERED": "bold green",
        "BLOCKED": "bold red",
        "FAILED": "bold red",
    }

    return styles.get(
        status,
        "bold",
    )