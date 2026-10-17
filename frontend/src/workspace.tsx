import { useCallback, useEffect, useState, type FormEvent } from "react";

type Tab = "command" | "sales" | "memory" | "security" | "calendar";
type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
type RecordData = Record<string, JsonValue>;
type JsonObject = { [key: string]: JsonValue };

function parseJsonObject(source: string): JsonObject {
  const value: unknown = JSON.parse(source);
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Evidence must be a JSON object");
  }
  return value as JsonObject;
}

const tabs: { id: Tab; title: string }[] = [
  { id: "command", title: "Command" },
  { id: "sales", title: "Sales" },
  { id: "memory", title: "Memory & tools" },
  { id: "security", title: "Security & catalog" },
  { id: "calendar", title: "Calendar" },
];

export function Workspace() {
  const [token, setToken] = useState(() => sessionStorage.getItem("finesse-token") ?? "");
  const [tab, setTab] = useState<Tab>("command");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [data, setData] = useState<RecordData>({});
  const [busy, setBusy] = useState(false);

  const request = useCallback(async (path: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    headers.set("Content-Type", "application/json");
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const raw = await fetch(path, { ...init, headers }).then(async (response) => ({
      response,
      body: await response.text(),
    }));
    let payload: RecordData = {};
    if (raw.body) {
      try {
        payload = JSON.parse(raw.body) as RecordData;
      } catch {
        throw new Error("Server returned a non-JSON response");
      }
    }
    if (!raw.response.ok) {
      throw new Error(typeof payload.detail === "string" ? payload.detail : `Request failed (${raw.response.status})`);
    }
    return payload;
  }, [token]);

  const load = useCallback(async (activeTab: Tab) => {
    if (!token) return;
    setError("");
    try {
      const paths: Record<Tab, string[]> = {
        command: ["/api/command/overview", "/api/v1/services"],
        sales: ["/api/v1/leads", "/api/v1/campaigns", "/api/v1/email/messages"],
        memory: ["/api/v1/memory/patterns", "/api/tools", "/api/v1/security/tools"],
        security: ["/api/v1/catalog/repositories", "/api/v1/security/tools", "/api/v1/audit-logs"],
        calendar: ["/api/v1/calendar/meetings", "/api/v1/calendar/slots"],
      };
      const results = await Promise.all(paths[activeTab].map(async (path) => {
        try {
          return [path, await request(path)] as const;
        } catch (cause) {
          return [path, { unavailable: cause instanceof Error ? cause.message : "Unavailable" }] as const;
        }
      }));
      setData(Object.fromEntries(results));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load workspace");
    }
  }, [request, token]);

  useEffect(() => { void load(tab); }, [load, tab]);

  async function submit(event: FormEvent<HTMLFormElement>, endpoint: string, body: Record<string, JsonValue>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await request(endpoint, { method: "POST", body: JSON.stringify(body) });
      setNotice(JSON.stringify(result, null, 2));
      await load(tab);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await request("/api/v1/auth/login", {
        method: "POST", body: JSON.stringify({ email, password }),
      });
      const issued = result.access_token;
      if (typeof issued !== "string") throw new Error("Authentication response did not include a token");
      sessionStorage.setItem("finesse-token", issued);
      setToken(issued);
      setPassword("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    sessionStorage.removeItem("finesse-token");
    setToken("");
    setData({});
  }

  if (!token) {
    return <main className="login-wrap">
      <form className="login-card" onSubmit={login}>
        <span className="eyebrow">SASTRAVA · FINESSE</span>
        <h1>Operator workspace</h1>
        <p>Sign in with your FINESSE account. The session token stays in this browser tab.</p>
        <label htmlFor="email">Email</label>
        <input id="email" autoComplete="username" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        <label htmlFor="password">Password</label>
        <input id="password" autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <Status error={error} notice="" />
      </form>
    </main>;
  }

  return <main className="app-shell">
    <header className="topbar">
      <a className="wordmark" href="/workspace/">FINESSE</a>
      <span className="status-badge">Tenant-aware · review first</span>
      <button className="quiet" onClick={logout}>Sign out</button>
    </header>
    <div className="layout">
      <nav aria-label="Workspace sections" className="sidebar">
        {tabs.map((item) => <button key={item.id} className={tab === item.id ? "nav-item active" : "nav-item"}
          aria-current={tab === item.id ? "page" : undefined} onClick={() => setTab(item.id)}>
          {item.title}
        </button>)}
        <a className="nav-link" href="/">Classic dashboard</a>
        <a className="nav-link" href="/command">Command dashboard</a>
      </nav>
      <section className="content">
        <div className="page-heading">
          <div><span className="eyebrow">CONTROL PLANE</span><h1>{tabs.find((item) => item.id === tab)?.title}</h1></div>
          <button className="quiet" onClick={() => void load(tab)}>Refresh</button>
        </div>
        <Status error={error} notice={notice} />
        {tab === "command" && <CommandView data={data} submit={submit} busy={busy} />}
        {tab === "sales" && <SalesView data={data} submit={submit} busy={busy} />}
        {tab === "memory" && <MemoryView data={data} submit={submit} busy={busy} />}
        {tab === "security" && <SecurityView data={data} submit={submit} busy={busy} />}
        {tab === "calendar" && <CalendarView data={data} submit={submit} busy={busy} />}
      </section>
    </div>
  </main>;
}

function Status({ error, notice }: { error: string; notice: string }) {
  return <div aria-live="polite" className="status-area">
    {error && <p className="alert error">{error}</p>}
    {notice && <pre className="alert success">{notice}</pre>}
  </div>;
}

function DataCard({ title, value }: { title: string; value: JsonValue | undefined }) {
  return <article className="card">
    <h2>{title}</h2>
    <pre>{value === undefined ? "No data loaded." : JSON.stringify(value, null, 2)}</pre>
  </article>;
}

function CommandView({ data, submit, busy }: ViewProps) {
  return <>
    <form className="card form-grid" onSubmit={(event) => void submit(event, "/api/v1/orchestra/conjunction", {
      command: String(new FormData(event.currentTarget).get("command") ?? ""),
    })}>
      <h2>Review-only conjunction</h2>
      <label htmlFor="directive">Directive</label>
      <textarea id="directive" name="command" required minLength={3} maxLength={4000} />
      <button disabled={busy}>Build plan</button>
      <p className="hint">Plans do not execute external side effects.</p>
    </form>
    <DataCard title="System overview" value={data["/api/command/overview"]} />
    <DataCard title="Service catalog" value={data["/api/v1/services"]} />
  </>;
}

function SalesView({ data, submit, busy }: ViewProps) {
  return <>
    <form className="card form-grid" onSubmit={(event) => void submit(event, "/api/v1/leads/generate", {
      service_id: String(new FormData(event.currentTarget).get("service_id") ?? ""),
      geography: String(new FormData(event.currentTarget).get("geography") ?? ""),
      count: Number(new FormData(event.currentTarget).get("count") ?? 5),
    })}>
      <h2>Generate sandbox leads</h2>
      <label htmlFor="service">Service line</label><input id="service" name="service_id" defaultValue="software_development" required />
      <label htmlFor="geography">Geography</label><input id="geography" name="geography" defaultValue="Sandbox" required />
      <label htmlFor="count">Count (1–100)</label><input id="count" name="count" type="number" min="1" max="100" defaultValue="5" required />
      <button disabled={busy}>Generate synthetic records</button>
    </form>
    <form className="card form-grid" onSubmit={(event) => void submit(event, "/api/v1/privacy/consent", {
      contact_id: String(new FormData(event.currentTarget).get("contact_id") ?? ""),
      purpose: String(new FormData(event.currentTarget).get("purpose") ?? ""),
      consented: true,
      evidence_reference: String(new FormData(event.currentTarget).get("evidence") ?? ""),
    })}>
      <h2>Record explicit consent</h2>
      <label htmlFor="consent-contact">Contact ID</label><input id="consent-contact" name="contact_id" required />
      <label htmlFor="consent-purpose">Purpose</label>
      <select id="consent-purpose" name="purpose" defaultValue="email_campaign">
        <option value="email_campaign">Email campaign</option>
        <option value="email_marketing">Email marketing</option>
        <option value="voice_call">Voice call</option>
        <option value="lead_enrichment">Lead enrichment</option>
        <option value="calendar_sync">Calendar sync</option>
      </select>
      <label htmlFor="consent-evidence">Evidence reference (no sensitive content)</label>
      <input id="consent-evidence" name="evidence" required maxLength={500} />
      <label className="check"><input type="checkbox" required /> I verified the consent evidence and scope.</label>
      <button disabled={busy}>Record consent</button>
    </form>
    <form className="card form-grid" onSubmit={(event) => void submit(event, "/api/v1/email/generate", {
      lead_id: String(new FormData(event.currentTarget).get("lead_id") ?? ""),
      service_id: String(new FormData(event.currentTarget).get("service_id") ?? ""),
    })}>
      <h2>Draft an email</h2>
      <label htmlFor="draft-lead">Lead ID</label><input id="draft-lead" name="lead_id" required />
      <label htmlFor="draft-service">Service ID</label><input id="draft-service" name="service_id" required />
      <button disabled={busy}>Create reviewable draft</button>
    </form>
    <form className="card form-grid" onSubmit={(event) => void submit(event, "/api/v1/email/send", {
      message_id: String(new FormData(event.currentTarget).get("message_id") ?? ""),
      idempotency_key: String(new FormData(event.currentTarget).get("idempotency_key") ?? ""),
      consent_confirmed: true,
    })}>
      <h2>Send an approved email</h2>
      <label htmlFor="send-message">Draft message ID</label><input id="send-message" name="message_id" required />
      <label htmlFor="send-idempotency">Unique idempotency key</label><input id="send-idempotency" name="idempotency_key" required maxLength={200} />
      <label className="check"><input type="checkbox" required /> I verified current consent and intend to send this message.</label>
      <button disabled={busy}>Send (provider flags and eligibility still enforced)</button>
    </form>
    <form className="card form-grid" onSubmit={(event) => void submit(event, "/api/v1/voice/calls", {
      lead_id: String(new FormData(event.currentTarget).get("lead_id") ?? ""),
      service_id: String(new FormData(event.currentTarget).get("service_id") ?? ""),
      command: String(new FormData(event.currentTarget).get("command") ?? ""),
      confirmed: true,
      consent_confirmed: true,
      approved_script: true,
    })}>
      <h2>Explicit voice command</h2>
      <label htmlFor="voice-lead">Lead ID</label><input id="voice-lead" name="lead_id" required />
      <label htmlFor="voice-service">Service ID</label><input id="voice-service" name="service_id" required />
      <label htmlFor="voice-command">Explicit command</label><input id="voice-command" name="command" required maxLength={1000} />
      <label className="check"><input type="checkbox" required /> Confirm this voice call and verify current calling consent.</label>
      <label className="check"><input type="checkbox" required /> Use the fixed approved AI disclosure and opt-out script.</label>
      <button disabled={busy}>Request call (provider remains opt-in)</button>
    </form>
    <form className="card form-grid" onSubmit={(event) => void submit(
      event,
      `/api/v1/leads/${encodeURIComponent(String(new FormData(event.currentTarget).get("lead_id") ?? ""))}/enrich`,
      { consent_confirmed: true },
    )}>
      <h2>Consent-gated domain enrichment</h2>
      <label htmlFor="enrich-lead">Lead ID</label><input id="enrich-lead" name="lead_id" required />
      <label className="check"><input type="checkbox" required /> I verified the lead-enrichment consent.</label>
      <button disabled={busy}>Enrich domain only</button>
    </form>
    <form className="card form-grid" onSubmit={async (event) => {
      const form = event.currentTarget;
      await submit(event, "/api/v1/settings/provider-secrets", {
        name: String(new FormData(form).get("name") ?? ""),
        secret: String(new FormData(form).get("secret") ?? ""),
      });
      form.reset();
    }}>
      <h2>Encrypted provider secret</h2>
      <label htmlFor="provider-secret-name">Credential</label>
      <select id="provider-secret-name" name="name" defaultValue="smtp_password">
        <option value="smtp_password">SMTP password</option>
        <option value="email_webhook_token">Email provider token</option>
        <option value="twilio_auth_token">Twilio auth token</option>
        <option value="enrichment_api_token">Enrichment token</option>
        <option value="calendar_api_token">Calendar token</option>
        <option value="email_webhook_signing_secret">Email webhook HMAC key</option>
        <option value="voice_webhook_signing_secret">Voice webhook HMAC key</option>
      </select>
      <label htmlFor="provider-secret">Secret value</label>
      <input id="provider-secret" name="secret" type="password" autoComplete="new-password" required maxLength={4096} />
      <button disabled={busy}>Store encrypted secret</button>
      <p className="hint">CEO/COO only. The API never returns or logs the plaintext value.</p>
    </form>
    <DataCard title="Leads" value={data["/api/v1/leads"]} />
    <DataCard title="Campaigns" value={data["/api/v1/campaigns"]} />
    <DataCard title="Email drafts" value={data["/api/v1/email/messages"]} />
    <p className="hint">Live outreach requires explicit consent, provider configuration, approval, and separate opt-in flags.</p>
  </>;
}

function MemoryView({ data, submit, busy }: ViewProps) {
  return <>
    <form className="card form-grid" onSubmit={(event) => void submit(event, "/api/v1/memory/patterns", {
      pattern: String(new FormData(event.currentTarget).get("pattern") ?? ""),
      human_confirmed: true,
    })}>
      <h2>Save a reviewed pattern</h2>
      <label htmlFor="pattern">Pattern</label><textarea id="pattern" name="pattern" required minLength={1} maxLength={4000} />
      <label className="check"><input type="checkbox" required /> I confirm this pattern is safe to remember.</label>
      <button disabled={busy}>Save pattern</button>
    </form>
    <DataCard title="Memory patterns" value={data["/api/v1/memory/patterns"]} />
    <DataCard title="Permitted MCP tools" value={data["/api/tools"]} />
    <DataCard title="Registered security tools" value={data["/api/v1/security/tools"]} />
  </>;
}

function SecurityView({ data, submit, busy }: ViewProps) {
  const [evidenceError, setEvidenceError] = useState("");
  return <>
    <article className="card">
      <h2>Safety controls</h2>
      <p>Security scans are authorization-gated dry-run plans. The worker never invokes arbitrary scanner commands.</p>
      <form onSubmit={(event) => {
        if (!window.confirm("Activate the platform emergency stop?")) {
          event.preventDefault();
          return;
        }
        void submit(event, "/api/v1/admin/emergency-stop", {});
      }}>
        <button className="danger" disabled={busy}>Emergency stop…</button>
      </form>
    </article>
    <form className="card form-grid" onSubmit={(event) => {
      event.preventDefault();
      const form = new FormData(event.currentTarget);
      try {
        const evidence = parseJsonObject(String(form.get("evidence") ?? "{}"));
        setEvidenceError("");
        void submit(event, "/api/v1/catalog/repositories/certify", {
          full_name: String(form.get("full_name") ?? ""),
          evidence,
        });
      } catch (cause) {
        setEvidenceError(cause instanceof Error ? cause.message : "Invalid evidence JSON");
      }
    }}>
      <h2>Review catalog evidence</h2>
      <label htmlFor="repository-name">Public repository (owner/name)</label>
      <input id="repository-name" name="full_name" pattern="[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+" required />
      <label htmlFor="repository-evidence">Evidence JSON</label>
      <textarea id="repository-evidence" name="evidence" defaultValue="{}" required />
      {evidenceError && <p className="alert error" role="alert">{evidenceError}</p>}
      <button disabled={busy}>Evaluate evidence gates</button>
      <p className="hint">All certification remains review-only; supplied evidence never auto-approves a repository.</p>
    </form>
    <DataCard title="Repository catalog" value={data["/api/v1/catalog/repositories"]} />
    <DataCard title="Security tooling" value={data["/api/v1/security/tools"]} />
    <DataCard title="Audit log" value={data["/api/v1/audit-logs"]} />
  </>;
}

function CalendarView({ data, submit, busy }: ViewProps) {
  return <>
    <form className="card form-grid" onSubmit={(event) => {
      const form = new FormData(event.currentTarget);
      const syncConfirmed = form.get("sync_confirmed") === "on";
      void submit(event, "/api/v1/calendar/meetings", {
        subject: String(form.get("subject") ?? ""),
        attendee: String(form.get("attendee") ?? ""),
        start: new Date(String(form.get("start") ?? "")).toISOString(),
        end: new Date(String(form.get("end") ?? "")).toISOString(),
        contact_id: String(form.get("contact_id") ?? ""),
        idempotency_key: String(form.get("idempotency_key") ?? ""),
        sync_confirmed: syncConfirmed,
      });
    }}>
      <h2>Create local calendar invite</h2>
      <label htmlFor="meeting-subject">Subject</label><input id="meeting-subject" name="subject" required maxLength={200} />
      <label htmlFor="attendee">Attendee email</label><input id="attendee" name="attendee" type="email" required />
      <label htmlFor="start">Start (timezone required)</label><input id="start" name="start" type="datetime-local" required />
      <label htmlFor="end">End (timezone required)</label><input id="end" name="end" type="datetime-local" required />
      <label htmlFor="calendar-contact">Consenting contact ID (external sync only)</label><input id="calendar-contact" name="contact_id" />
      <label htmlFor="calendar-idempotency">Idempotency key (external sync only)</label><input id="calendar-idempotency" name="idempotency_key" maxLength={200} />
      <label className="check"><input type="checkbox" name="sync_confirmed" /> I explicitly request external calendar sync.</label>
      <button disabled={busy}>Create invite</button>
      <p className="hint">Local ICS generation only. External calendar sync is a separate opt-in.</p>
    </form>
    <DataCard title="Meetings" value={data["/api/v1/calendar/meetings"]} />
    <DataCard title="Provider availability" value={data["/api/v1/calendar/slots"]} />
  </>;
}

type ViewProps = {
  data: Record<string, JsonValue>;
  submit: (event: FormEvent<HTMLFormElement>, endpoint: string, body: Record<string, JsonValue>) => Promise<void>;
  busy: boolean;
};
