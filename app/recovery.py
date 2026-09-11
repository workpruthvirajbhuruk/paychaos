"""Autonomous recovery orchestration for PayInChaos.

Architecture:
    PaymentSwitch
          ↓
    ChaosEngine
          ↓
      Telemetry
          ↓
       AI Agent
          ↓
      Guardrails
          ↓
        Router
          ↓
      Verification

Architectural rule:
    AI recommends.
    Guardrails authorize.
    Router executes.
    Telemetry verifies.

The controller contains orchestration only.
It does not contain AI decision logic or routing policy.

Gemini can be disabled so the complete recovery pipeline can
be validated without an external LLM dependency.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from app.agent import AIAgent, DiagnosisResult
from app.chaos_engine import (
    ChaosEngine,
    ChaosEvent,
    ChaosScenario,
)
from app.config import DEFAULT_SETTINGS, Settings
from app.guardrails import (
    GuardrailDecision,
    GuardrailEngine,
)
from app.router import (
    RoutingDecision,
    RoutingRule,
    TrafficRouter,
)
from app.switch import (
    BankName,
    PaymentMethod,
    PaymentSwitch,
    Transaction,
    TransactionResult,
)
from app.telemetry import (
    BankHealth,
    Telemetry,
    TelemetrySnapshot,
)


@dataclass(frozen=True, slots=True)
class RecoveryMetrics:
    """Measured recovery performance."""

    mttd_seconds: float | None
    mttr_seconds: float | None
    failed_amount_paise: int
    recovered_amount_paise: int

    @property
    def failed_amount_rupees(self) -> float:
        return round(
            self.failed_amount_paise / 100.0,
            2,
        )

    @property
    def recovered_amount_rupees(self) -> float:
        return round(
            self.recovered_amount_paise / 100.0,
            2,
        )


@dataclass(frozen=True, slots=True)
class RecoveryVerification:
    """Post-intervention recovery evidence."""

    recovered: bool

    before_success_rate: float
    after_success_rate: float

    before_p99_latency_ms: float
    after_p99_latency_ms: float

    successful_transactions: int
    failed_transactions: int

    attempted_recovery_amount_paise: int
    recovered_amount_paise: int

    # Routing-specific verification.
    rerouted_transactions: int
    successful_rerouted_transactions: int
    rerouted_success_rate: float

    reason: str


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Immutable control-plane audit record for one recovery run."""

    sequence: int
    actor: str
    event_type: str
    timestamp_seconds: float
    details: str


