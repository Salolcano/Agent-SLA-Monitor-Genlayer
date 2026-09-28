"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CONTRACT_ADDRESS,
  connectWallet,
  formatGen,
  parseGen,
  readActivityLog,
  readSlaInfo,
  readVerdicts,
  shortAddress,
  writeCloseReportingPhase,
  writeCloseSla,
  writeDepositBond,
  writeReportActivity,
  writeRequestJudgment,
  writeWithdrawBond,
} from "@/lib/genlayer";

type SlaInfo = {
  provider?: string;
  client?: string;
  sla_terms?: string;
  slash_bps?: string | number;
  bond_total?: string | number;
  bond_remaining?: string | number;
  is_active?: boolean;
  awaiting_judgment?: boolean;
  pending_activity_count?: string | number;
  verdict_count?: string | number;
  breach_count?: string | number;
  clean_count?: string | number;
  last_verdict_breach?: boolean;
  last_verdict_reasoning?: string;
};

export default function Page() {
  const [account, setAccount] = useState<`0x${string}` | null>(null);
  const [connecting, setConnecting] = useState(false);

  const [sla, setSla] = useState<SlaInfo | null>(null);
  const [activityLog, setActivityLog] = useState<Record<string, string>>({});
  const [verdicts, setVerdicts] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [eventId, setEventId] = useState("");
  const [activityDesc, setActivityDesc] = useState("");
  const [evidenceRef, setEvidenceRef] = useState("");
  const [bondAmount, setBondAmount] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const configured = Boolean(CONTRACT_ADDRESS);

  const loadState = useCallback(async () => {
    if (!configured) return;
    setLoading(true);
    setLoadError(null);
    try {
      const [info, log, verdictHistory] = await Promise.all([
        readSlaInfo(),
        readActivityLog(),
        readVerdicts(),
      ]);
      setSla(info as SlaInfo);
      setActivityLog(log);
      setVerdicts(verdictHistory);
    } catch (err: any) {
      setLoadError(err?.message ?? String(err));
    } finally {
      setLoading(false);
    }
  }, [configured]);

  useEffect(() => {
    loadState();
  }, [loadState]);

  async function handleConnect() {
    setConnecting(true);
    setActionError(null);
    try {
      const addr = await connectWallet();
      setAccount(addr);
    } catch (err: any) {
      setActionError(err?.message ?? String(err));
    } finally {
      setConnecting(false);
    }
  }

  async function runAction(name: string, fn: () => Promise<any>) {
    setBusyAction(name);
    setActionError(null);
    try {
      await fn();
      await loadState();
    } catch (err: any) {
      setActionError(err?.message ?? String(err));
    } finally {
      setBusyAction(null);
    }
  }

  const isProvider =
    account && sla?.provider && account.toLowerCase() === sla.provider.toLowerCase();
  const isClient =
    account && sla?.client && account.toLowerCase() === sla.client.toLowerCase();
  const isParty = isProvider || isClient;

  const activityEntries = Object.entries(activityLog).sort(
    (a, b) => Number(a[0]) - Number(b[0])
  );
  const verdictEntries = Object.entries(verdicts).sort(
    (a, b) => Number(a[0]) - Number(b[0])
  );

  return (
    <main className="shell">
      <div className="top">
        <div className="brand">
          <span className="brand-mark" />
          <h1>Agent SLA Monitor</h1>
        </div>
        {account ? (
          <button className="wallet-btn connected" disabled>
            {shortAddress(account)}
          </button>
        ) : (
          <button className="wallet-btn" onClick={handleConnect} disabled={connecting}>
            {connecting ? "Connecting..." : "Connect wallet"}
          </button>
        )}
      </div>
      <p className="tagline">
        A continuous, on-chain judge for the commitments an agent makes to another
        agent. Every interval's activity is logged here, then a GenLayer validator
        set reasons over the log against the SLA's plain-English terms and reaches
        a breach / no-breach verdict.
      </p>

      {!configured && (
        <div className="error-banner">
          No contract address configured. Deploy <code>contracts/sla_monitor.py</code>{" "}
          on GenLayer Studio Next, then set{" "}
          <code>NEXT_PUBLIC_CONTRACT_ADDRESS</code> in this project&apos;s environment
          variables and redeploy.
        </div>
      )}

      {loadError && (
        <div className="error-banner">
          Could not read contract state: {loadError}
        </div>
      )}
      {actionError && <div className="error-banner">{actionError}</div>}

      {sla && (
        <>
          <section className="panel">
            <h2>SLA overview</h2>
            <div style={{ marginBottom: 14 }}>
              <span className={`badge ${sla.is_active ? "active" : "closed"}`}>
                {sla.is_active ? "active" : "closed"}
              </span>{" "}
              {isProvider && <span className="badge role">you are the provider</span>}{" "}
              {isClient && <span className="badge role">you are the client</span>}
            </div>
            <div className="terms-box mono">{sla.sla_terms}</div>
            <div className="grid" style={{ marginTop: 16 }}>
              <div>
                <div className="stat-label">Provider</div>
                <div className="stat-value mono" style={{ fontSize: 14 }}>
                  {shortAddress(sla.provider)}
                </div>
              </div>
              <div>
                <div className="stat-label">Client</div>
                <div className="stat-value mono" style={{ fontSize: 14 }}>
                  {shortAddress(sla.client)}
                </div>
              </div>
              <div>
                <div className="stat-label">Bond remaining / total</div>
                <div className="stat-value">
                  {formatGen(sla.bond_remaining)} / {formatGen(sla.bond_total)} GEN
                </div>
              </div>
              <div>
                <div className="stat-label">Slash per breach</div>
                <div className="stat-value">
                  {sla.slash_bps ? Number(sla.slash_bps) / 100 : 0}%
                </div>
              </div>
              <div>
                <div className="stat-label">Clean intervals</div>
                <div className="stat-value clean">{String(sla.clean_count ?? 0)}</div>
              </div>
              <div>
                <div className="stat-label">Confirmed breaches</div>
                <div className="stat-value breach">
                  {String(sla.breach_count ?? 0)}
                </div>
              </div>
            </div>
          </section>

          {sla.verdict_count !== undefined && Number(sla.verdict_count) > 0 && (
            <section className="panel">
              <h2>Latest verdict</h2>
              <div className={`verdict ${sla.last_verdict_breach ? "breach" : "clean"}`}>
                <span className="verdict-label">
                  {sla.last_verdict_breach ? "Breach confirmed" : "No breach"}
                </span>
                {sla.last_verdict_reasoning}
              </div>
            </section>
          )}

          <section className="panel">
            <h2>Run the interval</h2>
            <div className="steps">
              <div className="step">
                <div className="step-num">1</div>
                <div className="step-body">
                  <div className="step-title">Deposit bond (provider only)</div>
                  <div className="step-desc">
                    The provider stakes GEN behind the SLA. A confirmed breach slashes{" "}
                    {sla.slash_bps ? Number(sla.slash_bps) / 100 : 0}% of whatever is
                    left.
                  </div>
                  <div className="row">
                    <input
                      placeholder="Amount in GEN, e.g. 5"
                      value={bondAmount}
                      onChange={(e) => setBondAmount(e.target.value)}
                      disabled={!isProvider}
                    />
                    <button
                      className="btn secondary"
                      disabled={!account || !isProvider || busyAction !== null}
                      onClick={() =>
                        runAction("bond", async () => {
                          const wei = parseGen(bondAmount);
                          if (wei <= 0n) throw new Error("Enter an amount greater than 0.");
                          await writeDepositBond(account as `0x${string}`, wei);
                          setBondAmount("");
                        })
                      }
                    >
                      {busyAction === "bond" ? "Depositing..." : "Deposit"}
                    </button>
                  </div>
                </div>
              </div>

              <div className="step">
                <div className="step-num">2</div>
                <div className="step-body">
                  <div className="step-title">
                    Report activity (provider or client)
                  </div>
                  <div className="step-desc">
                    Every entry must be attributable and verifiable: an event id the
                    other party can look up (a ticket number, request id), a plain
                    description, and an evidence reference (a URL, transcript link, or
                    hash). Free-form text alone is not accepted.
                  </div>
                  <div className="row" style={{ marginBottom: 8 }}>
                    <input
                      placeholder="Event id, e.g. ticket-482"
                      value={eventId}
                      onChange={(e) => setEventId(e.target.value)}
                      disabled={!isParty || sla.awaiting_judgment}
                    />
                    <input
                      placeholder="Evidence ref, e.g. a URL or transcript hash"
                      value={evidenceRef}
                      onChange={(e) => setEvidenceRef(e.target.value)}
                      disabled={!isParty || sla.awaiting_judgment}
                    />
                  </div>
                  <div className="row">
                    <textarea
                      rows={2}
                      placeholder="What happened: first response time, what was delivered, anything relevant to the SLA terms above."
                      value={activityDesc}
                      onChange={(e) => setActivityDesc(e.target.value)}
                      disabled={!isParty || sla.awaiting_judgment}
                    />
                    <button
                      className="btn secondary"
                      disabled={
                        !account ||
                        !isParty ||
                        busyAction !== null ||
                        Boolean(sla.awaiting_judgment) ||
                        !eventId.trim() ||
                        !activityDesc.trim() ||
                        !evidenceRef.trim()
                      }
                      onClick={() =>
                        runAction("report", async () => {
                          await writeReportActivity(
                            account as `0x${string}`,
                            eventId.trim(),
                            activityDesc.trim(),
                            evidenceRef.trim()
                          );
                          setEventId("");
                          setActivityDesc("");
                          setEvidenceRef("");
                        })
                      }
                    >
                      {busyAction === "report" ? "Logging..." : "Log activity"}
                    </button>
                  </div>
                  {sla.awaiting_judgment && (
                    <div className="step-desc" style={{ marginTop: 8 }}>
                      Reporting is closed for this interval -- request judgment below
                      before logging anything new.
                    </div>
                  )}
                </div>
              </div>

              <div className="step">
                <div className="step-num">3</div>
                <div className="step-body">
                  <div className="step-title">Close the reporting phase</div>
                  <div className="step-desc">
                    Seals this interval so judgment reads a fixed, final log --
                    required before a verdict can be requested.
                  </div>
                  <button
                    className="btn secondary"
                    disabled={
                      !account ||
                      !isParty ||
                      busyAction !== null ||
                      !sla.is_active ||
                      Boolean(sla.awaiting_judgment) ||
                      Number(sla.pending_activity_count ?? 0) === 0
                    }
                    onClick={() =>
                      runAction("closephase", () => writeCloseReportingPhase(account as `0x${string}`))
                    }
                  >
                    {busyAction === "closephase"
                      ? "Closing..."
                      : `Close reporting phase (${sla.pending_activity_count ?? 0} entries)`}
                  </button>
                </div>
              </div>

              <div className="step">
                <div className="step-num">4</div>
                <div className="step-body">
                  <div className="step-title">Request validator judgment</div>
                  <div className="step-desc">
                    Anyone can trigger this once the reporting phase is closed. A
                    random validator set reads the sealed log against the SLA terms
                    and reaches a verdict by consensus. This calls an LLM through
                    GenVM, so it can take a little while -- leave the tab open.
                  </div>
                  <button
                    className="btn"
                    disabled={!account || busyAction !== null || !sla.is_active || !sla.awaiting_judgment}
                    onClick={() => runAction("judge", () => writeRequestJudgment(account as `0x${string}`))}
                  >
                    {busyAction === "judge"
                      ? "Awaiting validator consensus..."
                      : sla.awaiting_judgment
                        ? `Request judgment (${sla.pending_activity_count ?? 0} entries sealed)`
                        : "Request judgment (close the reporting phase first)"}
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section className="panel">
            <h2>Activity log (current interval)</h2>
            <div className="log-list">
              {activityEntries.length === 0 && (
                <div className="empty">
                  Nothing logged yet this interval -- report activity above.
                </div>
              )}
              {activityEntries.map(([idx, entry]) => (
                <div className="log-entry" key={idx}>
                  <span className="log-index">#{idx}</span>
                  {entry}
                </div>
              ))}
            </div>
          </section>

          {verdictEntries.length > 0 && (
            <section className="panel">
              <h2>Verdict history</h2>
              <div className="log-list">
                {verdictEntries
                  .slice()
                  .reverse()
                  .map(([idx, raw]) => {
                    let parsed: { breach?: boolean; reasoning?: string } = {};
                    try {
                      parsed = JSON.parse(raw);
                    } catch {
                      parsed = {};
                    }
                    return (
                      <div className="log-entry" key={idx}>
                        <span className="log-index">#{idx}</span>
                        <span
                          className="verdict-label"
                          style={{
                            display: "inline",
                            color: parsed.breach ? "var(--breach)" : "var(--clean)",
                          }}
                        >
                          {parsed.breach ? "breach" : "clean"}
                        </span>{" "}
                        -- {parsed.reasoning}
                      </div>
                    );
                  })}
              </div>
            </section>
          )}

          <section className="panel">
            <h2>Close out</h2>
            <div className="row">
              <button
                className="btn danger"
                disabled={
                  !account ||
                  !isParty ||
                  !sla.is_active ||
                  busyAction !== null ||
                  Boolean(sla.awaiting_judgment) ||
                  Number(sla.pending_activity_count ?? 0) > 0
                }
                onClick={() => runAction("close", () => writeCloseSla(account as `0x${string}`))}
              >
                {busyAction === "close" ? "Closing..." : "Close SLA"}
              </button>
              <button
                className="btn secondary"
                disabled={
                  !account ||
                  !isProvider ||
                  sla.is_active ||
                  Number(sla.bond_remaining ?? 0) === 0 ||
                  busyAction !== null
                }
                onClick={() => runAction("withdraw", () => writeWithdrawBond(account as `0x${string}`))}
              >
                {busyAction === "withdraw" ? "Withdrawing..." : "Withdraw remaining bond"}
              </button>
              <button
                className="btn secondary"
                onClick={loadState}
                disabled={loading}
              >
                {loading ? "Refreshing..." : "Refresh"}
              </button>
            </div>
          </section>
        </>
      )}

      <p className="footer-note">
        Contract:{" "}
        <a
          href={`https://explorer-studio-dev.genlayer.com/address/${CONTRACT_ADDRESS}`}
          target="_blank"
          rel="noreferrer"
        >
          {shortAddress(CONTRACT_ADDRESS) || "not configured"}
        </a>{" "}
        on GenLayer Studio Next. Built for a GenLayer hackathon -- not an official
        GenLayer product.
      </p>
    </main>
  );
}
