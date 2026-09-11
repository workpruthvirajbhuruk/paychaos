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
    CASCADING_SWITCH_FAILURE = "CASCADING_SWITCH_FAILURE"


@dataclass(frozen=True, slots=True)
class ChaosEvent:
    """Description of an active chaos event."""

    scenario: ChaosScenario
    bank: BankName
    description: str
    injected_latency_ms: float | None = None
    affected_method: PaymentMethod | None = None

    # Cascading-failure metadata.
    #
    # These fields describe a secondary failure that can emerge after
    # the autonomous recovery system begins rerouting traffic.
    secondary_bank: BankName | None = None
    secondary_trigger_after_seconds: float | None = None
    secondary_failure_active: bool = False


class ChaosEngine:
    """Inject and remove controlled payment-switch failures."""

    def __init__(self, switch: PaymentSwitch) -> None:
        self._switch = switch
        self._active_event: ChaosEvent | None = None
        self._cascade_triggered = False

    @property
    def active_event(self) -> ChaosEvent | None:
        """Return the currently active chaos event."""

        return self._active_event

    @property
    def cascade_triggered(self) -> bool:
        """Return whether the secondary cascading failure is active."""

        return self._cascade_triggered

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

        elif scenario is ChaosScenario.CASCADING_SWITCH_FAILURE:
            event = self._inject_cascading_switch_failure()

        else:
            raise ValueError(
                f"Unsupported chaos scenario: {scenario}"
            )

        self._active_event = event

        return event

    def clear(self) -> None:
        """Remove all active chaos."""

        self._switch.reset_all_banks()
        self._active_event = None
        self._cascade_triggered = False

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

    def _inject_cascading_switch_failure(self) -> ChaosEvent:
        """Inject a primary failure that later spreads to its target.

        The initial failure affects SBI UPI. The intended recovery target
        is AXIS. After the configured delay, AXIS UPI becomes degraded.

        This intentionally creates a situation where a naive autonomous
        recovery system would continue sending traffic into a failing
        target. PayInChaos must detect that condition and stop/escalate.
        """

        state = self._switch.get_bank_state(BankName.SBI)

        state.method_latency_multipliers[PaymentMethod.UPI] = (
            4500.0 / state.base_latency_ms
        )

        state.method_error_codes[PaymentMethod.UPI] = (
            ErrorCode.GATEWAY_TIMEOUT
        )

        return ChaosEvent(
            scenario=ChaosScenario.CASCADING_SWITCH_FAILURE,
            bank=BankName.SBI,
            description=(
                "SBI UPI initially fails with gateway timeouts. "
                "After recovery traffic begins moving, AXIS UPI "
                "also degrades, forcing the recovery controller to "
                "stop autonomous routing and escalate."
            ),
            injected_latency_ms=4500.0,
            affected_method=PaymentMethod.UPI,
            secondary_bank=BankName.AXIS,
            secondary_trigger_after_seconds=7.0,
        )

    def tick(self, elapsed_seconds: float) -> None:
        """Advance a time-dependent chaos scenario.

        FLAPPING_GATEWAY alternates between healthy and degraded phases.

        CASCADING_SWITCH_FAILURE activates its secondary bank failure once
        the configured trigger time has elapsed.
        """

        if self._active_event is None:
            return

        if self._active_event.scenario is ChaosScenario.FLAPPING_GATEWAY:
            self._tick_flapping_gateway(elapsed_seconds)
            return

        if (
            self._active_event.scenario
            is ChaosScenario.CASCADING_SWITCH_FAILURE
        ):
            self._tick_cascading_failure(elapsed_seconds)

    def _tick_flapping_gateway(
        self,
        elapsed_seconds: float,
    ) -> None:
        """Advance the ICICI flapping gateway."""

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

    def _tick_cascading_failure(
        self,
        elapsed_seconds: float,
    ) -> None:
        """Activate the secondary AXIS failure after the trigger delay."""

        event = self._active_event

        if event is None:
            return

        trigger_after = event.secondary_trigger_after_seconds

        if trigger_after is None:
            return

        if elapsed_seconds < trigger_after:
            return

        if self._cascade_triggered:
            return

        secondary_bank = event.secondary_bank

        if secondary_bank is None:
            return

        state = self._switch.get_bank_state(
            secondary_bank
        )

        # AXIS becomes unhealthy specifically for UPI traffic.
        state.method_latency_multipliers[PaymentMethod.UPI] = (
            4500.0 / state.base_latency_ms
        )

        state.method_error_codes[PaymentMethod.UPI] = (
            ErrorCode.GATEWAY_TIMEOUT
        )

        self._cascade_triggered = True

        self._active_event = ChaosEvent(
            scenario=event.scenario,
            bank=event.bank,
            description=event.description,
            injected_latency_ms=event.injected_latency_ms,
            affected_method=event.affected_method,
            secondary_bank=event.secondary_bank,
            secondary_trigger_after_seconds=(
                event.secondary_trigger_after_seconds
            ),
            secondary_failure_active=True,
        )