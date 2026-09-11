# PayInChaos

### Autonomous Payment-Switch Resilience & Chaos Engineering for AI-Assisted Payment Recovery

> **Inject failures. Detect degradation. Diagnose the cause. Safely reroute bounded traffic. Verify recovery. Stop when the fallback fails.**

PayInChaos is an AI-assisted payment-switch resilience engine that explores a practical question:

> **Can an AI-assisted system recover payment traffic safely without giving an LLM unrestricted control over payment routing?**

It simulates failures across multiple bank/payment switches, observes transaction telemetry, uses Gemini to diagnose the failure and recommend a bounded recovery action, validates that recommendation through deterministic guardrails, executes controlled traffic rerouting, and independently verifies whether the intervention actually worked.

The central architecture is:

**AI recommends. Guardrails authorize. Router executes. Telemetry verifies. Recovery Controller decides whether autonomy continues.**

No real payments or customer funds are involved. All transaction amounts are synthetic.

---

## Why PayInChaos?

Payment failures are rarely just "the bank is down."

A payment switch can experience:

- Gateway timeouts
- Issuer unavailability
- OTP completion failures
- Severe latency spikes
- Bank-side degradation
- Flapping/intermittent gateways
- Payment-method-specific failures
- A recovery target failing while recovery is already in progress

A naive autonomous router might detect the first failure and immediately keep moving traffic from one bank to another.

PayInChaos treats recovery as a **closed-loop control problem**:

```text
                    ┌──────────────────────┐
                    │    Payment Switch    │
                    │   Synthetic traffic  │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │    Chaos Engine      │
                    │   Inject failure     │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │      Telemetry       │
                    │ SR / P99 / Errors    │
                    │ Bank + method health │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │       AI Agent       │
                    │ Diagnose + Recommend │
                    └──────────┬───────────┘
                               │ recommendation
                               ▼
                    ┌──────────────────────┐
                    │     Guardrails       │
                    │ Validate + Bound     │
                    └──────────┬───────────┘
                               │ approved action
                               ▼
                    ┌──────────────────────┐
                    │    Traffic Router   │
                    │ Controlled rerouting │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │     Verification     │
                    │ Actual target traffic │
                    │ + success measurement│
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Recovery Controller  │
                    │ Continue / Stop /    │
                    │ Escalate to operator │
                    └──────────────────────┘
```

The key safety boundary is deliberate:

> **The LLM never directly controls the payment router.**

---

# Architecture

## 1. Payment Switch

`app/switch.py` implements a deterministic payment-switch simulator representing multiple bank destinations:

- HDFC
- ICICI
- SBI
- AXIS

Each synthetic transaction contains:

- Transaction ID
- Amount
- Payment method
- Bank
- Processing latency
- Success/failure result
- Error code

Seeded transaction generation makes scenarios reproducible.

---

## 2. Chaos Engine

`app/chaos_engine.py` deliberately introduces controlled payment failures.

### Supported scenarios

| Scenario | Failure simulated |
|---|---|
| `OTP_SILENT_DROP` | OTP completion failures |
| `UPI_LATENCY_SPIKE` | Severe UPI latency / gateway timeout |
| `BIN_ISOLATED_FAILURE` | RuPay issuer failures isolated to a bank |
| `FLAPPING_GATEWAY` | Intermittent bank-side degradation |
| `CASCADING_SWITCH_FAILURE` | Primary switch fails, recovery target subsequently fails |

The fifth scenario is different from the others.

It is a **controlled two-stage resilience test**:

```text
SBI fails
   │
   ▼
AI recommends AXIS
   │
   ▼
Guardrails approve bounded rerouting
   │
   ▼
Traffic begins moving toward AXIS
   │
   ▼
AXIS is deliberately degraded
   │
   ▼
Telemetry / chaos state detects target failure
   │
   ▼
Recovery Controller clears autonomous routing
   │
   ▼
Operator escalation
```

The purpose is not to maximize automation.

