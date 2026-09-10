"""Rolling telemetry and deterministic health analysis for PayInChaos."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from typing import Iterable

from app.config import DEFAULT_SETTINGS, Settings
from app.switch import (
    BankName,
    ErrorCode,
    PaymentMethod,
    TransactionResult,
)


@dataclass(frozen=True, slots=True)
class TelemetrySnapshot:
    """Aggregated health metrics for a bank/method scope."""

    bank: BankName
    method: PaymentMethod | None

    total_transactions: int
    successful_transactions: int
    failed_transactions: int

    success_rate: float
    p99_latency_ms: float

    error_distribution: dict[str, int]

    anomaly_detected: bool
    anomaly_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BankHealth:
    """Deterministic health state for one bank."""

    bank: BankName

    success_rate: float
    p99_latency_ms: float

    total_transactions: int
    successful_transactions: int
    failed_transactions: int

    anomaly_detected: bool
    anomaly_reasons: tuple[str, ...]

    healthy: bool


@dataclass(frozen=True, slots=True)
class RevenueMetrics:
    """Revenue metrics derived from the rolling telemetry window."""

    total_processed_paise: int
    successful_processed_paise: int
    failed_processed_paise: int

    successful_transactions: int
    failed_transactions: int

    @property
    def total_processed_rupees(self) -> float:
        """Return total processed transaction value in rupees."""

        return round(
            self.total_processed_paise / 100.0,
            2,
        )

    @property
    def successful_processed_rupees(self) -> float:
        """Return successful transaction value in rupees."""

        return round(
            self.successful_processed_paise / 100.0,
            2,
        )

    @property
    def failed_processed_rupees(self) -> float:
        """Return failed transaction value in rupees."""

        return round(
            self.failed_processed_paise / 100.0,
            2,
        )


class Telemetry:
    """30-second rolling telemetry store.

    Telemetry records raw transaction outcomes and derives:

        - Success Rate
        - P99 latency
        - Error distribution
        - Anomaly state
        - Bank health
        - Revenue metrics

    The class is intentionally independent from the AI agent.
    """

    def __init__(
        self,
        *,
        settings: Settings = DEFAULT_SETTINGS,
    ) -> None:
        self._window_seconds = settings.telemetry_window_seconds

        self._success_rate_threshold = (
            settings.anomaly_success_rate_threshold
        )

        self._p99_latency_threshold_ms = (
            settings.anomaly_p99_latency_threshold_ms
        )

        self._results: deque[TransactionResult] = deque()

    def record(
        self,
        result: TransactionResult,
    ) -> None:
        """Record one transaction result."""

        self._results.append(result)

        self._evict_expired(
            result.timestamp
        )

    def record_many(
        self,
        results: Iterable[TransactionResult],
    ) -> None:
        """Record multiple transaction results."""

        for result in results:
            self.record(result)

    def snapshot(
        self,
        *,
        bank: BankName,
        method: PaymentMethod | None = None,
        now: float | None = None,
    ) -> TelemetrySnapshot:
        """Build a rolling health snapshot."""

        if now is None:
            if self._results:
                now = self._results[-1].timestamp
            else:
                now = 0.0

        self._evict_expired(now)

        matching_results = [
            result
            for result in self._results
            if result.bank is bank
            and (
                method is None
                or result.method is method
            )
        ]

        total = len(matching_results)

        if total == 0:
            return TelemetrySnapshot(
                bank=bank,
                method=method,
                total_transactions=0,
                successful_transactions=0,
                failed_transactions=0,
                success_rate=0.0,
                p99_latency_ms=0.0,
                error_distribution={},
                anomaly_detected=False,
                anomaly_reasons=(),
            )

        successful = sum(
            1
            for result in matching_results
            if result.success
        )

        failed = total - successful

        success_rate = round(
            (successful / total) * 100.0,
            2,
        )

        p99_latency = self._calculate_p99(
            [
                result.latency_ms
                for result in matching_results
            ]
        )

        error_distribution = (
            self._calculate_error_distribution(
                matching_results
            )
        )

        anomaly_reasons: list[str] = []

        if success_rate < self._success_rate_threshold:
            anomaly_reasons.append(
                f"success_rate_below_"
                f"{self._success_rate_threshold:.0f}_percent"
            )

        if (
            p99_latency
            > self._p99_latency_threshold_ms
        ):
            anomaly_reasons.append(
                f"p99_latency_above_"
                f"{self._p99_latency_threshold_ms:.0f}ms"
            )

        return TelemetrySnapshot(
            bank=bank,
            method=method,
            total_transactions=total,
            successful_transactions=successful,
            failed_transactions=failed,
            success_rate=success_rate,
            p99_latency_ms=p99_latency,
            error_distribution=error_distribution,
            anomaly_detected=bool(anomaly_reasons),
            anomaly_reasons=tuple(anomaly_reasons),
        )

    def bank_health(
        self,
        *,
        bank: BankName,
        now: float | None = None,
    ) -> BankHealth:
        """Return deterministic health state for one bank."""

        snapshot = self.snapshot(
            bank=bank,
            now=now,
        )

        return BankHealth(
            bank=bank,
            success_rate=snapshot.success_rate,
            p99_latency_ms=snapshot.p99_latency_ms,
            total_transactions=snapshot.total_transactions,
            successful_transactions=(
                snapshot.successful_transactions
            ),
            failed_transactions=(
                snapshot.failed_transactions
            ),
            anomaly_detected=snapshot.anomaly_detected,
            anomaly_reasons=snapshot.anomaly_reasons,
            healthy=not snapshot.anomaly_detected,
        )

    def all_bank_health(
        self,
        *,
        now: float | None = None,
    ) -> dict[BankName, BankHealth]:
        """Return deterministic health state for every bank."""

        return {
            bank: self.bank_health(
                bank=bank,
                now=now,
            )
            for bank in BankName
        }

    def healthy_banks(
        self,
        *,
        now: float | None = None,
        exclude: set[BankName] | None = None,
    ) -> set[BankName]:
        """Return banks currently considered healthy.

        Health is derived exclusively from deterministic telemetry.
        The AI agent has no authority over this set.
        """

        excluded = exclude or set()

        health = self.all_bank_health(
            now=now
        )

        return {
            bank
            for bank, state in health.items()
            if state.healthy
            and bank not in excluded
        }

    def revenue_metrics(
        self,
        *,
        now: float | None = None,
    ) -> RevenueMetrics:
        """Calculate transaction-value metrics in the rolling window."""

        if now is None:
            if self._results:
                now = self._results[-1].timestamp
            else:
                now = 0.0

        self._evict_expired(now)

        total_processed = sum(
            result.amount_paise
            for result in self._results
        )

        successful_processed = sum(
            result.amount_paise
            for result in self._results
            if result.success
        )

        failed_processed = (
            total_processed
            - successful_processed
        )

        successful_transactions = sum(
            1
            for result in self._results
            if result.success
        )

        failed_transactions = (
            len(self._results)
            - successful_transactions
        )

        return RevenueMetrics(
            total_processed_paise=total_processed,
            successful_processed_paise=(
                successful_processed
            ),
            failed_processed_paise=failed_processed,
            successful_transactions=(
                successful_transactions
            ),
            failed_transactions=failed_transactions,
        )

    def all_bank_snapshots(
        self,
        *,
        now: float | None = None,
    ) -> dict[BankName, TelemetrySnapshot]:
        """Return one health snapshot for every bank."""

        return {
            bank: self.snapshot(
                bank=bank,
                now=now,
            )
            for bank in BankName
        }

    def method_snapshot(
        self,
        *,
        bank: BankName,
        method: PaymentMethod,
        now: float | None = None,
    ) -> TelemetrySnapshot:
        """Return telemetry for one bank and payment method."""

        return self.snapshot(
            bank=bank,
            method=method,
            now=now,
        )

    def clear(self) -> None:
        """Remove all stored telemetry."""

        self._results.clear()

    @property
    def result_count(self) -> int:
        """Return the number of results currently in the rolling window."""

        return len(self._results)

    def _evict_expired(
        self,
        now: float,
    ) -> None:
        """Remove results older than the rolling telemetry window."""

        cutoff = now - self._window_seconds

        while (
            self._results
            and self._results[0].timestamp < cutoff
        ):
            self._results.popleft()

    @staticmethod
    def _calculate_p99(
        latencies: list[float],
    ) -> float:
        """Calculate P99 latency using nearest-rank percentile."""

        if not latencies:
            return 0.0

        ordered = sorted(latencies)

        rank = max(
            1,
            int(
                (
                    99 * len(ordered)
                    + 99
                )
                // 100
            ),
        )

        index = min(
            rank - 1,
            len(ordered) - 1,
        )

        return round(
            ordered[index],
            2,
        )

    @staticmethod
    def _calculate_error_distribution(
        results: list[TransactionResult],
    ) -> dict[str, int]:
        """Count failures by canonical error code."""

        errors = Counter(
            result.error_code.value
            for result in results
            if result.error_code is not None
        )

        return dict(
            sorted(errors.items())
        )