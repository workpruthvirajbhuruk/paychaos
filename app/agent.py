"""AI diagnosis and recovery recommendation engine for PayInChaos.

Architecture:
    AI         -> observe + diagnose + recommend
    Guardrails -> validate + clamp + cooldown
    Router     -> execute
    Telemetry  -> verify

The AI agent NEVER executes a routing change directly.

Gemini is optional:
    - When enabled and available, Gemini provides diagnosis/recommendation.
    - When disabled or unavailable, deterministic diagnosis/recommendation
      keeps the recovery pipeline operational.

Deterministic fallback policy:
    - Method-specific anomaly -> 30% traffic shift.
    - Latency-driven anomaly  -> 30% traffic shift.
    - Bank-wide anomaly       -> 40% traffic shift.
    - Failover destinations use an explicit deterministic preference matrix.

The deterministic failover matrix prevents incidental telemetry volume from
changing the recovery destination. The matrix still respects the current
availability set supplied by the recovery controller.

Guardrails remain the final authority regardless of whether the
recommendation came from Gemini or deterministic policy.
"""

from __future__ import annotations

import json
import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

from app.config import DEFAULT_SETTINGS, Settings
from app.switch import BankName, ErrorCode
from app.telemetry import Telemetry, TelemetrySnapshot


load_dotenv()


class RerouteAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isolated_bank: str
    target_bank: str
    scope: Literal["ALL", "UPI", "CARD_RUPAY", "CARD_VISA"]
    traffic_percentage: int = Field(..., ge=10, le=100)
    root_cause_summary: str
    cooling_period_seconds: int = Field(..., ge=60)


class DiagnosisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["gemini", "deterministic_fallback"]
    bank: str
    method: str | None
    anomaly_detected: bool
    diagnosis: str
    action: RerouteAction | None
    confidence: float = Field(..., ge=0.0, le=1.0)


