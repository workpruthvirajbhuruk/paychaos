# PayInChaos

### Autonomous Switch Resilience & Chaos Engineering for Payment Systems

> **Inject failures. Detect degradation. Diagnose the cause. Safely reroute traffic. Verify recovery.**

PayInChaos is an autonomous payment-switch resilience engine built for **AI-driven revenue recovery**.

It simulates failures across multiple Indian bank/payment switches, observes real transaction telemetry, diagnoses the failure, proposes a bounded recovery action, validates that action through deterministic guardrails, reroutes a controlled percentage of traffic, and finally verifies whether the intervention actually restored successful payments.

The key design principle is simple:

**AI recommends. Guardrails authorize. Router executes. Telemetry verifies.**

---

## Why PayInChaos?

Payment failures are not always binary outages.

A payment switch can experience:

* Gateway timeouts
* Issuer unavailability
* OTP completion failures
* Sudden latency spikes
* Bank-side degradation
* Flapping or intermittent gateways
* Failures isolated to a particular payment method

A conventional router may simply send traffic elsewhere.

PayInChaos instead treats the payment system as a **closed-loop recovery system**:

```text
             ┌──────────────────────┐
             │    Payment Switch    │
             └──────────┬───────────┘
                        │
                        ▼
             ┌──────────────────────┐
             │    Chaos Engine      │
             │  Inject failure      │
             └──────────┬───────────┘
                        │
                        ▼
             ┌──────────────────────┐
             │      Telemetry       │
             │ SR / P99 / Errors    │
             └──────────┬───────────┘
                        │
                        ▼
             ┌──────────────────────┐
             │       AI Agent       │
             │ Diagnose + Recommend │
             └──────────┬───────────┘
                        │
                        ▼
             ┌──────────────────────┐
             │     Guardrails       │
             │ Validate + Bound     │
             └──────────┬───────────┘
                        │
                        ▼
             ┌──────────────────────┐
             │    Traffic Router    │
             │ Controlled rerouting │
             └──────────┬───────────┘
                        │
                        ▼
             ┌──────────────────────┐
             │     Verification     │
             │ Did recovery work?   │
             └──────────────────────┘
```

The system does **not** allow an LLM to directly control payment routing.

---

# Core Architecture

## 1. Payment Switch

A deterministic payment-switch simulator representing multiple bank destinations:

* HDFC
* ICICI
* SBI
* AXIS

Each transaction contains:

* Transaction ID
* Amount
* Payment method
* Bank
* Processing latency
* Success/failure result
* Error code

The simulator supports deterministic seeds so benchmark runs are reproducible.

---

## 2. Chaos Engine

The Chaos Engine deliberately introduces realistic payment failures.

### Supported scenarios

| Scenario               | Failure simulated                        |
| ---------------------- | ---------------------------------------- |
| `OTP_SILENT_DROP`      | OTP completion failures                  |
| `UPI_LATENCY_SPIKE`    | Severe UPI latency / gateway timeout     |
| `BIN_ISOLATED_FAILURE` | RuPay issuer failures isolated to a bank |
| `FLAPPING_GATEWAY`     | Intermittent bank-side degradation       |

This allows the recovery system to be evaluated against different failure shapes instead of a single hard-coded outage.

---

## 3. Telemetry

PayInChaos continuously evaluates transaction health using:

* Success rate
* P99 latency
* Error distribution
* Transaction counts
* Bank health
* Payment-method-specific health

An anomaly is raised when the observed system crosses configured health thresholds.

The system therefore distinguishes between:

```text
Healthy
   ↓
Degraded
   ↓
Anomaly detected
   ↓
Recovery required
```

---

# AI Agent

The AI layer is responsible for **reasoning about the failure**, not directly controlling infrastructure.

Given telemetry, the agent determines:

* What appears to be failing?
* Which bank/payment method is affected?
* What is the likely root cause?
* Which healthy bank should receive traffic?
* What payment-method scope should be affected?
* What percentage of traffic should be rerouted?
* How long should the recovery action remain active?

Example recommendation:

```text
SBI → AXIS
Scope: UPI
Traffic: 30%
Reason: Gateway timeout failures caused by elevated latency
```

---

# AI Judgment

One of the core design decisions in PayInChaos is knowing **where not to use an LLM**.

The LLM does not get unrestricted control over the payment system.

Instead:

```text
LLM
 │
 │ recommendation
 ▼
Guardrails
 │
 │ approved / clamped / blocked
 ▼
Router
 │
 │ actual traffic movement
 ▼
Telemetry
 │
 │ measured outcome
 ▼
Recovery verification
```

This separation prevents an AI-generated recommendation from becoming an unchecked production action.

### Deterministic fallback

PayInChaos also includes a deterministic reasoning path.

If Gemini is unavailable, rate-limited, or fails during execution, the system can continue through a deterministic fallback policy.

This is intentional resilience behavior.

The benchmark can also be run in strict Gemini mode, where fallback is not silently accepted.

---

# Guardrails

Every AI recovery recommendation passes through deterministic guardrails before execution.

Guardrails validate:

* Is the affected bank valid?
* Is the target bank valid?
* Is the target currently healthy?
* Is the requested scope valid?
* Is the traffic percentage within the allowed bound?
* Is the cooldown period safe?
* Has the same bank already received an intervention recently?

### Traffic limits

Recovery actions are bounded to a maximum of **40% traffic**.

The AI cannot simply decide:

```text
"Move 100% of traffic immediately."
```

Instead, the guardrail layer can reject or constrain unsafe actions.

This creates a hard boundary between probabilistic AI reasoning and deterministic operational control.

---

# Deterministic Traffic Routing

The router uses deterministic transaction bucketing to decide which transactions are rerouted.

This means a recovery rule such as:

```text
SBI → AXIS
UPI
30%
```

does not randomly change from transaction to transaction.

A transaction identifier is deterministically mapped to a routing bucket, allowing the system to consistently enforce the configured percentage.

This also makes benchmark behavior reproducible.

---

# Recovery Verification

PayInChaos does not declare recovery merely because the overall success rate looks better.

The system verifies that:

1. The approved routing rule was actually installed.
2. Transactions were actually rerouted.
3. Rerouted transactions reached the intended target bank.
4. Rerouted traffic achieved a healthy success rate.

Recovery requires the rerouted target traffic to achieve at least an **85% success rate**.

This prevents false positives such as:

```text
"Overall success rate improved, therefore recovery succeeded."
```

when the actual recovery route never carried traffic.

---

# Benchmark

The benchmark runs **1,000 synthetic transactions across four chaos scenarios**.

### Deterministic benchmark — measured results

| Scenario             | MTTD |  MTTR | Target | Rerouted |   Recovered |
| -------------------- | ---: | ----: | ------ | -------: | ----------: |
| OTP Silent Drop      | 5.0s | 12.0s | AXIS   |       44 |      ₹4,300 |
| UPI Latency Spike    | 5.0s | 12.0s | AXIS   |       40 |      ₹4,000 |
| BIN Isolated Failure | 5.0s | 12.0s | HDFC   |       41 |      ₹4,100 |
| Flapping Gateway     | 5.0s | 12.0s | AXIS   |       39 |      ₹3,800 |
| **Total**            |    — |     — | —      |  **164** | **₹16,200** |

### Overall result

```text
Scenarios recovered:       4 / 4
Recovery rate:             100%
Synthetic transactions:    1,000
Rerouted transactions:     164
Recovered synthetic transaction value:         ₹16,200
Guardrail violations:      0
MTTD:                      5.0 seconds
MTTR:                      12.0 seconds
```

These are measured simulator results from the reproducible deterministic benchmark.

---

# Example Failure → Recovery

### Before recovery

```text
SBI / UPI

Success Rate: 0.0%
P99 Latency: 4945 ms

Diagnosis:
Gateway timeout failures caused by elevated latency
```

### AI recommendation

```text
SBI → AXIS
Scope: UPI
Traffic: 30%
```

### Guardrails

```text
Decision: APPROVED
Traffic: 30% → 30%
Cooldown: 120s
```

### Execution

```text
40 transactions rerouted
40 successful reroutes
100% rerouted success rate
```

### Verification

```text
Recovery: SUCCESS
MTTD: 5s
MTTR: 12s
Recovered: ₹4,000
```

---

# Dashboard

PayInChaos includes an operator dashboard showing:

### Switch Health

```text
HDFC   HEALTHY
ICICI  HEALTHY
SBI    DEGRADED
AXIS   HEALTHY
```

### Active Chaos

Displays:

* Scenario
* Affected bank
* Payment method
* Injected latency
* Failure description

### AI + Guardrails

