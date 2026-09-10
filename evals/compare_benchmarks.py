"""Compare reproducible Gemini and deterministic benchmark results."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

GEMINI_FILE = ROOT / "benchmark_results_gemini.json"
FALLBACK_FILE = ROOT / "benchmark_results_fallback.json"


def load_result(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def average(
    values: list[float | int | None],
) -> float | None:
    valid = [
        float(value)
        for value in values
        if value is not None
    ]

    if not valid:
        return None

    return sum(valid) / len(valid)


def main() -> None:
    if not GEMINI_FILE.exists():
        raise FileNotFoundError(
            f"Missing {GEMINI_FILE}. Run the Gemini benchmark first."
        )

    if not FALLBACK_FILE.exists():
        raise FileNotFoundError(
            f"Missing {FALLBACK_FILE}. Run the fallback benchmark first."
        )

    gemini = load_result(GEMINI_FILE)
    fallback = load_result(FALLBACK_FILE)

    assert gemini["seed"] == fallback["seed"]
    assert (
        gemini["total_transactions"]
        == fallback["total_transactions"]
    )

    gemini_scenarios = {
        item["scenario"]: item
        for item in gemini["scenarios"]
    }

    fallback_scenarios = {
        item["scenario"]: item
        for item in fallback["scenarios"]
    }

    scenarios = list(gemini_scenarios)

    print()
    print("PAYINCHAOS AI JUDGMENT BENCHMARK")
    print("=" * 100)

    print("Seed:", gemini["seed"])
    print(
        "Transactions:",
        gemini["total_transactions"],
    )

    print()
    print(
        f"{'Scenario':<24}"
        f"{'Gemini SR':>12}"
        f"{'Fallback SR':>14}"
        f"{'Gemini ₹':>14}"
        f"{'Fallback ₹':>16}"
    )

    print("-" * 100)

    for scenario in scenarios:
        g = gemini_scenarios[scenario]
        f = fallback_scenarios[scenario]

        g_sr = "RECOVERED" if g["recovered"] else "FAILED"
        f_sr = "RECOVERED" if f["recovered"] else "FAILED"

        print(
            f"{scenario:<24}"
            f"{g_sr:>12}"
            f"{f_sr:>14}"
            f"{g['recovered_amount_rupees']:>14,.2f}"
            f"{f['recovered_amount_rupees']:>16,.2f}"
        )

    gemini_mttd = average(
        [
            item["mttd_seconds"]
            for item in gemini["scenarios"]
        ]
    )

    fallback_mttd = average(
        [
            item["mttd_seconds"]
            for item in fallback["scenarios"]
        ]
    )

    gemini_mttr = average(
        [
            item["mttr_seconds"]
            for item in gemini["scenarios"]
        ]
    )

    fallback_mttr = average(
        [
            item["mttr_seconds"]
            for item in fallback["scenarios"]
        ]
    )

    print("-" * 100)

    print()
    print("RECOVERY")
    print("-" * 100)
    print(
        "Gemini recovery rate:",
        f"{gemini['recovery_rate_percent']:.1f}%",
    )
    print(
        "Fallback recovery rate:",
        f"{fallback['recovery_rate_percent']:.1f}%",
    )

    print()
    print("TIME TO RECOVERY")
    print("-" * 100)
    print(
        "Gemini average MTTD:",
        f"{gemini_mttd:.2f}s",
    )
    print(
        "Fallback average MTTD:",
        f"{fallback_mttd:.2f}s",
    )
    print(
        "Gemini average MTTR:",
        f"{gemini_mttr:.2f}s",
    )
    print(
        "Fallback average MTTR:",
        f"{fallback_mttr:.2f}s",
    )

    print()
    print("REVENUE RECOVERY")
    print("-" * 100)
    print(
        "Gemini recovered:",
        f"₹{gemini['total_recovered_amount_rupees']:,.2f}",
    )
    print(
        "Fallback recovered:",
        f"₹{fallback['total_recovered_amount_rupees']:,.2f}",
    )

    print()
    print("GUARDRAIL SAFETY")
    print("-" * 100)
    print(
        "Gemini interventions:",
        gemini["guardrail_interventions"],
    )
    print(
        "Fallback interventions:",
        fallback["guardrail_interventions"],
    )

    print()
    print("ARCHITECTURAL CONCLUSION")
    print("-" * 100)

    fallback_survives = (
        fallback["recovery_rate_percent"] == 100.0
    )

    if fallback_survives:
        print(
            "PASS: Recovery remains operational without Gemini."
        )
        print(
            "PASS: LLM is an intelligence layer, not a recovery dependency."
        )
    else:
        print(
            "WARNING: Deterministic fallback did not recover every scenario."
        )

    print()
    print("=" * 100)


if __name__ == "__main__":
    main()