class AIAgent:
    """AI diagnosis and recovery recommendation engine."""

    DEFAULT_MODEL = "gemini-3.6-flash"

    # ------------------------------------------------------------------
    # Deterministic failover policy
    #
    # These are preferred destinations, not unconditional routes.
    # The recovery controller still supplies the currently available
    # banks, and the selected destination must be present in that set.
    #
    # Keeping this matrix deterministic means:
    #
    #     same incident + same available banks -> same recommendation
    #
    # regardless of incidental dashboard transaction volume.
    # ------------------------------------------------------------------
    FAILOVER_PREFERENCES: dict[BankName, tuple[BankName, ...]] = {
        BankName.HDFC: (
            BankName.AXIS,
            BankName.ICICI,
            BankName.SBI,
        ),
        BankName.SBI: (
            BankName.AXIS,
            BankName.HDFC,
            BankName.ICICI,
        ),
        BankName.AXIS: (
            BankName.HDFC,
            BankName.ICICI,
            BankName.SBI,
        ),
        BankName.ICICI: (
            BankName.AXIS,
            BankName.HDFC,
            BankName.SBI,
        ),
    }

    def __init__(
        self,
        *,
        settings: Settings = DEFAULT_SETTINGS,
        model: str | None = None,
        telemetry: Telemetry | None = None,
        use_gemini: bool = True,
    ) -> None:
        self._settings = settings
        self._model = (
            model
            or os.getenv("GEMINI_MODEL")
            or self.DEFAULT_MODEL
        )

        self._api_key = os.getenv("GEMINI_API_KEY")
        self._client = None
        self._last_gemini_error: str | None = None
        self._telemetry = telemetry
        self._use_gemini = use_gemini

        if self._use_gemini and self._api_key:
            self._initialize_gemini()

    @property
    def gemini_available(self) -> bool:
        """Return whether Gemini is initialized."""

        return self._client is not None

    @property
    def model(self) -> str:
        """Return the configured Gemini model."""

        return self._model

    @property
    def use_gemini(self) -> bool:
        """Return whether Gemini usage is enabled."""

        return self._use_gemini

    @property
    def last_gemini_error(self) -> str | None:
        """Return the latest Gemini error, if any."""

        return self._last_gemini_error

    def diagnose(
        self,
        snapshot: TelemetrySnapshot,
        *,
        available_banks: list[BankName] | None = None,
    ) -> DiagnosisResult:
        """Diagnose an anomaly and recommend a bounded action."""

        self._last_gemini_error = None

        if not snapshot.anomaly_detected:
            return DiagnosisResult(
                source="deterministic_fallback",
                bank=snapshot.bank.value,
                method=(
                    snapshot.method.value
                    if snapshot.method
                    else None
                ),
                anomaly_detected=False,
                diagnosis="No material anomaly detected.",
                action=None,
                confidence=1.0,
            )

        banks = available_banks or list(BankName)

        if self._use_gemini and self.gemini_available:
            try:
                return self._diagnose_with_gemini(
                    snapshot=snapshot,
                    available_banks=banks,
                )
            except Exception as exc:
                self._last_gemini_error = (
                    f"{type(exc).__name__}: {exc}"
                )

        return self._diagnose_deterministically(
            snapshot=snapshot,
            available_banks=banks,
        )

    def _initialize_gemini(self) -> None:
        """Initialize the Gemini client."""

        try:
            from google import genai

            self._client = genai.Client(
                api_key=self._api_key
            )

        except Exception as exc:
            self._client = None
            self._last_gemini_error = (
                f"{type(exc).__name__}: {exc}"
            )

    def _diagnose_with_gemini(
        self,
        *,
        snapshot: TelemetrySnapshot,
        available_banks: list[BankName],
    ) -> DiagnosisResult:
        """Ask Gemini for a structured diagnosis."""

        telemetry_payload = self._build_telemetry_payload(
            snapshot
        )

        available_bank_values = [
            bank.value
            for bank in available_banks
        ]

        prompt = f"""
You are the diagnosis engine inside PayInChaos,
a payment-switch resilience system.

Analyze the payment telemetry below and recommend ONE
bounded traffic-routing action.

You are NOT allowed to execute the action.

TELEMETRY:
{json.dumps(telemetry_payload, indent=2)}

AVAILABLE BANKS:
{json.dumps(available_bank_values)}

RULES:

1. Identify the most likely root cause.
2. Determine whether the failure is bank-wide or method-specific.
3. Prefer the smallest affected scope.
4. If the anomaly is method-specific, use that exact method.
5. Choose a target bank different from the failing bank.
6. Choose only from AVAILABLE BANKS.
7. traffic_percentage must be between 10 and 40.
8. cooling_period_seconds must be at least 60.
9. Never route traffic to the failing bank.
10. source must be "gemini".
11. confidence must be between 0 and 1.
12. Return only JSON matching the supplied schema.
"""

        response_schema = DiagnosisResult.model_json_schema()

        interaction = self._client.interactions.create(
            model=self._model,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": response_schema,
            },
        )

        response_text = interaction.output_text

        if not response_text:
            raise RuntimeError(
                "Gemini returned an empty response."
            )

        result = DiagnosisResult.model_validate_json(
            response_text
        )

        self._validate_action_targets(
            result=result,
            snapshot=snapshot,
            available_banks=available_banks,
        )

        return result

    def _diagnose_deterministically(
        self,
        *,
        snapshot: TelemetrySnapshot,
        available_banks: list[BankName],
    ) -> DiagnosisResult:
        """Produce a diagnosis without using an LLM."""

        bank = snapshot.bank
        method = snapshot.method

        diagnosis = self._infer_root_cause(
            snapshot=snapshot
        )

        target_bank = self._select_target_bank(
            isolated_bank=bank,
            available_banks=available_banks,
        )

        scope = (
            method.value
            if method
            else "ALL"
        )

        traffic_percentage = self._fallback_traffic_percentage(
            snapshot=snapshot
        )

        action = RerouteAction(
            isolated_bank=bank.value,
            target_bank=target_bank.value,
            scope=scope,
            traffic_percentage=traffic_percentage,
            root_cause_summary=diagnosis,
            cooling_period_seconds=(
                self._settings.default_ai_cooling_period_seconds
            ),
        )

        return DiagnosisResult(
            source="deterministic_fallback",
            bank=bank.value,
            method=(
                method.value
                if method
                else None
            ),
            anomaly_detected=True,
            diagnosis=diagnosis,
            action=action,
            confidence=0.95,
        )

    def _fallback_traffic_percentage(
        self,
        *,
        snapshot: TelemetrySnapshot,
    ) -> int:
        """Choose a deterministic traffic-shift policy."""

        # Method-specific incidents are isolated as narrowly as
        # possible, so only a partial traffic shift is required.
        if snapshot.method is not None:
            return 30

        # Bank-wide latency incidents also receive a measured
        # partial shift rather than immediately moving 40%.
        if (
            snapshot.p99_latency_ms
            > self._settings.anomaly_p99_latency_threshold_ms
        ):
            return 30

        # A bank-wide availability/error incident requires a
        # larger protective shift.
        return self._settings.max_reroute_percentage

    def _infer_root_cause(
        self,
        *,
        snapshot: TelemetrySnapshot,
    ) -> str:
        """Infer root cause from deterministic telemetry."""

        errors = snapshot.error_distribution

        if (
            ErrorCode.GATEWAY_TIMEOUT.value in errors
            and snapshot.p99_latency_ms
            > self._settings.anomaly_p99_latency_threshold_ms
        ):
            if snapshot.method:
                return (
                    f"{snapshot.bank.value} "
                    f"{snapshot.method.value} traffic is experiencing "
                    f"gateway timeout failures caused by elevated latency."
                )

            return (
                f"{snapshot.bank.value} is experiencing gateway "
                f"timeouts caused by elevated latency."
            )

        if ErrorCode.OTP_TIMEOUT.value in errors:
            return (
                f"{snapshot.bank.value} "
                f"{snapshot.method.value if snapshot.method else 'payment'} "
                f"traffic is experiencing OTP completion timeouts."
            )

        if ErrorCode.ISSUER_UNAVAILABLE.value in errors:
            return (
                f"{snapshot.bank.value} "
                f"{snapshot.method.value if snapshot.method else 'payment'} "
                f"traffic is experiencing issuer availability failures."
            )

        if ErrorCode.BANK_ERROR.value in errors:
            return (
                f"{snapshot.bank.value} is experiencing elevated "
                f"bank-side transaction failures."
            )

        return (
            f"{snapshot.bank.value} is showing anomalous "
            f"transaction degradation requiring isolation."
        )

    def _select_target_bank(
        self,
        *,
        isolated_bank: BankName,
        available_banks: list[BankName],
    ) -> BankName:
        """Select a deterministic preferred destination.

        The recovery controller supplies the banks currently considered
        available. We respect that availability set, but do not rank
        destinations using incidental telemetry volume.

        This makes the fallback recommendation reproducible and ensures
        the dashboard, tests, and benchmark observe the same policy.
        """

        available = {
            bank
            for bank in available_banks
            if bank is not isolated_bank
        }

        if not available:
            raise RuntimeError(
                "No alternative bank is available."
            )

        preferences = self.FAILOVER_PREFERENCES.get(
            isolated_bank,
            tuple(
                sorted(
                    available,
                    key=lambda bank: bank.value,
                )
            ),
        )

        for preferred_bank in preferences:
            if preferred_bank in available:
                return preferred_bank

        # Defensive fallback for an unknown bank or incomplete matrix.
        return sorted(
            available,
            key=lambda bank: bank.value,
        )[0]

    @staticmethod
    def _build_telemetry_payload(
        snapshot: TelemetrySnapshot,
    ) -> dict[str, object]:
        """Build the telemetry payload sent to Gemini."""

        return {
            "bank": snapshot.bank.value,
            "method": (
                snapshot.method.value
                if snapshot.method
                else None
            ),
            "total_transactions": snapshot.total_transactions,
            "successful_transactions": (
                snapshot.successful_transactions
            ),
            "failed_transactions": snapshot.failed_transactions,
            "success_rate_percent": snapshot.success_rate,
            "p99_latency_ms": snapshot.p99_latency_ms,
            "error_distribution": snapshot.error_distribution,
            "anomaly_detected": snapshot.anomaly_detected,
            "anomaly_reasons": list(
                snapshot.anomaly_reasons
            ),
        }

    @staticmethod
    def _validate_action_targets(
        *,
        result: DiagnosisResult,
        snapshot: TelemetrySnapshot,
        available_banks: list[BankName],
    ) -> None:
        """Validate Gemini's recommendation before guardrails."""

        if result.action is None:
            raise RuntimeError(
                "Gemini returned no recovery action."
            )

        action = result.action

        available_values = {
            bank.value
            for bank in available_banks
        }

        if action.isolated_bank != snapshot.bank.value:
            raise RuntimeError(
                "AI isolated_bank does not match telemetry."
            )

        if action.target_bank not in available_values:
            raise RuntimeError(
                "AI selected an unavailable target bank."
            )

        if action.target_bank == action.isolated_bank:
            raise RuntimeError(
                "AI selected the failing bank as target."
            )

        if snapshot.method is not None:
            if action.scope != snapshot.method.value:
                raise RuntimeError(
                    "AI selected an incorrect scope "
                    "for a method-specific anomaly."
                )

        if not 10 <= action.traffic_percentage <= 40:
            raise RuntimeError(
                "AI traffic percentage is outside 10-40%."
            )

        if action.cooling_period_seconds < 60:
            raise RuntimeError(
                "AI cooling period is below 60 seconds."
            )
