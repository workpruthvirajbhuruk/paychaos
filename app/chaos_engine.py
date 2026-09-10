"""Chaos injection engine for PayInChaos."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.switch import (
    BankName,
    ErrorCode,
    PaymentMethod,
    PaymentSwitch,
)


class ChaosScenario(str, Enum):
    """Supported chaos scenarios."""

    OTP_SILENT_DROP = "OTP_SILENT_DROP"
    UPI_LATENCY_SPIKE = "UPI_LATENCY_SPIKE"
    BIN_ISOLATED_FAILURE = "BIN_ISOLATED_FAILURE"
    FLAPPING_GATEWAY = "FLAPPING_GATEWAY"


@dataclass(frozen=True, slots=True)
class ChaosEvent:
    """Description of an active chaos event."""

    scenario: ChaosScenario
    bank: BankName
    description: str
    injected_latency_ms: float | None = None
    affected_method: PaymentMethod | None = None


class ChaosEngine:
    """Inject and remove controlled payment-switch failures."""

    def __init__(self, switch: PaymentSwitch) -> None:
        self._switch = switch
        self._active_event: ChaosEvent | None = None

    @property
    def active_event(self) -> ChaosEvent | None:
        """Return the currently active chaos event."""

        return self._active_event

    def inject(self, scenario: ChaosScenario) -> ChaosEvent:
        """Inject a chaos scenario."""

        self.clear()

        if scenario is ChaosScenario.OTP_SILENT_DROP:
            event = self._inject_otp_silent_drop()

        elif scenario is ChaosScenario.UPI_LATENCY_SPIKE:
            event = self._inject_upi_latency_spike()

        elif scenario is ChaosScenario.BIN_ISOLATED_FAILURE:
            event = self._inject_bin_isolated_failure()

        elif scenario is ChaosScenario.FLAPPING_GATEWAY:
            event = self._inject_flapping_gateway()

        else:
            raise ValueError(f"Unsupported chaos scenario: {scenario}")

        self._active_event = event

        return event

    def clear(self) -> None:
        """Remove all active chaos."""

        self._switch.reset_all_banks()
        self._active_event = None

    def _inject_otp_silent_drop(self) -> ChaosEvent:
        """Inject deterministic OTP completion failures into HDFC UPI."""

        state = self._switch.get_bank_state(BankName.HDFC)

        state.method_failure_rates[PaymentMethod.UPI] = 1.0

        state.method_error_codes[PaymentMethod.UPI] = (
            ErrorCode.OTP_TIMEOUT
        )

        return ChaosEvent(
            scenario=ChaosScenario.OTP_SILENT_DROP,
            bank=BankName.HDFC,
            description=(
                "HDFC accepts the payment request but OTP completion "
                "silently times out after 30 seconds."
            ),
            affected_method=PaymentMethod.UPI,
        )

    def _inject_upi_latency_spike(self) -> ChaosEvent:
        """Inject a 4500ms-class latency spike into SBI UPI only."""

        state = self._switch.get_bank_state(BankName.SBI)

        state.method_latency_multipliers[PaymentMethod.UPI] = (
            4500.0 / state.base_latency_ms
        )

        state.method_error_codes[PaymentMethod.UPI] = (
            ErrorCode.GATEWAY_TIMEOUT
        )

        return ChaosEvent(
            scenario=ChaosScenario.UPI_LATENCY_SPIKE,
            bank=BankName.SBI,
            description=(
                "SBI UPI latency rises to approximately 4500ms, "
                "crossing the gateway timeout boundary."
            ),
            injected_latency_ms=4500.0,
            affected_method=PaymentMethod.UPI,
        )

    def _inject_bin_isolated_failure(self) -> ChaosEvent:
        """Inject RuPay-only issuer failures into AXIS."""

        state = self._switch.get_bank_state(BankName.AXIS)

        state.method_failure_rates[PaymentMethod.CARD_RUPAY] = 1.0

        state.method_error_codes[PaymentMethod.CARD_RUPAY] = (
            ErrorCode.ISSUER_UNAVAILABLE
        )

        return ChaosEvent(
            scenario=ChaosScenario.BIN_ISOLATED_FAILURE,
            bank=BankName.AXIS,
            description=(
                "AXIS RuPay issuer traffic is unavailable while Visa "
                "and UPI remain healthy."
            ),
            affected_method=PaymentMethod.CARD_RUPAY,
        )

    def _inject_flapping_gateway(self) -> ChaosEvent:
        """Initialize ICICI for a flapping gateway."""

        return ChaosEvent(
            scenario=ChaosScenario.FLAPPING_GATEWAY,
            bank=BankName.ICICI,
            description=(
                "ICICI alternates between healthy and degraded "
                "gateway states every 15 seconds."
            ),
        )

    def tick(self, elapsed_seconds: float) -> None:
        """Advance a time-dependent chaos scenario."""

        if self._active_event is None:
            return

        if self._active_event.scenario is not ChaosScenario.FLAPPING_GATEWAY:
            return

        state = self._switch.get_bank_state(BankName.ICICI)

        phase = int(elapsed_seconds // 15) % 2

        if phase == 0:
            # Healthy phase: approximately 99% baseline SR.
            state.latency_multiplier = 1.0
            state.additional_failure_rate = 0.0
            state.forced_error_code = ErrorCode.BANK_ERROR

        else:
            # Degraded phase:
            #
            # Base SR = 99.1%
            # Additional failure = 79%
            #
            # Effective SR ≈ 20.1%.
            state.latency_multiplier = 1.0
            state.additional_failure_rate = 0.79
            state.forced_error_code = ErrorCode.BANK_ERROR