The purpose is to prove that the system knows **when to stop being autonomous**.

For this controlled scenario, AXIS is intentionally supplied as the allowed recovery target. Gemini still performs the diagnosis and recommendation; the scenario constrains the candidate target so the cascade is reproducible and tests the safety boundary deterministically.

---

# 3. Telemetry

`app/telemetry.py` continuously evaluates transaction health using:

- Success rate
- P99 latency
- Error distribution
- Transaction counts
- Bank health
- Payment-method-specific health

The system moves through:

```text
Healthy
   ↓
Degraded
   ↓
Anomaly detected
   ↓
Recovery required
```

Telemetry is also used after an intervention.

This matters because a recovery action is not considered successful simply because the overall system looks better.

The system asks:

> **Did the traffic we actually rerouted reach the intended target, and did that traffic succeed?**

---

# 4. AI Agent

`app/agent.py` is responsible for **reasoning about the failure**, not executing infrastructure changes.

Given telemetry, the AI determines:

- What appears to be failing?
- Which bank/payment method is affected?
- What is the likely cause?
- Which allowed healthy bank should receive traffic?
- What payment-method scope should be affected?
- What percentage of traffic should be rerouted?
- How long should the intervention remain active?

Example recommendation:

```text
Affected bank: SBI
Method: UPI
Diagnosis: gateway timeout failures caused by elevated latency

Recommendation:
Target: AXIS
Scope: UPI
Traffic: 30%
```

The AI output is treated as a **recommendation**, not an instruction to infrastructure.

---

# 5. Recovery Controller

`app/recovery.py` is the orchestration layer.

It connects:

```text
Chaos
  ↓
Observation
  ↓
AI diagnosis
  ↓
Guardrail decision
  ↓
Routing execution
  ↓
Independent verification
  ↓
Recovery outcome
```

The controller is also responsible for the autonomous safety boundary.

It can produce outcomes such as:

```text
RECOVERED
ESCALATED
```

If the recovery target becomes unhealthy during a controlled cascade, the controller:

1. Detects the target degradation.
2. Stops autonomous recovery.
3. Clears the active routing rule.
4. Records the recovery abort.
5. Records operator escalation.
6. Returns an explicit `ESCALATED` outcome.

This prevents the dangerous behavior of blindly chaining:

```text
SBI → AXIS → HDFC → ICICI → ...
```

just because the system is still trying to recover.

---

# 6. Guardrails

Every AI recovery recommendation passes through deterministic guardrails before execution.

`app/guardrails.py` validates:

- Affected bank
- Target bank
- Target health
- Payment-method scope
- Traffic percentage
- Cooldown period
- Previous interventions

Recovery traffic is bounded to a maximum of **40%**.

For example, the AI cannot directly execute:

```text
Move 100% of SBI traffic immediately.
```

Instead:

```text
AI recommendation
       ↓
Guardrails
       ├── APPROVE
       ├── CLAMP
       └── BLOCK
```

This creates a hard boundary between probabilistic reasoning and deterministic operational control.

---

# 7. Traffic Router

`app/router.py` contains the deterministic `TrafficRouter`.

The router:

- Accepts only approved guardrail decisions.
- Installs bounded routing rules.
- Uses deterministic transaction bucketing.
- Respects payment-method scope.
- Respects the configured traffic percentage.
- Does not call the LLM.
- Does not override guardrails.

For example:

```text
SBI → AXIS
UPI
30%
```

does not mean every transaction is rerouted.

A transaction ID is deterministically mapped into a routing bucket, allowing the router to consistently enforce the configured percentage.

---

# 8. Recovery Verification

PayInChaos verifies recovery using actual rerouted traffic.

Verification checks:

1. The approved routing rule was installed.
2. Transactions were actually rerouted.
3. Rerouted transactions reached the intended target.
4. The rerouted traffic achieved a healthy success rate.

Recovery requires the rerouted target traffic to achieve at least an **85% success rate**.

Therefore:

```text
Overall success rate improved
        ≠
Recovery succeeded
```

