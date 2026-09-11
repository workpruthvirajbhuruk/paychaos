from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.chaos_engine import ChaosScenario
from app.recovery import RecoveryRun
from run_dashboard import (
    FakeClock,
    build_affected_traffic,
    build_baseline_traffic,
    build_controller,
)


app = FastAPI(
    title="PayInChaos API",
    description=(
        "API layer for the PayInChaos payment-switch "
        "resilience engine."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def json_value(value):
    """Convert project objects into JSON-safe values."""

    if isinstance(value, Enum):
        return value.value

    if is_dataclass(value):
        return {
            key: json_value(item)
            for key, item in asdict(value).items()
        }

    if isinstance(value, dict):
        return {
            str(key): json_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]

    if hasattr(value, "model_dump"):
        return json_value(value.model_dump())

    if hasattr(value, "__dict__"):
        return {
            str(key): json_value(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }

    return value


def build_demo_run(
    scenario: ChaosScenario,
) -> RecoveryRun:
    """Run one controlled PayInChaos demonstration scenario."""

    clock = FakeClock()
    controller = build_controller(clock)

    baseline = build_baseline_traffic()
    affected_before = build_affected_traffic(100)
    affected_after = build_affected_traffic(100)

    return controller.run_recovery_cycle(
        scenario=scenario,
        transactions_before_recovery=(
            baseline + affected_before
        ),
        transactions_after_recovery=(
            baseline + affected_after
        ),
    )


def serialize_run(run: RecoveryRun) -> dict:
    """Convert a RecoveryRun into frontend-safe JSON."""

    result = {
        "scenario": run.scenario,
        "affected_bank": run.affected_bank,
        "outcome": run.outcome,
        "escalation_required": run.escalation_required,
        "autonomous_routing_stopped": (
            run.autonomous_routing_stopped
        ),
        "chaos_event": run.chaos_event,
        "bank_health": run.bank_health,
        "anomaly_snapshot": run.anomaly_snapshot,
        "diagnosis": run.diagnosis,
        "guardrail_decision": run.guardrail_decision,
        "routing_rule": run.routing_rule,
        "verification": run.verification,
        "metrics": run.metrics,
        "audit_trail": run.audit_trail,
    }

    return json_value(result)


@app.get("/api/health")
def health() -> dict:
    """API health check."""

    return {
        "status": "ok",
        "service": "paychaos",
    }


@app.get("/api/scenarios")
def scenarios() -> dict:
    """Return the controlled scenarios available to the UI."""

    return {
        "scenarios": [
            {
                "id": "normal",
                "name": "UPI Latency Spike",
                "description": (
                    "SBI UPI latency crosses the gateway "
                    "timeout boundary and triggers controlled "
                    "recovery."
                ),
            },
            {
                "id": "cascade",
                "name": "Cascading Switch Failure",
                "description": (
                    "SBI fails, the recovery target AXIS then "
                    "fails, causing autonomous recovery to stop."
                ),
            },
        ]
    }


@app.post("/api/demo/{scenario}")
def run_demo(scenario: str) -> dict:
    """Execute one controlled PayInChaos scenario."""

    scenario_map = {
        "normal": ChaosScenario.UPI_LATENCY_SPIKE,
        "cascade": (
            ChaosScenario.CASCADING_SWITCH_FAILURE
        ),
    }

    selected = scenario_map.get(
        scenario.lower()
    )

    if selected is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Unknown scenario. "
                "Use 'normal' or 'cascade'."
            ),
        )

    run = build_demo_run(selected)

    return serialize_run(run)