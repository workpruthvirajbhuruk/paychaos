
"""PayInChaos autonomous recovery benchmark.

Runs 1,000 synthetic transactions across four chaos scenarios.

Modes:
    python evals/run_benchmark.py --gemini
    python evals/run_benchmark.py --no-gemini

The benchmark uses deterministic switch seeds and deterministic
transaction IDs so Gemini and fallback runs use the same simulated
transaction workload.

Results are written separately:
    benchmark_results_gemini.json
    benchmark_results_fallback.json

IMPORTANT:
    --gemini is a strict Gemini benchmark.

    If Gemini is unavailable, exhausted, rejected, or throws an
    error during diagnosis, the benchmark FAILS rather than silently
    converting the run into a deterministic fallback benchmark.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.chaos_engine import ChaosScenario
from app.recovery import (
    RecoveryController,
    RecoveryMetrics,
    RecoveryRun,
)
from app.router import RoutingDecision
from app.switch import (
    BankName,
    PaymentMethod,
    PaymentSwitch,
    TransactionResult,
)


BENCHMARK_SEED = 20260911


class FakeClock:
    """Deterministic benchmark clock."""

    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    """Configuration for one benchmark scenario."""

    scenario: ChaosScenario
    bank: BankName
    method: PaymentMethod
    amount_paise: int
    before_count: int = 125
    after_count: int = 125
    initial_elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class BenchmarkRecoveryResult:
    """Transaction result plus the routing decision that produced it."""

    result: TransactionResult
    routing: RoutingDecision


SCENARIOS = (
    BenchmarkScenario(
        scenario=ChaosScenario.OTP_SILENT_DROP,
        bank=BankName.HDFC,
        method=PaymentMethod.UPI,
        amount_paise=10000,
    ),
    BenchmarkScenario(
        scenario=ChaosScenario.UPI_LATENCY_SPIKE,
        bank=BankName.SBI,
        method=PaymentMethod.UPI,
        amount_paise=10000,
    ),
    BenchmarkScenario(
        scenario=ChaosScenario.BIN_ISOLATED_FAILURE,
        bank=BankName.AXIS,
        method=PaymentMethod.CARD_RUPAY,
        amount_paise=10000,
    ),
    BenchmarkScenario(
        scenario=ChaosScenario.FLAPPING_GATEWAY,
        bank=BankName.ICICI,
        method=PaymentMethod.UPI,
        amount_paise=10000,
        initial_elapsed_seconds=15.0,
    ),
)


def build_transactions(
    *,
    bank: BankName,
    method: PaymentMethod,
    amount_paise: int,
    count: int,
) -> list[tuple[int, PaymentMethod, BankName]]:
    """Build synthetic transactions."""

    return [
        (
            amount_paise,
            method,
            bank,
        )
        for _ in range(count)
    ]


def build_switch(
    *,
    scenario_index: int,
) -> PaymentSwitch:
    """Create a deterministic switch for one benchmark scenario."""

    return PaymentSwitch(
        seed=BENCHMARK_SEED + scenario_index,
        transaction_id_prefix=(
            f"benchmark_{BENCHMARK_SEED}_{scenario_index}"
        ),
    )


def run_scenario(
    config: BenchmarkScenario,
    *,
    use_gemini: bool,
    scenario_index: int,
) -> RecoveryRun:
    """Execute one benchmark scenario."""

    clock = FakeClock()

    controller = RecoveryController(
        clock=clock,
        switch=build_switch(
            scenario_index=scenario_index,
        ),
        use_gemini=use_gemini,
    )

    before = build_transactions(
        bank=config.bank,
        method=config.method,
        amount_paise=config.amount_paise,
        count=config.before_count,
    )

    after = build_transactions(
        bank=config.bank,
        method=config.method,
        amount_paise=config.amount_paise,
        count=config.after_count,
    )

    if config.scenario is ChaosScenario.FLAPPING_GATEWAY:
        run = run_flapping_scenario(
            controller=controller,
            clock=clock,
            config=config,
            before=before,
            after=after,
        )
    else:
        run = controller.run_recovery_cycle(
            scenario=config.scenario,
            transactions_before_recovery=before,
            transactions_after_recovery=after,
            detection_delay_seconds=5.0,
            diagnosis_delay_seconds=2.0,
            execution_delay_seconds=2.0,
            verification_delay_seconds=3.0,
        )

    # A Gemini benchmark must contain an actual Gemini diagnosis.
    # Never allow quota exhaustion or another Gemini error to be
    # silently represented as a successful "Gemini" benchmark.
    if use_gemini and run.diagnosis.source != "gemini":
        error_detail = controller.agent.last_gemini_error

        detail = (
            f" Gemini error: {error_detail}"
            if error_detail
            else ""
        )

        raise RuntimeError(
            f"Strict Gemini benchmark failed for "
            f"{config.scenario.value}: "
            f"diagnosis source was "
            f"{run.diagnosis.source!r}, not 'gemini'."
            f"{detail}"
        )

    return run


def run_flapping_scenario(
    *,
    controller: RecoveryController,
    clock: FakeClock,
    config: BenchmarkScenario,
    before: list[tuple[int, PaymentMethod, BankName]],
    after: list[tuple[int, PaymentMethod, BankName]],
) -> RecoveryRun:
    """Run flapping while preserving its degraded phase."""

    controller.chaos.inject(
        config.scenario
    )

    clock.advance(
        config.initial_elapsed_seconds
    )

    controller.chaos.tick(
        clock()
    )

    controller.telemetry.clear()
    controller.router.clear_rules()
    controller.guardrails.clear_cooldown()

    failure_start = clock()

    for amount, method, bank in before:
        controller.process_transaction(
            amount_paise=amount,
            method=method,
            bank=bank,
        )

    clock.advance(5.0)
    controller.chaos.tick(
        clock()
    )

    anomaly_snapshot = controller.observe(
        bank=config.bank,
    )

    detection_time = clock()

    mttd = max(
        0.0,
        detection_time - failure_start,
    )

    diagnosis_snapshot = controller.telemetry.snapshot(
        bank=config.bank,
        method=config.method,
        now=clock(),
    )

    clock.advance(2.0)
    controller.chaos.tick(
        clock()
    )

    healthy_banks = controller.telemetry.healthy_banks(
        now=clock(),
        exclude={config.bank},
    )

    diagnosis = controller.agent.diagnose(
        diagnosis_snapshot,
        available_banks=sorted(
            healthy_banks,
            key=lambda bank: bank.value,
        ),
    )

    guardrail_decision = None
    routing_rule = None

    if diagnosis.action is not None:
        guardrail_decision = controller.authorize(
            diagnosis,
        )

        if guardrail_decision.approved:
            clock.advance(2.0)

            controller.chaos.tick(
                clock()
            )

            routing_rule = controller.execute(
                guardrail_decision,
            )

    recovery_results: list[
        BenchmarkRecoveryResult
    ] = []

    for amount, method, bank in after:
        _, result, routing_decision = (
            controller.process_transaction(
                amount_paise=amount,
                method=method,
                bank=bank,
            )
        )

        recovery_results.append(
            BenchmarkRecoveryResult(
                result=result,
                routing=routing_decision,
            )
        )

    clock.advance(3.0)

    controller.chaos.tick(
        clock()
    )

    verification = controller._verify_recovery(
        affected_bank=config.bank,
        affected_method=config.method,
        before=diagnosis_snapshot,
        recovery_results=recovery_results,
        routing_rule=routing_rule,
    )

    recovery_end = clock()

    mttr = (
        recovery_end - failure_start
        if verification.recovered
        else None
    )

    failed_amount_paise = sum(
        amount
        for amount, _, _ in before
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

    return RecoveryRun(
        scenario=config.scenario,
        affected_bank=config.bank,
        anomaly_snapshot=anomaly_snapshot,
        diagnosis=diagnosis,
        guardrail_decision=guardrail_decision,
        routing_rule=routing_rule,
        verification=verification,
        metrics=metrics,
    )


def format_money(
    paise: int,
) -> str:
    """Format paise as Indian rupees."""

    return f"₹{paise / 100:,.2f}"


def print_run(
    config: BenchmarkScenario,
    run: RecoveryRun,
) -> None:
    """Print detailed results."""

    print()
    print("=" * 80)
    print(config.scenario.value)
    print("=" * 80)

    print(
        "Affected bank:",
        run.affected_bank.value,
    )

    print(
        "Initial SR:",
        run.anomaly_snapshot.success_rate,
        "%",
    )

    print(
        "Initial P99:",
        run.anomaly_snapshot.p99_latency_ms,
        "ms",
    )

    print(
        "AI source:",
        run.diagnosis.source,
    )

    print(
        "AI diagnosis:",
        run.diagnosis.diagnosis,
    )

    if run.diagnosis.action:
        print(
            "AI recommendation:",
            run.diagnosis.action.isolated_bank,
            "->",
            run.diagnosis.action.target_bank,
            "|",
            run.diagnosis.action.scope,
            "|",
            f"{run.diagnosis.action.traffic_percentage}%",
        )

    if run.guardrail_decision:
        print(
            "Guardrail:",
            run.guardrail_decision.status,
        )

        print(
            "Guardrail intervention:",
            run.guardrail_decision.policy_intervention,
        )

    if run.routing_rule:
        print(
            "Executed route:",
            run.routing_rule.isolated_bank.value,
            "->",
            run.routing_rule.target_bank.value,
        )

        print(
            "Actual traffic:",
            f"{run.routing_rule.traffic_percentage}%",
        )

    if run.verification:
        print(
            "Recovered:",
            run.verification.recovered,
        )

        print(
            "Recovery success rate:",
            f"{run.verification.after_success_rate:.1f}%",
        )

        print(
            "Rerouted transactions:",
            run.verification.rerouted_transactions,
        )

        print(
            "Successful reroutes:",
            run.verification.successful_rerouted_transactions,
        )

        print(
            "Rerouted success rate:",
            f"{run.verification.rerouted_success_rate:.1f}%",
        )

        print(
            "Recovered:",
            format_money(
                run.verification.recovered_amount_paise,
            ),
        )

    print(
        "MTTD:",
        run.metrics.mttd_seconds,
        "seconds",
    )

    print(
        "MTTR:",
        (
            f"{run.metrics.mttr_seconds} seconds"
            if run.metrics.mttr_seconds is not None
            else "N/A"
        ),
    )


def build_result_payload(
    *,
    mode: str,
    runs: list[RecoveryRun],
) -> dict[str, object]:
    """Build machine-readable benchmark evidence."""

    scenario_results: list[dict[str, object]] = []

    for run in runs:
        intervention = (
            run.guardrail_decision is not None
            and run.guardrail_decision.policy_intervention
        )

        verification = run.verification

        scenario_results.append(
            {
                "scenario": run.scenario.value,
                "affected_bank": run.affected_bank.value,
                "ai_source": run.diagnosis.source,
                "diagnosis": run.diagnosis.diagnosis,
                "mttd_seconds": run.metrics.mttd_seconds,
                "mttr_seconds": run.metrics.mttr_seconds,
                "target_bank": (
                    run.routing_rule.target_bank.value
                    if run.routing_rule
                    else None
                ),
                "scope": (
                    run.routing_rule.scope
                    if run.routing_rule
                    else None
                ),
                "traffic_percentage": (
                    run.routing_rule.traffic_percentage
                    if run.routing_rule
                    else None
                ),
                "recovered": (
                    verification.recovered
                    if verification
                    else False
                ),
                "recovered_amount_paise": (
                    run.metrics.recovered_amount_paise
                ),
                "recovered_amount_rupees": (
                    run.metrics.recovered_amount_rupees
                ),
                "rerouted_transactions": (
                    verification.rerouted_transactions
                    if verification
                    else 0
                ),
                "successful_rerouted_transactions": (
                    verification.successful_rerouted_transactions
                    if verification
                    else 0
                ),
                "rerouted_success_rate": (
                    verification.rerouted_success_rate
                    if verification
                    else 0.0
                ),
                "guardrail_interventions": (
                    1
                    if intervention
                    else 0
                ),
            }
        )

    total_transactions = sum(
        config.before_count + config.after_count
        for config in SCENARIOS
    )

    recovered_scenarios = sum(
        1
        for run in runs
        if (
            run.verification is not None
            and run.verification.recovered
        )
    )

    total_recovered_paise = sum(
        run.metrics.recovered_amount_paise
        for run in runs
    )

    total_interventions = sum(
        1
        for run in runs
        if (
            run.guardrail_decision is not None
            and run.guardrail_decision.policy_intervention
        )
    )

    return {
        "project": "PayInChaos",
        "benchmark_version": "4.0",
        "seed": BENCHMARK_SEED,
        "mode": mode,
        "strict_gemini": mode == "gemini",
        "total_transactions": total_transactions,
        "scenario_count": len(runs),
        "recovered_scenarios": recovered_scenarios,
        "recovery_rate_percent": round(
            recovered_scenarios
            / len(runs)
            * 100.0,
            2,
        ),
        "total_recovered_amount_paise": (
            total_recovered_paise
        ),
        "total_recovered_amount_rupees": round(
            total_recovered_paise / 100.0,
            2,
        ),
        "guardrail_interventions": (
            total_interventions
        ),
        "scenarios": scenario_results,
    }


def print_summary(
    *,
    mode: str,
    runs: list[RecoveryRun],
) -> None:
    """Print the benchmark summary table."""

    print()
    print()
    print("=" * 110)

    print(
        f"PAYINCHAOS BENCHMARK SUMMARY — "
        f"{mode.upper()}"
    )

    print("=" * 110)

    print(
        f"{'Scenario':<24}"
        f"{'MTTD':>10}"
        f"{'MTTR':>10}"
        f"{'Target':>12}"
        f"{'Rerouted':>12}"
        f"{'Recovered ₹':>16}"
        f"{'Guardrail':>12}"
    )

    print("-" * 110)

    for run in runs:
        target = (
            run.routing_rule.target_bank.value
            if run.routing_rule
            else "NONE"
        )

        recovered = (
            run.metrics.recovered_amount_rupees
        )

        rerouted = (
            run.verification.rerouted_transactions
            if run.verification
            else 0
        )

        interventions = (
            1
            if (
                run.guardrail_decision is not None
                and run.guardrail_decision.policy_intervention
            )
            else 0
        )

        mttd = (
            f"{run.metrics.mttd_seconds:.1f}s"
            if run.metrics.mttd_seconds is not None
            else "N/A"
        )

        mttr = (
            f"{run.metrics.mttr_seconds:.1f}s"
            if run.metrics.mttr_seconds is not None
            else "N/A"
        )

        print(
            f"{run.scenario.value:<24}"
            f"{mttd:>10}"
            f"{mttr:>10}"
            f"{target:>12}"
            f"{rerouted:>12}"
            f"{recovered:>16,.2f}"
            f"{interventions:>12}"
        )

    total_recovered = sum(
        run.metrics.recovered_amount_rupees
        for run in runs
    )

    recovered_scenarios = sum(
        1
        for run in runs
        if (
            run.verification is not None
            and run.verification.recovered
        )
    )

    total_rerouted = sum(
        run.verification.rerouted_transactions
        if run.verification
        else 0
        for run in runs
    )

    print("-" * 110)

    total_interventions = sum(
        1
        for run in runs
        if run.guardrail_decision
        and run.guardrail_decision.policy_intervention
    )

    print(
        f"{'TOTAL':<24}"
        f"{'':>10}"
        f"{'':>10}"
        f"{'':>12}"
        f"{total_rerouted:>12}"
        f"{total_recovered:>16,.2f}"
        f"{total_interventions:>12}"
    )

    print()

    print(
        "Recovery rate:",
        recovered_scenarios,
        "/",
        len(runs),
        f"({recovered_scenarios / len(runs) * 100:.1f}%)",
    )

    print(
        "Transactions:",
        sum(
            config.before_count
            + config.after_count
            for config in SCENARIOS
        ),
    )

    print(
        "Rerouted transactions:",
        total_rerouted,
    )

    print(
        "Recovered revenue:",
        format_money(
            int(
                round(
                    total_recovered * 100
                )
            )
        ),
    )

    print("=" * 110)


def parse_args() -> argparse.Namespace:
    """Parse benchmark mode."""

    parser = argparse.ArgumentParser(
        description=(
            "Run the PayInChaos recovery benchmark."
        )
    )

    group = parser.add_mutually_exclusive_group()

    group.add_argument(
        "--gemini",
        action="store_true",
        help=(
            "Run a strict Gemini benchmark. "
            "Fails if Gemini falls back."
        ),
    )

    group.add_argument(
        "--no-gemini",
        action="store_true",
        help=(
            "Run deterministic fallback only."
        ),
    )

    return parser.parse_args()


def resolve_mode(
    args: argparse.Namespace,
) -> tuple[bool, str, Path]:
    """Resolve execution mode and output file."""

    if args.no_gemini:
        return (
            False,
            "deterministic_fallback",
            ROOT / "benchmark_results_fallback.json",
        )

    return (
        True,
        "gemini",
        ROOT / "benchmark_results_gemini.json",
    )


def main() -> None:
    """Run the complete benchmark."""

    args = parse_args()

    use_gemini, mode, output_path = (
        resolve_mode(args)
    )

    expected_transactions = sum(
        config.before_count + config.after_count
        for config in SCENARIOS
    )

    print()
    print("PAYINCHAOS BENCHMARK")
    print("=" * 80)
    print("Mode:", mode)
    print("Seed:", BENCHMARK_SEED)
    print(
        "Running",
        f"{expected_transactions:,}",
        "synthetic transactions across",
        len(SCENARIOS),
        "chaos scenarios...",
    )

    if use_gemini:
        print(
            "Gemini mode: STRICT "
            "(fallback is not permitted)"
        )

    runs: list[RecoveryRun] = []

    try:
        for scenario_index, config in enumerate(
            SCENARIOS
        ):
            run = run_scenario(
                config,
                use_gemini=use_gemini,
                scenario_index=scenario_index,
            )

            runs.append(run)

            print_run(
                config,
                run,
            )

    except Exception as exc:
        print()
        print("=" * 80)
        print("BENCHMARK FAILED")
        print("=" * 80)
        print(
            f"{type(exc).__name__}: {exc}"
        )
        print()
        print(
            "No benchmark result file was written."
        )

        raise SystemExit(1) from exc

    print_summary(
        mode=mode,
        runs=runs,
    )

    payload = build_result_payload(
        mode=mode,
        runs=runs,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            payload,
            file,
            indent=2,
        )

    print()
    print(
        "Benchmark evidence written to:",
        output_path,
    )
    print("JSON VALID")


if __name__ == "__main__":
    main()

