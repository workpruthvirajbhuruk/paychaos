import { useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

const BANKS = ["HDFC", "ICICI", "SBI", "AXIS"];

function formatRupees(paise) {
  if (paise == null) return "₹0";

  return `₹${(paise / 100).toLocaleString("en-IN", {
    maximumFractionDigits: 0,
  })}`;
}

function bankStatus(bank) {
  if (!bank) return "READY";
  if (bank.healthy === false) return "DEGRADED";
  return "HEALTHY";
}

function statusClass(status) {
  if (status === "DEGRADED") return "degraded";
  return "healthy";
}

function App() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastScenario, setLastScenario] = useState("");

  async function runScenario(scenario) {
    setLoading(true);
    setError("");
    setLastScenario(scenario);

    try {
      const response = await fetch(
        `${API_BASE}/api/demo/${scenario}`,
        {
          method: "POST",
        }
      );

      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }

      const result = await response.json();
      setData(result);
    } catch (err) {
      setError(
        "Unable to connect to the PayInChaos API. Make sure FastAPI is running on port 8000."
      );
    } finally {
      setLoading(false);
    }
  }

  const hasRun = Boolean(data);

  const banks = data?.bank_health || {};
  const incident = data?.anomaly_snapshot;
  const diagnosis = data?.diagnosis;
  const action = diagnosis?.action;
  const guardrails = data?.guardrail_decision;
  const routing = data?.routing_rule;
  const verification = data?.verification;
  const metrics = data?.metrics;
  const auditTrail = data?.audit_trail || [];

  const recovered = data?.outcome === "RECOVERED";
  const escalated = data?.outcome === "ESCALATED";

  const operatorStatus = !hasRun
    ? "READY"
    : recovered
      ? "RECOVERED"
      : escalated
        ? "ESCALATED"
        : "DEGRADED";

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <div className="brand">
            <span className="brand-mark">P</span>
            <span>PAYINCHAOS</span>
          </div>

          <p className="subtitle">
            Autonomous Payment-Switch Resilience
          </p>
        </div>

        <div className="system-pill">
          <span className="pulse-dot" />
          SYSTEM ONLINE
        </div>
      </header>

      <main className="dashboard">
        <section className="hero-row">
          <div>
            <p className="eyebrow">RESILIENCE CONTROL PLANE</p>

            <h1>
              Payment infrastructure
              <br />
              under pressure.
            </h1>

            <p className="hero-copy">
              Deliberately inject failures. Let AI diagnose them.
              Keep execution bounded by deterministic safety
              controls.
            </p>
          </div>

          <div
            className={`operator-status ${
              !hasRun
                ? "ready"
                : recovered
                  ? "recovered"
                  : "degraded"
            }`}
          >
            <span className="status-label">
              OPERATOR STATUS
            </span>

            <strong>
              {operatorStatus === "READY"
                ? "● READY"
                : operatorStatus === "RECOVERED"
                  ? "● RECOVERED"
                  : operatorStatus === "ESCALATED"
                    ? "● ESCALATED"
                    : "● DEGRADED"}
            </strong>
          </div>
        </section>

        <section className="bank-grid">
          {BANKS.map((name) => {
            const bank =
              banks[`BankName.${name}`] || banks[name];

            const status = bankStatus(bank);

            return (
              <div className="bank-card" key={name}>
                <div className="bank-card-top">
                  <span className="bank-name">{name}</span>

                  <span
                    className={`bank-indicator ${statusClass(
                      status
                    )}`}
                  />
                </div>

                <div className="bank-rate">
                  {bank
                    ? `${bank.success_rate.toFixed(1)}%`
                    : "—"}
                </div>

                <div className="bank-meta">
                  <span>{status}</span>

                  <span>
                    {bank
                      ? `${bank.p99_latency_ms.toFixed(0)}ms P99`
                      : "Awaiting telemetry"}
                  </span>
                </div>
              </div>
            );
          })}
        </section>

        {error && (
          <div className="error-banner">
            <strong>CONNECTION ERROR</strong>
            <span>{error}</span>
          </div>
        )}

        {!hasRun ? (
          <section className="incident-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">SYSTEM STATE</p>

                <h2>All payment switches ready.</h2>
              </div>

              <div className="incident-badge healthy">
                NO ACTIVE INCIDENT
              </div>
            </div>

            <div className="metric-strip">
              <div>
                <span>ACTIVE CHAOS</span>
                <strong>NONE</strong>
              </div>

              <div>
                <span>AI AGENT</span>
                <strong>STANDBY</strong>
              </div>

              <div>
                <span>ROUTER</span>
                <strong>NO RULES</strong>
              </div>

              <div>
                <span>OPERATOR</span>
                <strong>READY</strong>
              </div>
            </div>
          </section>
        ) : (
          <section className="incident-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">LIVE INCIDENT</p>

                <h2>
                  {data
                    ? `${data.affected_bank} / ${
                        incident?.method || "UPI"
                      }`
                    : "Waiting for incident"}
                </h2>
              </div>

              {data && (
                <div
                  className={`incident-badge ${
                    escalated ? "danger" : "warning"
                  }`}
                >
                  {escalated
                    ? "CASCADE DETECTED"
                    : "DEGRADED"}
                </div>
              )}
            </div>

            <div className="metric-strip">
              <div>
                <span>P99 LATENCY</span>

                <strong>
                  {incident
                    ? `${incident.p99_latency_ms.toFixed(0)} ms`
                    : "—"}
                </strong>
              </div>

              <div>
                <span>SUCCESS RATE</span>

                <strong>
                  {incident
                    ? `${incident.success_rate.toFixed(1)}%`
                    : "—"}
                </strong>
              </div>

              <div>
                <span>FAILED REQUESTS</span>

                <strong>
                  {incident
                    ? incident.failed_transactions
                    : "—"}
                </strong>
              </div>

              <div>
                <span>ERROR</span>

                <strong className="mono">
                  GATEWAY_TIMEOUT
                </strong>
              </div>
            </div>
          </section>
        )}

        <section className="decision-grid">
          <div className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">AI AGENT</p>
                <h3>Diagnosis</h3>
              </div>

              {diagnosis && (
                <span className="confidence">
                  {Math.round(
                    diagnosis.confidence * 100
                  )}
                  % CONFIDENCE
                </span>
              )}
            </div>

            <div className="source-row">
              <span className="source-dot" />

              <span>
                {diagnosis?.source ||
                  "Awaiting scenario"}
              </span>
            </div>

            <p className="diagnosis">
              {diagnosis?.diagnosis ||
                "No active incident. Inject a controlled failure to generate an AI diagnosis from live telemetry."}
            </p>

            {action && (
              <div className="recommendation">
                <span>RECOMMENDED ACTION</span>

                <div className="route-line">
                  <strong>
                    {action.isolated_bank}
                  </strong>

                  <span className="arrow">→</span>

                  <strong>
                    {action.target_bank}
                  </strong>
                </div>

                <div className="recommendation-meta">
                  <span>{action.scope}</span>

                  <span>
                    {action.traffic_percentage}% TRAFFIC
                  </span>
                </div>
              </div>
            )}
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <p className="eyebrow">
                  CONTROL PLANE
                </p>

                <h3>Execution chain</h3>
              </div>
            </div>

            <div className="execution-chain">
              <div className="chain-step">
                <span className="chain-number">01</span>

                <div>
                  <strong>AI RECOMMENDATION</strong>

                  <span>
                    {diagnosis
                      ? "Reason over telemetry"
                      : "Awaiting incident"}
                  </span>
                </div>

                <span
                  className={
                    diagnosis ? "check" : "pending"
                  }
                >
                  {diagnosis ? "✓" : "—"}
                </span>
              </div>

              <div className="chain-line" />

              <div className="chain-step">
                <span className="chain-number">02</span>

                <div>
                  <strong>GUARDRAILS</strong>

                  <span>
                    {guardrails?.approved
                      ? "Action authorized"
                      : "Awaiting authorization"}
                  </span>
                </div>

                <span
                  className={
                    guardrails?.approved
                      ? "check"
                      : "pending"
                  }
                >
                  {guardrails?.approved ? "✓" : "—"}
                </span>
              </div>

              <div className="chain-line" />

              <div className="chain-step">
                <span className="chain-number">03</span>

                <div>
                  <strong>ROUTER</strong>

                  <span>
                    {routing
                      ? `${routing.traffic_percentage}% traffic shifted`
                      : "No route applied"}
                  </span>
                </div>

                <span
                  className={
                    routing ? "check" : "pending"
                  }
                >
                  {routing ? "✓" : "—"}
                </span>
              </div>

              <div className="chain-line" />

              <div className="chain-step">
                <span className="chain-number">04</span>

                <div>
                  <strong>TELEMETRY</strong>

                  <span>
                    {verification?.recovered
                      ? "Recovery verified"
                      : escalated
                        ? "Target degradation detected"
                        : hasRun
                          ? "Awaiting verification"
                          : "Monitoring system"}
                  </span>
                </div>

                <span
                  className={
                    verification?.recovered
                      ? "check"
                      : escalated
                        ? "danger-check"
                        : "pending"
                  }
                >
                  {verification?.recovered
                    ? "✓"
                    : escalated
                      ? "!"
                      : "—"}
                </span>
              </div>
            </div>
          </div>
        </section>

        <section
          className={`outcome-panel ${
            escalated ? "outcome-danger" : ""
          }`}
        >
          <div className="outcome-heading">
            <div>
              <p className="eyebrow">
                RECOVERY OUTCOME
              </p>

              <h2>
                {!hasRun
                  ? "Awaiting a controlled failure."
                  : recovered
                    ? "Recovery verified."
                    : escalated
                      ? "Autonomous recovery stopped."
                      : "Recovery pending."}
              </h2>
            </div>

            {hasRun && (
              <div
                className={`outcome-badge ${
                  recovered ? "success" : "danger"
                }`}
              >
                {recovered
                  ? "RECOVERED"
                  : "ESCALATED"}
              </div>
            )}
          </div>

          {!hasRun ? (
            <div className="recovery-stats">
              <div className="recovery-stat">
                <span>BEFORE</span>
                <strong>—</strong>
              </div>

              <div className="recovery-arrow">→</div>

              <div className="recovery-stat">
                <span>AFTER</span>
                <strong>—</strong>
              </div>

              <div className="recovery-stat">
                <span>MTTD</span>
                <strong>—</strong>
              </div>

              <div className="recovery-stat">
                <span>MTTR</span>
                <strong>—</strong>
              </div>

              <div className="recovery-stat value-stat">
                <span>
                  SYNTHETIC TRANSACTION VALUE
                </span>

                <strong>₹0</strong>
              </div>
            </div>
          ) : escalated ? (
            <div className="cascade-flow">
              <div className="cascade-node failed">
                <strong>SBI</strong>
                <span>UPI FAILED</span>
              </div>

              <div className="cascade-arrow">→</div>

              <div className="cascade-node failed">
                <strong>AXIS</strong>
                <span>TARGET DEGRADED</span>
              </div>

              <div className="cascade-arrow">→</div>

              <div className="cascade-node stopped">
                <strong>STOP</strong>
                <span>OPERATOR REQUIRED</span>
              </div>
            </div>
          ) : (
            <div className="recovery-stats">
              <div className="recovery-stat">
                <span>BEFORE</span>

                <strong>
                  {verification
                    ? `${verification.before_success_rate.toFixed(
                        1
                      )}%`
                    : "—"}
                </strong>
              </div>

              <div className="recovery-arrow">→</div>

              <div className="recovery-stat">
                <span>AFTER</span>

                <strong>
                  {verification
                    ? `${verification.after_success_rate.toFixed(
                        1
                      )}%`
                    : "—"}
                </strong>
              </div>

              <div className="recovery-stat">
                <span>MTTD</span>

                <strong>
                  {metrics
                    ? `${metrics.mttd_seconds}s`
                    : "—"}
                </strong>
              </div>

              <div className="recovery-stat">
                <span>MTTR</span>

                <strong>
                  {metrics?.mttr_seconds != null
                    ? `${metrics.mttr_seconds}s`
                    : "—"}
                </strong>
              </div>

              <div className="recovery-stat value-stat">
                <span>
                  SYNTHETIC TRANSACTION VALUE
                </span>

                <strong>
                  {formatRupees(
                    metrics?.recovered_amount_paise
                  )}
                </strong>
              </div>
            </div>
          )}

          {verification?.reason && (
            <p className="outcome-reason">
              {verification.reason}
            </p>
          )}
        </section>

        <section className="audit-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">
                IMMUTABLE AUDIT TRAIL
              </p>

              <h2>Decision history</h2>
            </div>

            <span className="audit-count">
              {auditTrail.length} EVENTS
            </span>
          </div>

          {auditTrail.length > 0 ? (
            <div className="audit-list">
              {auditTrail.map((event) => (
                <div
                  className="audit-row"
                  key={event.sequence}
                >
                  <span className="audit-number">
                    {String(event.sequence).padStart(
                      2,
                      "0"
                    )}
                  </span>

                  <span className="audit-actor">
                    {event.actor}
                  </span>

                  <strong className="audit-event">
                    {event.event_type}
                  </strong>

                  <span className="audit-detail">
                    {event.details}
                  </span>

                  <span className="audit-time">
                    t=
                    {event.timestamp_seconds.toFixed(
                      1
                    )}
                    s
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="audit-list">
              <div className="audit-row">
                <span className="audit-number">
                  00
                </span>

                <span className="audit-actor">
                  SYSTEM
                </span>

                <strong className="audit-event">
                  STANDBY
                </strong>

                <span className="audit-detail">
                  No incident has been injected. The
                  control plane is ready for a
                  controlled resilience test.
                </span>

                <span className="audit-time">
                  t=0.0s
                </span>
              </div>
            </div>
          )}
        </section>

        <section className="controls">
          <div>
            <p className="eyebrow">
              CHAOS CONTROL
            </p>

            <p className="control-copy">
              Run a controlled failure against the
              simulated payment switches.
            </p>
          </div>

          <div className="control-buttons">
            <button
              className="primary-button"
              onClick={() => runScenario("normal")}
              disabled={loading}
            >
              {loading && lastScenario === "normal"
                ? "RUNNING..."
                : "INJECT LATENCY SPIKE"}
            </button>

            <button
              className="danger-button"
              onClick={() => runScenario("cascade")}
              disabled={loading}
            >
              {loading && lastScenario === "cascade"
                ? "RUNNING..."
                : "RUN CASCADE FAILURE"}
            </button>
          </div>
        </section>
      </main>

      <footer>
        <span>PAYINCHAOS</span>

        <span>
          AI RECOMMENDS · GUARDRAILS AUTHORIZE · ROUTER
          EXECUTES · TELEMETRY VERIFIES
        </span>
      </footer>
    </div>
  );
}

export default App;