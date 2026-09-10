
"""Core payment-switch simulation for PayInChaos."""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class BankName(str, Enum):
    """Supported bank payment switches."""

    HDFC = "HDFC"
    ICICI = "ICICI"
    SBI = "SBI"
    AXIS = "AXIS"


class PaymentMethod(str, Enum):
    """Supported payment methods."""

    UPI = "UPI"
    CARD_RUPAY = "CARD_RUPAY"
    CARD_VISA = "CARD_VISA"


class ErrorCode(str, Enum):
    """Canonical payment failure categories."""

    GATEWAY_TIMEOUT = "GATEWAY_TIMEOUT"
    ISSUER_UNAVAILABLE = "ISSUER_UNAVAILABLE"
    OTP_TIMEOUT = "OTP_TIMEOUT"
    BANK_ERROR = "BANK_ERROR"


@dataclass(frozen=True, slots=True)
class Transaction:
    """Immutable payment request."""

    transaction_id: str
    amount_paise: int
    method: PaymentMethod
    bank: BankName
    created_at: float


@dataclass(frozen=True, slots=True)
class TransactionResult:
    """Result produced after processing a transaction."""

    transaction_id: str
    bank: BankName
    method: PaymentMethod
    amount_paise: int
    success: bool
    latency_ms: float
    error_code: ErrorCode | None
    timestamp: float


@dataclass(slots=True)
class BankSwitchState:
    """Mutable runtime state for a bank switch."""

    bank: BankName

    base_latency_ms: float
    base_success_rate: float = 0.99

    # Bank-wide dynamic degradation.
    latency_multiplier: float = 1.0
    additional_failure_rate: float = 0.0

    # Method-specific chaos.
    method_latency_multipliers: dict[PaymentMethod, float] = field(
        default_factory=dict
    )
    method_failure_rates: dict[PaymentMethod, float] = field(
        default_factory=dict
    )
    method_error_codes: dict[PaymentMethod, ErrorCode] = field(
        default_factory=dict
    )

    # Default error for generic bank-level failures.
    forced_error_code: ErrorCode = ErrorCode.BANK_ERROR

    def reset_dynamic_state(self) -> None:
        """Remove all dynamically injected degradation."""

        self.latency_multiplier = 1.0
        self.additional_failure_rate = 0.0

        self.method_latency_multipliers.clear()
        self.method_failure_rates.clear()
        self.method_error_codes.clear()

        self.forced_error_code = ErrorCode.BANK_ERROR


class PaymentSwitch:
    """Simulated multi-bank payment switch.

    The switch owns its own random generator so simulation randomness
    is isolated from global application state.

    ``seed`` makes processing randomness reproducible.

    ``transaction_id_prefix`` can be supplied for deterministic
    benchmark runs. When provided, transaction IDs become:

        <prefix>_000001
        <prefix>_000002
        ...

    Normal production-style usage continues to use UUIDs.
    """

    DEFAULT_BANK_STATES: dict[BankName, tuple[float, float]] = {
        BankName.HDFC: (180.0, 0.992),
        BankName.ICICI: (210.0, 0.991),
        BankName.SBI: (190.0, 0.989),
        BankName.AXIS: (200.0, 0.992),
    }

    def __init__(
        self,
        *,
        seed: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        timeout_threshold_ms: float = 2500.0,
        transaction_id_prefix: str | None = None,
    ) -> None:
        self._rng = random.Random(seed)
        self._clock = clock
        self.timeout_threshold_ms = timeout_threshold_ms

        self._transaction_id_prefix = transaction_id_prefix
        self._transaction_sequence = 0

        self._banks: dict[BankName, BankSwitchState] = {
            bank: BankSwitchState(
                bank=bank,
                base_latency_ms=latency,
                base_success_rate=success_rate,
            )
            for bank, (latency, success_rate) in self.DEFAULT_BANK_STATES.items()
        }

    def create_transaction(
        self,
        *,
        amount_paise: int,
        method: PaymentMethod,
        bank: BankName,
    ) -> Transaction:
        """Create a transaction.

        When ``transaction_id_prefix`` was configured, the generated
        ID is deterministic. Otherwise a UUID is used.
        """

        if amount_paise <= 0:
            raise ValueError(
                "amount_paise must be greater than zero"
            )

        transaction_id = self._next_transaction_id()

        return Transaction(
            transaction_id=transaction_id,
            amount_paise=amount_paise,
            method=method,
            bank=bank,
            created_at=self._clock(),
        )

    def process(
        self,
        transaction: Transaction,
    ) -> TransactionResult:
        """Process one transaction through the simulated switch."""

        state = self._banks[transaction.bank]

        latency_ms = self._calculate_latency(
            state=state,
            method=transaction.method,
        )

        failure_rate = self._calculate_failure_rate(
            state=state,
            method=transaction.method,
        )

        if latency_ms > self.timeout_threshold_ms:
            success = False
            error_code = ErrorCode.GATEWAY_TIMEOUT

        else:
            success = self._rng.random() < (
                1.0 - failure_rate
            )

            if success:
                error_code = None
            else:
                error_code = self._get_error_code(
                    state=state,
                    method=transaction.method,
                )

        return TransactionResult(
            transaction_id=transaction.transaction_id,
            bank=transaction.bank,
            method=transaction.method,
            amount_paise=transaction.amount_paise,
            success=success,
            latency_ms=latency_ms,
            error_code=error_code,
            timestamp=self._clock(),
        )

    def get_bank_state(
        self,
        bank: BankName,
    ) -> BankSwitchState:
        """Return mutable state for one bank."""

        return self._banks[bank]

    def reset_all_banks(self) -> None:
        """Clear all dynamic chaos state."""

        for state in self._banks.values():
            state.reset_dynamic_state()

    def reset_transaction_sequence(self) -> None:
        """Reset deterministic transaction numbering."""

        self._transaction_sequence = 0

    def _next_transaction_id(self) -> str:
        """Generate either a deterministic or UUID transaction ID."""

        if self._transaction_id_prefix is None:
            return f"txn_{uuid.uuid4().hex}"

        self._transaction_sequence += 1

        return (
            f"{self._transaction_id_prefix}_"
            f"{self._transaction_sequence:06d}"
        )

    def _calculate_latency(
        self,
        *,
        state: BankSwitchState,
        method: PaymentMethod,
    ) -> float:
        """Calculate simulated transaction latency."""

        jitter = self._rng.uniform(
            0.90,
            1.10,
        )

        method_multiplier = (
            state.method_latency_multipliers.get(
                method,
                1.0,
            )
        )

        latency = (
            state.base_latency_ms
            * state.latency_multiplier
            * method_multiplier
            * jitter
        )

        return round(
            latency,
            2,
        )

    @staticmethod
    def _calculate_failure_rate(
        *,
        state: BankSwitchState,
        method: PaymentMethod,
    ) -> float:
        """Calculate effective transaction failure probability."""

        method_failure_rate = (
            state.method_failure_rates.get(
                method,
                0.0,
            )
        )

        failure_rate = (
            (1.0 - state.base_success_rate)
            + state.additional_failure_rate
            + method_failure_rate
        )

        return min(
            max(
                failure_rate,
                0.0,
            ),
            1.0,
        )

    @staticmethod
    def _get_error_code(
        *,
        state: BankSwitchState,
        method: PaymentMethod,
    ) -> ErrorCode:
        """Resolve the canonical error code."""

        return state.method_error_codes.get(
            method,
            state.forced_error_code,
        )