@dataclass(frozen=True, slots=True)
class RecoveryRun:
    """Complete result of one autonomous recovery cycle."""

    scenario: ChaosScenario
    affected_bank: BankName

    anomaly_snapshot: TelemetrySnapshot
    diagnosis: DiagnosisResult

    guardrail_decision: GuardrailDecision | None
    routing_rule: RoutingRule | None

    verification: RecoveryVerification | None
    metrics: RecoveryMetrics

    # Dashboard-facing observability.
    #
    # These fields expose information that already exists inside
    # the recovery pipeline without allowing the dashboard to
    # make or modify operational decisions.
    chaos_event: ChaosEvent | None = None
    bank_health: dict[BankName, BankHealth] = field(
        default_factory=dict
    )

    # Explicit terminal state for operators and the dashboard.
    outcome: str = "RECOVERED"
    escalation_required: bool = False
    autonomous_routing_stopped: bool = False
    audit_trail: tuple[AuditEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class _RecoveryResult:
    """Internal result containing routing information."""

    result: TransactionResult
    routing: RoutingDecision


class RecoveryController:
    """Coordinate the complete autonomous recovery pipeline."""

    def __init__(
        self,
        *,
        switch: PaymentSwitch | None = None,
        telemetry: Telemetry | None = None,
        chaos: ChaosEngine | None = None,
        agent: AIAgent | None = None,
        guardrails: GuardrailEngine | None = None,
        router: TrafficRouter | None = None,
        settings: Settings = DEFAULT_SETTINGS,
        clock: Callable[[], float] = time.monotonic,
        use_gemini: bool = True,
    ) -> None:
        self.settings = settings
        self.clock = clock

        self.switch = switch or PaymentSwitch(
            clock=clock,
            timeout_threshold_ms=(
                settings.payment_timeout_threshold_ms
            ),
        )

        self.telemetry = telemetry or Telemetry(
            settings=settings
        )

        self.chaos = chaos or ChaosEngine(
            self.switch
        )

        self.agent = agent or AIAgent(
            settings=settings,
            telemetry=self.telemetry,
            use_gemini=use_gemini,
        )

        self.guardrails = guardrails or GuardrailEngine(
            settings=settings
        )

        self.router = router or TrafficRouter()

    def process_transaction(
        self,
        *,
        amount_paise: int,
        method: PaymentMethod,
        bank: BankName,
    ) -> tuple[
        Transaction,
        TransactionResult,
        RoutingDecision,
    ]:
        """Create, route, process, and record one transaction."""

        transaction = self.switch.create_transaction(
            amount_paise=amount_paise,
            method=method,
            bank=bank,
        )

        routed_transaction, routing_decision = (
            self.router.route(transaction)
        )

        result = self.switch.process(
            routed_transaction
        )

        self.telemetry.record(
            result
        )

        return (
            routed_transaction,
            result,
            routing_decision,
        )

    def observe(
        self,
        *,
        bank: BankName,
        method: PaymentMethod | None = None,
    ) -> TelemetrySnapshot:
        """Observe current bank health."""

        return self.telemetry.snapshot(
            bank=bank,
            method=method,
            now=self.clock(),
        )

    def diagnose(
        self,
        *,
        bank: BankName,
        method: PaymentMethod | None = None,
    ) -> DiagnosisResult:
        """Observe and diagnose a bank anomaly."""

        snapshot = self.observe(
            bank=bank,
            method=method,
        )

        healthy_banks = self.telemetry.healthy_banks(
            now=self.clock(),
            exclude={bank},
        )

        return self.agent.diagnose(
            snapshot,
            available_banks=sorted(
                healthy_banks,
                key=lambda item: item.value,
            ),
        )

    def authorize(
        self,
        diagnosis: DiagnosisResult,
    ) -> GuardrailDecision:
        """Ask deterministic guardrails to authorize AI output."""

        if diagnosis.action is None:
            raise ValueError(
                "Diagnosis does not contain a recovery action."
            )

        isolated_bank = self._parse_bank(
            diagnosis.action.isolated_bank
        )

        if isolated_bank is None:
            raise ValueError(
                "Diagnosis contains an unknown isolated bank."
            )

        healthy_banks = self.telemetry.healthy_banks(
            now=self.clock(),
            exclude={isolated_bank},
        )

        return self.guardrails.evaluate(
            diagnosis.action,
            now=self.clock(),
            healthy_banks=healthy_banks,
        )

    def execute(
        self,
        decision: GuardrailDecision,
    ) -> RoutingRule:
        """Install an approved routing rule."""

        return self.router.apply_guardrail_decision(
            decision,
            now=self.clock(),
        )

    def run_recovery_cycle(
        self,
        *,
        scenario: ChaosScenario,
        transactions_before_recovery: list[
            tuple[int, PaymentMethod, BankName]
        ],
        transactions_after_recovery: list[
            tuple[int, PaymentMethod, BankName]
        ],
        detection_delay_seconds: float = 5.0,
        diagnosis_delay_seconds: float = 2.0,
        execution_delay_seconds: float = 2.0,
        verification_delay_seconds: float = 3.0,
    ) -> RecoveryRun:
        """Run one complete autonomous recovery cycle."""

        self.telemetry.clear()
        self.router.clear_rules()
        self.guardrails.clear_cooldown()
        self.chaos.clear()

        self.chaos.inject(
            scenario
        )

        scenario_event = self.chaos.active_event

        if scenario_event is None:
            raise RuntimeError(
                "Chaos scenario failed to become active."
            )

        affected_bank = scenario_event.bank
        failure_start = self.clock()

        audit: list[AuditEvent] = []

        def record_audit(actor: str, event_type: str, details: str) -> None:
            audit.append(
                AuditEvent(
                    sequence=len(audit) + 1,
                    actor=actor,
                    event_type=event_type,
                    timestamp_seconds=round(self.clock(), 3),
                    details=details,
                )
            )

        record_audit(
            "CHAOS_ENGINE",
            "CHAOS_INJECTED",
            f"{scenario.value} injected on {affected_bank.value}.",
        )

        before_results: list[TransactionResult] = []

        for amount, method, bank in (
            transactions_before_recovery
        ):
            _, result, _ = self.process_transaction(
                amount_paise=amount,
                method=method,
                bank=bank,
            )
            before_results.append(result)

        self._advance_time(
            detection_delay_seconds
        )

        anomaly_snapshot = self.observe(
            bank=affected_bank
        )

        record_audit(
            "TELEMETRY",
            "ANOMALY_DETECTED",
            (
                f"{affected_bank.value} detected at "
                f"{anomaly_snapshot.success_rate:.1f}% success rate and "
                f"{anomaly_snapshot.p99_latency_ms:.1f}ms P99 latency."
            ),
        )

        detection_time = self.clock()

        mttd = max(
            0.0,
            detection_time - failure_start,
        )

        affected_method = scenario_event.affected_method

        diagnosis_snapshot = self.telemetry.snapshot(
            bank=affected_bank,
            method=affected_method,
            now=self.clock(),
        )

        self._advance_time(
            diagnosis_delay_seconds,
            tick_chaos=False,
        )

        healthy_banks = self.telemetry.healthy_banks(
            now=self.clock(),
            exclude={affected_bank},
        )

        diagnosis = self.agent.diagnose(
            diagnosis_snapshot,
            available_banks=sorted(
                healthy_banks,
                key=lambda item: item.value,
            ),
        )

        record_audit(
            "AI_AGENT",
            "AI_DIAGNOSED",
            getattr(diagnosis, "diagnosis", None)
            or "AI diagnosis completed.",
        )

        guardrail_decision: GuardrailDecision | None = None
        routing_rule: RoutingRule | None = None

        if diagnosis.action is not None:
            guardrail_decision = self.authorize(
                diagnosis
            )

            record_audit(
                "GUARDRAILS",
                (
                    "GUARDRAIL_APPROVED"
                    if guardrail_decision.approved
                    else "GUARDRAIL_REJECTED"
                ),
                getattr(guardrail_decision, "status", "Decision recorded."),
            )

            if guardrail_decision.approved:
                self._advance_time(
                    execution_delay_seconds,
                    tick_chaos=(
                        scenario is not ChaosScenario.CASCADING_SWITCH_FAILURE
                    ),
                )

                routing_rule = self.execute(
                    guardrail_decision
                )
                record_audit(
                    "ROUTER",
                    "TRAFFIC_REROUTED",
                    (
                        f"{routing_rule.isolated_bank.value} -> "
                        f"{routing_rule.target_bank.value}, "
                        f"{routing_rule.traffic_percentage:.0f}% traffic, "
                        f"{routing_rule.scope}."
                    ),
                )

        # Cascading failure safety boundary. The primary failure is SBI,
        # while AXIS is the AI-selected recovery target. The cascade trigger
        # is measured from scenario start, so evaluate it at the current
        # simulated time immediately after the route is installed.
        if (
            scenario is ChaosScenario.CASCADING_SWITCH_FAILURE
            and routing_rule is not None
        ):
            self.chaos.tick(self.clock())
            scenario_event = self.chaos.active_event or scenario_event

            secondary_bank = routing_rule.target_bank
            secondary_snapshot = self.observe(
                bank=secondary_bank,
                method=affected_method,
            )
            # The chaos engine is the authoritative source for whether the
            # injected secondary failure has actually activated. Do not require
            # a telemetry sample from AXIS here: the verification sample has
            # not run yet, so AXIS may legitimately have zero observations.
            secondary_active = (
                self.chaos.cascade_triggered
                or getattr(
                    scenario_event,
                    "secondary_failure_active",
                    False,
                )
            )

            if secondary_active:
                record_audit(
                    "TELEMETRY",
                    "TARGET_DEGRADED",
                    (
                        f"Recovery target {secondary_bank.value} became degraded "
                        f"after the configured cascade trigger at "
                        f"t={self.clock():.1f}s. "
                        f"Current observed sample: "
                        f"{secondary_snapshot.success_rate:.1f}% success rate, "
                        f"{secondary_snapshot.p99_latency_ms:.1f}ms P99."
                    ),
                )

                # Safety boundary: remove the active route before any further
                # transaction can be sent into the degraded target.
                self.router.clear_rules()
                record_audit(
                    "RECOVERY_CONTROLLER",
                    "RECOVERY_ABORTED",
                    (
                        f"Autonomous recovery stopped because target "
                        f"{secondary_bank.value} became unhealthy."
                    ),
                )
                record_audit(
                    "RECOVERY_CONTROLLER",
                    "OPERATOR_ESCALATION",
                    (
                        "Recovery target failed during intervention; "
                        "manual operator action is required."
                    ),
                )

                failed_amount_paise = sum(
                    result.amount_paise
                    for result in before_results
                    if not result.success
                )
                verification = self._build_escalation_verification(
                    before=diagnosis_snapshot,
                    reason=(
                        f"Autonomous recovery stopped: target {secondary_bank.value} "
                        "degraded during recovery; operator escalation required."
                    ),
                )
                metrics = RecoveryMetrics(
                    mttd_seconds=round(mttd, 3),
                    mttr_seconds=None,
                    failed_amount_paise=failed_amount_paise,
                    recovered_amount_paise=0,
                )

                return RecoveryRun(
                    scenario=scenario,
                    affected_bank=affected_bank,
                    anomaly_snapshot=anomaly_snapshot,
                    diagnosis=diagnosis,
                    guardrail_decision=guardrail_decision,
                    routing_rule=routing_rule,
                    verification=verification,
                    metrics=metrics,
                    chaos_event=scenario_event,
                    bank_health=self.telemetry.all_bank_health(
                        now=self.clock()
                    ),
                    outcome="ESCALATED",
                    escalation_required=True,
                    autonomous_routing_stopped=True,
                    audit_trail=tuple(audit),
                )

        recovery_results: list[_RecoveryResult] = []

        for amount, method, bank in (
            transactions_after_recovery
        ):
            _, result, routing_decision = (
                self.process_transaction(
                    amount_paise=amount,
                    method=method,
                    bank=bank,
                )
            )

            recovery_results.append(
                _RecoveryResult(
                    result=result,
                    routing=routing_decision,
                )
            )

        self._advance_time(
            verification_delay_seconds
        )

        verification = self._verify_recovery(
            affected_bank=affected_bank,
            affected_method=affected_method,
            before=diagnosis_snapshot,
            recovery_results=recovery_results,
            routing_rule=routing_rule,
        )

        record_audit(
            "TELEMETRY",
            "RECOVERY_VERIFIED" if verification.recovered else "RECOVERY_FAILED",
            verification.reason,
        )

        recovery_end = self.clock()

        mttr = (
            recovery_end - failure_start
            if verification.recovered
            else None
        )

        # Measure the amount attached to transactions that actually failed
        # during the pre-recovery window. This is intentionally different
        # from total attempted amount: a successful baseline transaction
        # must not be reported as lost revenue.
        failed_amount_paise = sum(
            result.amount_paise
            for result in before_results
            if not result.success
        )

        metrics = RecoveryMetrics(
            mttd_seconds=round(
                mttd,
                3,
            ),
            mttr_seconds=(
                round(
                    mttr,
                    3,
                )
                if mttr is not None
                else None
            ),
            failed_amount_paise=(
                failed_amount_paise
            ),
            recovered_amount_paise=(
                verification.recovered_amount_paise
                if verification.recovered
                else 0
            ),
        )

        # Capture the complete health picture after recovery.
        #
        # This is read-only dashboard evidence. It does not influence
        # the recovery decision that has already been executed.
        bank_health = self.telemetry.all_bank_health(
            now=self.clock()
        )

        return RecoveryRun(
            scenario=scenario,
            affected_bank=affected_bank,
            anomaly_snapshot=anomaly_snapshot,
            diagnosis=diagnosis,
            guardrail_decision=guardrail_decision,
            routing_rule=routing_rule,
            verification=verification,
            metrics=metrics,
            chaos_event=scenario_event,
            bank_health=bank_health,
            outcome="RECOVERED" if verification.recovered else "FAILED",
            escalation_required=False,
            autonomous_routing_stopped=False,
            audit_trail=tuple(audit),
        )

    def _build_escalation_verification(
        self,
        *,
        before: TelemetrySnapshot,
        reason: str,
    ) -> RecoveryVerification:
        """Build explicit negative evidence for a safety escalation."""

        return RecoveryVerification(
            recovered=False,
            before_success_rate=before.success_rate,
            after_success_rate=before.success_rate,
            before_p99_latency_ms=before.p99_latency_ms,
            after_p99_latency_ms=before.p99_latency_ms,
            successful_transactions=0,
            failed_transactions=0,
            attempted_recovery_amount_paise=0,
            recovered_amount_paise=0,
            rerouted_transactions=0,
            successful_rerouted_transactions=0,
            rerouted_success_rate=0.0,
            reason=reason,
        )

    def _verify_recovery(
        self,
        *,
        affected_bank: BankName,
        affected_method: PaymentMethod | None,
        before: TelemetrySnapshot,
        recovery_results: list[_RecoveryResult],
        routing_rule: RoutingRule | None,
    ) -> RecoveryVerification:
        """Verify recovery using actual routed transactions.

        Recovery is considered successful only when the approved
        routing rule actually sends traffic to the target bank and
        that rerouted traffic achieves the healthy success threshold.

        This avoids falsely claiming recovery merely because the
        overall post-recovery batch happened to contain successful
        transactions.
        """

        if not recovery_results:
            return RecoveryVerification(
                recovered=False,
                before_success_rate=before.success_rate,
                after_success_rate=before.success_rate,
                before_p99_latency_ms=before.p99_latency_ms,
                after_p99_latency_ms=before.p99_latency_ms,
                successful_transactions=0,
                failed_transactions=0,
                attempted_recovery_amount_paise=0,
                recovered_amount_paise=0,
                rerouted_transactions=0,
                successful_rerouted_transactions=0,
                rerouted_success_rate=0.0,
                reason=(
                    "No post-recovery transactions "
                    "were processed."
                ),
            )

        results = [
            item.result
            for item in recovery_results
        ]

        attempted_amount = sum(
            result.amount_paise
            for result in results
        )

        successful_count = sum(
            1
            for result in results
            if result.success
        )

        failed_count = (
            len(results)
            - successful_count
        )

        successful_amount = sum(
            result.amount_paise
            for result in results
            if result.success
        )

        rerouted_items = [
            item
            for item in recovery_results
            if item.routing.rerouted
        ]

        rerouted_results = [
            item.result
            for item in rerouted_items
        ]

        rerouted_count = len(
            rerouted_results
        )

        successful_rerouted_results = [
            result
            for result in rerouted_results
            if result.success
        ]

        successful_rerouted_count = len(
            successful_rerouted_results
        )

        rerouted_success_rate = (
            (
                successful_rerouted_count
                / rerouted_count
            )
            * 100.0
            if rerouted_count > 0
            else 0.0
        )

        after_success_rate = (
            successful_count
            / len(results)
        ) * 100.0

        after_p99 = max(
            result.latency_ms
            for result in results
        )

        # ---------------------------------------------------------
        # Primary verification path:
        # approved route must actually carry traffic.
        # ---------------------------------------------------------

        if routing_rule is not None:
            target_results = [
                result
                for result in rerouted_results
                if result.bank is routing_rule.target_bank
                and (
                    affected_method is None
                    or result.method is affected_method
                )
            ]

            target_successes = [
                result
                for result in target_results
                if result.success
            ]

            target_success_rate = (
                (
                    len(target_successes)
                    / len(target_results)
                )
                * 100.0
                if target_results
                else 0.0
            )

            if target_results:
                recovered = (
                    target_success_rate >= 85.0
                    and len(target_successes) > 0
                )

                if recovered:
                    recovered_amount = sum(
                        result.amount_paise
                        for result in target_successes
                    )

                    reason = (
                        f"Recovery traffic reached "
                        f"{routing_rule.target_bank.value}: "
                        f"{len(target_results)} transaction(s) "
                        f"were rerouted and achieved "
                        f"{target_success_rate:.1f}% "
                        f"success rate."
                    )

                    return RecoveryVerification(
                        recovered=True,
                        before_success_rate=(
                            before.success_rate
                        ),
                        after_success_rate=(
                            target_success_rate
                        ),
                        before_p99_latency_ms=(
                            before.p99_latency_ms
                        ),
                        after_p99_latency_ms=max(
                            result.latency_ms
                            for result in target_results
                        ),
                        successful_transactions=(
                            successful_count
                        ),
                        failed_transactions=(
                            failed_count
                        ),
                        attempted_recovery_amount_paise=(
                            attempted_amount
                        ),
                        recovered_amount_paise=(
                            recovered_amount
                        ),
                        rerouted_transactions=(
                            rerouted_count
                        ),
                        successful_rerouted_transactions=(
                            successful_rerouted_count
                        ),
                        rerouted_success_rate=(
                            rerouted_success_rate
                        ),
                        reason=reason,
                    )

                reason = (
                    f"Traffic reached "
                    f"{routing_rule.target_bank.value}, "
                    f"but rerouted traffic achieved only "
                    f"{target_success_rate:.1f}% success rate."
                )

                return RecoveryVerification(
                    recovered=False,
                    before_success_rate=(
                        before.success_rate
                    ),
                    after_success_rate=(
                        target_success_rate
                    ),
                    before_p99_latency_ms=(
                        before.p99_latency_ms
                    ),
                    after_p99_latency_ms=max(
                        result.latency_ms
                        for result in target_results
                    ),
                    successful_transactions=(
                        successful_count
                    ),
                    failed_transactions=(
                        failed_count
                    ),
                    attempted_recovery_amount_paise=(
                        attempted_amount
                    ),
                    recovered_amount_paise=0,
                    rerouted_transactions=(
                        rerouted_count
                    ),
                    successful_rerouted_transactions=(
                        successful_rerouted_count
                    ),
                    rerouted_success_rate=(
                        rerouted_success_rate
                    ),
                    reason=reason,
                )

            # A routing rule exists, but the sample did not contain
            # any traffic selected by the percentage rule.
            return RecoveryVerification(
                recovered=False,
                before_success_rate=(
                    before.success_rate
                ),
                after_success_rate=(
                    after_success_rate
                ),
                before_p99_latency_ms=(
                    before.p99_latency_ms
                ),
                after_p99_latency_ms=after_p99,
                successful_transactions=(
                    successful_count
                ),
                failed_transactions=(
                    failed_count
                ),
                attempted_recovery_amount_paise=(
                    attempted_amount
                ),
                recovered_amount_paise=0,
                rerouted_transactions=(
                    rerouted_count
                ),
                successful_rerouted_transactions=(
                    successful_rerouted_count
                ),
                rerouted_success_rate=(
                    rerouted_success_rate
                ),
                reason=(
                    "An approved routing rule was installed, "
                    "but the post-recovery sample contained "
                    "no transactions selected for rerouting. "
                    "Increase the verification sample size."
                ),
            )

        # ---------------------------------------------------------
        # No routing rule.
        # ---------------------------------------------------------

        recovered = (
            successful_count > 0
            and after_success_rate >= 85.0
        )

        if recovered:
            reason = (
                "Post-intervention traffic recovered "
                "above the healthy threshold."
            )
        else:
            reason = (
                "Post-intervention traffic remains degraded."
            )

        return RecoveryVerification(
            recovered=recovered,
            before_success_rate=(
                before.success_rate
            ),
            after_success_rate=(
                after_success_rate
            ),
            before_p99_latency_ms=(
                before.p99_latency_ms
            ),
            after_p99_latency_ms=after_p99,
            successful_transactions=(
                successful_count
            ),
            failed_transactions=(
                failed_count
            ),
            attempted_recovery_amount_paise=(
                attempted_amount
            ),
            recovered_amount_paise=(
                successful_amount
                if recovered
                else 0
            ),
            rerouted_transactions=(
                rerouted_count
            ),
            successful_rerouted_transactions=(
                successful_rerouted_count
            ),
            rerouted_success_rate=(
                rerouted_success_rate
            ),
            reason=reason,
        )

    def _advance_time(
        self,
        seconds: float,
        *,
        tick_chaos: bool = True,
    ) -> None:
        """Advance the simulation clock and optionally advance chaos."""

        if seconds <= 0:
            return

        advance = getattr(
            self.clock,
            "advance",
            None,
        )

        if advance is None:
            return

        advance(seconds)

        if tick_chaos:
            self.chaos.tick(
                self.clock()
            )

    @staticmethod
    def _parse_bank(
        value: str,
    ) -> BankName | None:
        try:
            return BankName(
                value.upper()
            )
        except ValueError:
            return None