Instead:

```text
Approved route
     ↓
Actual reroutes
     ↓
Target reached
     ↓
Target traffic succeeds
     ↓
Recovery verified
```

---

# AI Safety Model

One of the core design decisions in PayInChaos is knowing **where not to use an LLM**.

The AI is useful for interpreting telemetry and producing a diagnosis.

The AI is not trusted with unrestricted operational authority.

```text
                 ┌─────────────────┐
                 │       LLM       │
                 │ Diagnose +       │
                 │ Recommend        │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │   Guardrails    │
                 │ Validate + Bound│
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │      Router     │
                 │ Execute only    │
                 │ approved action │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │    Telemetry    │
                 │ Measure outcome │
                 └────────┬────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │    Recovery     │
                 │ Continue / Stop │
                 └─────────────────┘
```

This is the project's central engineering principle:

> **Probabilistic reasoning, deterministic control, evidence-based recovery.**

---

# Gemini + Deterministic Fallback

PayInChaos supports two reasoning paths.

### Gemini mode

Gemini provides the diagnosis and recovery recommendation.

### Deterministic fallback

If Gemini is unavailable, rate-limited, or fails during execution, PayInChaos can use a deterministic recovery policy.

This prevents the resilience system itself from becoming dependent on the availability of its AI provider.

The benchmark also supports **strict Gemini mode**, where fallback is not silently accepted.

That distinction is important for evaluation:

```text
Gemini available
      ↓
Gemini diagnosis
      ↓
Benchmark records Gemini

Gemini unavailable
      ↓
Fallback diagnosis
      ↓
Benchmark records fallback

Strict Gemini mode
      ↓
Gemini unavailable
      ↓
Benchmark FAILS
```

The system never labels fallback behavior as a successful Gemini run.

---

# Audit Trail

Recovery decisions produce an immutable in-memory audit trail containing events such as:

```text
TELEMETRY
  anomaly detected

AI_AGENT
  diagnosis generated

GUARDRAILS
  recovery recommendation approved

ROUTER
  traffic rerouted

TELEMETRY
  recovery target degraded

RECOVERY_CONTROLLER
  autonomous recovery aborted

RECOVERY_CONTROLLER
  operator escalation required
```

This makes the autonomous control loop inspectable rather than opaque.

---

# Cascading Failure Demonstration

The controlled cascade scenario is one of the most important demonstrations in the project.

Run:

```bash
python run_dashboard.py --scenario cascade
```

The intended sequence is:

```text
1. SBI / UPI fails
          ↓
2. AI diagnoses the failure
          ↓
3. AI recommends AXIS
          ↓
4. Guardrails approve 30%
          ↓
5. Router begins controlled rerouting
          ↓
6. AXIS is deliberately degraded
          ↓
7. Target failure is detected
          ↓
8. Routing rule is cleared
          ↓
9. Autonomous recovery stops
          ↓
10. Operator escalation is required
```

A representative dashboard result:

```text
OPERATOR STATUS  ● DEGRADED

SBI       0.0% success    ~4.9s P99    DEGRADED
AXIS    100.0% success    ~220ms       HEALTHY

SCENARIO  CASCADING_SWITCH_FAILURE

TARGET    AXIS
SCOPE     UPI
TRAFFIC   30%

GUARDRAILS
DECISION  APPROVED

RECOVERY  FAILED

Autonomous recovery stopped:
target AXIS degraded during recovery;
operator escalation required.
```

This is intentional.

A resilient autonomous system should not interpret:

> "My first fallback failed"

as:

> "Try another fallback forever."

It should recognize the boundary of safe autonomy.

---

# Normal Failure → Recovery

Run:

```bash
python run_dashboard.py
```

A representative recovery flow:

```text
SBI / UPI
Success Rate: 0.0%
P99 Latency: ~4.9s
        ↓
AI diagnosis
        ↓
SBI → HDFC / AXIS
UPI / 30%
        ↓
Guardrails APPROVED
        ↓
Router reroutes bounded traffic
        ↓
Target traffic succeeds
        ↓
Recovery VERIFIED
```