Displays:

* AI source
* Confidence
* Diagnosis
* Target bank
* Scope
* Traffic percentage
* Guardrail decision
* Cooldown

### Recovery

Displays:

* Recovery status
* MTTD
* MTTR
* Before/after success rate
* Recovered synthetic transaction value
* Failed amount
* Rerouted transactions
* Verification reason

Run the dashboard with:

```bash
python run_dashboard.py
```

---

# Project Structure

```text
paychaos/
│
├── README.md
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
│
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── switch.py
│   ├── chaos_engine.py
│   ├── telemetry.py
│   ├── agent.py
│   ├── guardrails.py
│   ├── router.py
│   ├── recovery.py
│   └── dashboard.py
│
├── evals/
│   ├── scenarios.json
│   ├── run_benchmark.py
│   └── test_resilience.py
│
├── test_switch.py
├── test_guardrails.py
├── test_router.py
├── test_telemetry_health.py
├── test_recovery.py
├── test_fallback_recovery.py
├── test_fallback_policy.py
├── test_health_aware_routing.py
└── test_dashboard.py
```

---

# Running Locally

## 1. Create the environment

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows:

```bash
.venv\Scripts\activate
```

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

## 3. Run tests

```bash
python -m pytest -q
```

Expected result:

```text
37 passed
```

## 4. Run the dashboard

```bash
python run_dashboard.py
```

## 5. Run the deterministic benchmark

```bash
python evals/run_benchmark.py --no-gemini
```

## 6. Run strict Gemini benchmark

If Gemini credentials and quota are available:

```bash
python evals/run_benchmark.py --gemini
```

Strict Gemini mode fails rather than silently falling back when Gemini cannot be used.

---

# Gemini Configuration

Create a local `.env` file:

```env
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-3.6-flash
```

The `.env` file is intentionally excluded from Git.

---

# Testing Philosophy

PayInChaos emphasizes **behavioral verification**, not just unit coverage.

Tests validate:

* Payment-switch behavior
* Chaos injection
* Telemetry calculations
* Health-aware target selection
* AI fallback behavior
* Guardrail enforcement
* Cooldown protection
* Deterministic routing
* Actual rerouted recovery
* Dashboard construction
* End-to-end recovery

The recovery verifier specifically checks that the approved route actually carried traffic and that the rerouted traffic succeeded.

---

# Design Principles

### 1. AI should reason, not own the payment switch

LLMs are useful for interpreting ambiguous telemetry and producing a diagnosis.

They should not directly execute unrestricted payment-routing commands.

### 2. Safety must be deterministic

Traffic caps, cooldowns, target-health checks, and routing boundaries are enforced outside the LLM.

### 3. Recovery must be measurable

A system should not claim recovery without evidence.

### 4. Failure should be reproducible

Chaos scenarios use deterministic simulation and seeded transaction generation so failures can be benchmarked repeatedly.

### 5. Fallback is a feature

An autonomous system that stops functioning because its LLM is temporarily unavailable is not resilient.

PayInChaos therefore maintains a deterministic fallback recovery path.

---

# What Makes PayInChaos Different?

Most payment-routing demos stop at:

```text
Failure detected
       ↓
Send traffic somewhere else
```

PayInChaos implements the complete control loop:

```text
Failure
  ↓
Observe
  ↓
Diagnose
  ↓
Recommend
  ↓
Validate
  ↓
Bound
  ↓
Execute
  ↓
Measure
  ↓
Verify
```

The important question is not:

> **"Can AI choose another bank?"**

It is:

> **"Can an AI-assisted system safely recover payment traffic and prove that its intervention actually worked?"**

PayInChaos is designed around that question.

---

# Status

**Core implementation complete.**

Current verified deterministic benchmark:

```text
✓ 4/4 recovery scenarios
✓ 1,000 synthetic transactions
✓ 164 actual reroutes
✓ ₹16,200 synthetic transaction value recovered
✓ 100% scenario recovery
✓ 0 guardrail violations
✓ 5s MTTD
✓ 12s MTTR
✓ 37 automated tests passing
```

---

## Built for the Razorpay AI Builder Opportunity

**Focus:** AI-assisted payment reliability, autonomous recovery, and safe system control

PayInChaos demonstrates how AI can be placed inside a controlled operational loop where **reasoning is probabilistic, execution is deterministic, and recovery is evidence-based.**