Example measured dashboard outcome:

```text
RECOVERY        SUCCESS
MTTD            5s
MTTR            12s
BEFORE          0.0%
AFTER           100.0%

Rerouted traffic:
34 transactions
100.0% success rate
```

Exact transaction counts and synthetic values vary because the dashboard uses seeded synthetic simulation.

---

# Benchmark

The deterministic benchmark runs **1,000 synthetic transactions across four baseline chaos scenarios**.

```bash
python evals/run_benchmark.py --no-gemini
```

### Deterministic benchmark

| Scenario | MTTD | MTTR | Target | Rerouted | Synthetic value |
|---|---:|---:|---|---:|---:|
| OTP Silent Drop | 5s | 12s | AXIS | 44 | ₹4,300 |
| UPI Latency Spike | 5s | 12s | AXIS | 40 | ₹4,000 |
| BIN Isolated Failure | 5s | 12s | HDFC | 41 | ₹4,100 |
| Flapping Gateway | 5s | 12s | AXIS | 39 | ₹3,800 |
| **Total** | — | — | — | **164** | **₹16,200** |

### Verified deterministic result

```text
Scenarios recovered:              4 / 4
Recovery rate:                    100%
Synthetic transactions:           1,000
Actual rerouted transactions:     164
Synthetic transaction value:      ₹16,200
Guardrail violations:             0
MTTD:                             5.0 seconds
MTTR:                            12.0 seconds
```

These are simulator measurements.

**No real payments or customer funds are involved.**

---

# Gemini Benchmark

The benchmark can also run in strict Gemini mode:

```bash
python evals/run_benchmark.py --gemini
```

A successful Gemini run produced:

```text
OTP_SILENT_DROP
HDFC → ICICI
UPI
30%
97.7% recovered

UPI_LATENCY_SPIKE
SBI → HDFC
UPI
30%
100% recovered

BIN_ISOLATED_FAILURE
AXIS → HDFC
CARD_RUPAY
30%
100% recovered

FLAPPING_GATEWAY
ICICI → HDFC
UPI
30%
97.4% recovered
```

Overall:

```text
4 / 4 recovery scenarios
1,000 synthetic transactions
164 rerouted transactions
₹16,200 synthetic transaction value
0 guardrail violations
JSON benchmark output
```

The important point is not that Gemini always chooses the same bank as the deterministic fallback.

The important point is that:

```text
Gemini recommendation
        ↓
Guardrails
        ↓
Approved bounded action
        ↓
Deterministic router
        ↓
Measured result
```

The AI can reason differently while the operational safety boundary remains deterministic.

---

# Dashboard

PayInChaos includes an operator dashboard with four major panels.

### 01 — Switch Health

Shows:

- Bank
- Success rate
- P99 latency
- Transaction count
- Health status

### 02 — Active Chaos

Shows:

- Scenario
- Affected bank
- Payment method
- Injected latency
- Failure description

### 03 — AI + Guardrails

Shows:

- AI source
- Confidence
- Diagnosis
- Target bank
- Scope
- Traffic percentage
- Guardrail decision
- Cooldown

### 04 — Recovery

Shows:

- Recovery outcome
- MTTD
- MTTR
- Before/after success rate
- Synthetic transaction value
- Failed value
- Rerouted transactions
- Verification result
- Escalation status when autonomy stops

---

# Running Locally

## 1. Create the environment

```bash
python -m venv .venv
```

Linux/macOS/Codespaces:

```bash
source .venv/bin/activate
```

Windows:

```powershell
.venv\Scripts\activate
```

## 2. Install dependencies

```bash
pip install -r requirements.txt
```

## 3. Configure Gemini

Create `.env`:

```env
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-3.6-flash
```

`.env` is excluded from Git.

## 4. Run the full test suite

```bash
python -m pytest -q
```

Expected:

```text
38 passed
```

## 5. Run the normal dashboard

```bash
python run_dashboard.py
```

## 6. Run the cascade demonstration

```bash
python run_dashboard.py --scenario cascade
```

## 7. Run deterministic benchmark

```bash
python evals/run_benchmark.py --no-gemini
```

## 8. Run strict Gemini benchmark

```bash
python evals/run_benchmark.py --gemini
```

Strict Gemini mode fails rather than silently falling back if Gemini cannot be used.

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

# Testing Philosophy

PayInChaos emphasizes **behavioral verification**, not just unit coverage.

The test suite validates:

- Payment-switch behavior
- Chaos injection
- Telemetry calculations
- Health-aware target selection
- AI fallback behavior
- Guardrail enforcement
- Cooldown protection
- Deterministic routing
- Actual rerouted recovery
- Cascade failure handling
- Operator escalation
- Audit trail behavior
- Dashboard construction
- End-to-end recovery

Current verification:

```text
38 passed
0 failed
```

The Google GenAI deprecation warning shown in the environment is a dependency warning, not a project test failure.

---

# Design Principles

### 1. AI should reason, not own the payment switch

LLMs are useful for interpreting ambiguous telemetry and producing diagnoses.

They should not directly execute unrestricted payment-routing commands.

### 2. Safety must be deterministic

Traffic caps, cooldowns, target-health checks, and routing boundaries are enforced outside the LLM.

### 3. Recovery must be measurable

A system should not claim recovery without evidence from the actual rerouted traffic.

### 4. Failure should be reproducible

Chaos scenarios use deterministic simulation and seeded transaction generation so failures can be benchmarked repeatedly.

### 5. Fallback is a feature

The resilience system should not completely collapse because the AI provider is temporarily unavailable.

### 6. Autonomous systems need stopping rules

The goal is not maximum autonomy.

The goal is **bounded autonomy with an explicit escalation path**.

The cascade scenario exists specifically to test this principle.

---

# What Makes PayInChaos Different?

Many payment-routing demos stop at:

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
  ↓
Continue OR Stop + Escalate
```

The important question is not:

> **"Can AI choose another bank?"**

It is:

> **"Can an AI-assisted system safely recover payment traffic, prove that its intervention worked, and know when it should stop acting autonomously?"**

That is the problem PayInChaos is designed to explore.

---

# Limitations

PayInChaos is a **controlled simulation**, not a production payment gateway.

It does not connect to:

- Real bank switches
- Real customer payment instruments
- Production transaction ledgers
- Real money movement

A production implementation would additionally need concerns such as:

- Idempotency
- In-flight transaction handling
- Duplicate-payment prevention
- Gateway ambiguity
- Distributed state
- Persistent audit storage
- Authentication and authorization
- Multi-region failover
- Rate limiting
- Production observability
- Formal change management

The purpose of PayInChaos is to demonstrate the **AI control-loop and resilience architecture** in a reproducible environment.

---

# Status

**Core implementation complete and verified.**

```text
✓ AI-assisted failure diagnosis
✓ Gemini recommendation path
✓ Deterministic fallback path
✓ Deterministic guardrails
✓ Bounded traffic routing
✓ Health-aware target validation
✓ Independent recovery verification
✓ Audit trail
✓ Cascading switch failure scenario
✓ Autonomous recovery stopping rule
✓ Operator escalation
✓ 1,000 synthetic-transaction benchmark
✓ 4/4 baseline recovery scenarios
✓ 100% deterministic benchmark recovery
✓ 0 guardrail violations
✓ 5s MTTD
✓ 12s MTTR
✓ 38 automated tests passing
```

---

## Built for the Razorpay AI Builder Opportunity

**Focus:** AI-assisted payment reliability, autonomous recovery, and safe system control.

PayInChaos demonstrates how AI can be placed inside a controlled operational loop where:

**reasoning is probabilistic, execution is deterministic, recovery is evidence-based, and autonomy has a safety boundary.**
