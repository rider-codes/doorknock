import { useEffect, useState } from "react";
import { api } from "../api";
import type { JobDetail, Person } from "../types";
import { Spinner } from "./Logo";
import { message, type Ctx } from "./ctx";

const ROLE: Record<Person["role_type"], string> = { recruiter: "Recruiting", hiring_manager: "Hiring manager", teammate: "Teammate" };
const EMAIL: Record<Person["email_status"], string> = { verified: "✓ verified", risky: "Risky", unknown: "Unverified" };

export function PeopleStep({ ctx }: { ctx: Ctx }) {
  const { state, notify, go, jobId, personId: picked, selectPerson: setPicked } = ctx;
  const [job, setJob] = useState<JobDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [domain, setDomain] = useState("");

  async function load() {
    if (jobId == null) { setJob(null); return; }
    const j = await api.job(jobId).catch(() => null);
    setJob(j);
    setDomain(j?.domain ?? "");
    if (j && !j.people.some((p) => p.id === picked)) setPicked(j.people[0]?.id ?? null);
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [jobId]);

  async function find() {
    if (!job) return;
    setBusy(true);
    try {
      if (domain.trim() !== job.domain) await api.setDomain(job.company_id, domain);
      const people = await api.findPeople(job.id);
      setPicked(people[0]?.id ?? null);
      await load();
      if (people.length === 0) notify("No people found for that domain.");
    } catch (e) {
      notify(message(e));
    } finally {
      setBusy(false);
    }
  }

  const [mName, setMName] = useState("");
  const [mTitle, setMTitle] = useState("");
  const [mEmail, setMEmail] = useState("");
  const [adding, setAdding] = useState(false);

  async function addByHand() {
    if (!job || !mName.trim()) return;
    setAdding(true);
    try {
      const p = await api.addPerson(job.id, mName, mTitle, mEmail);
      setMName(""); setMTitle(""); setMEmail("");
      await load();
      setPicked(p.id);
    } catch (e) {
      notify(message(e));
    } finally {
      setAdding(false);
    }
  }

  const provider = state.setup.people_provider;
  const hunter = state.allowances.find((a) => a.key === "hunter");

  return (
    <>
      <div>
        <h2>Find who to write to.</h2>
        <p className="lede">
          Doorknock looks for the recruiter, hiring manager or teammate behind the job, and ranks them by relevance and by whether their email is verified.
        </p>
      </div>

      {!job ? (
        <div className="empty">
          Pick a scored job first.
          <div style={{ marginTop: 12 }}><button className="btn dark small" type="button" onClick={() => go("matches")}>Go to matches</button></div>
        </div>
      ) : (
        <>
          <div className="card">
            <div className="mono-label">For</div>
            <div style={{ fontWeight: 600, fontSize: 17, marginTop: 2 }}>{job.title}</div>
            <div style={{ color: "var(--muted)", fontSize: 14 }}>{job.company}</div>
          </div>

          {provider === "none" && (
            <div className="notice">
              No people provider is set up, so Doorknock can only use contacts printed in the posting. Paste a name below, add{" "}
              <code>PEOPLE_PROVIDER=hunter</code> and <code>HUNTER_API_KEY</code> to <code>backend/.env</code>, or use <code>PEOPLE_PROVIDER=mock</code> for fake contacts.
            </div>
          )}
          {provider === "mock" && <div className="notice">Mock provider: these contacts are fake and use undeliverable addresses.</div>}

          {hunter && (
            <div className={hunter.left <= 5 ? "notice" : "mono-label"} style={hunter.left <= 5 ? undefined : { textTransform: "none", letterSpacing: 0 }}>
              {hunter.left <= 5
                ? `Only ${hunter.left} contact tokens left ${hunter.period}. Save them for jobs you really want, or add people by hand below.`
                : `Each search uses 1 of your ${hunter.left} contact tokens left ${hunter.period}. Adding someone by hand is free unless it has to look up their email.`}
            </div>
          )}

          <form className="row" onSubmit={(e) => { e.preventDefault(); find(); }} style={{ alignItems: "flex-end" }}>
            <div style={{ flex: "1 1 220px" }}>
              <label className="mono-label" htmlFor="domain">Company website</label>
              <input id="domain" className="field" inputMode="url" placeholder="stripe.com" value={domain} onChange={(e) => setDomain(e.target.value)} style={{ marginTop: 6 }} />
            </div>
            <button className="btn" type="submit" disabled={busy || !domain.trim()}>
              {busy ? <><Spinner /> Searching</> : job.people.length ? "Search again" : "Find people"}
            </button>
          </form>

          <form className="card" onSubmit={(e) => { e.preventDefault(); addByHand(); }} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div>
              <div className="mono-label">Found someone yourself?</div>
              <div style={{ color: "var(--muted)", fontSize: 14, marginTop: 2 }}>
                Paste a name from LinkedIn or the team page. Add their email if you have it; otherwise Doorknock looks it up or guesses the usual pattern and marks it unverified.
              </div>
            </div>
            <div className="row">
              <input className="field" aria-label="Name" placeholder="Name" value={mName} onChange={(e) => setMName(e.target.value)} style={{ flex: "1 1 160px" }} />
              <input className="field" aria-label="Title" placeholder="Title (optional)" value={mTitle} onChange={(e) => setMTitle(e.target.value)} style={{ flex: "1 1 160px" }} />
              <input className="field" aria-label="Email" type="email" placeholder="Email (optional)" value={mEmail} onChange={(e) => setMEmail(e.target.value)} style={{ flex: "1 1 200px" }} />
            </div>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button className="btn dark small" type="submit" disabled={adding || !mName.trim()}>{adding ? <><Spinner /> Adding</> : "Add person"}</button>
            </div>
          </form>

          {job.people.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {job.people.map((p) => (
                <button key={p.id} type="button" className={"person" + (picked === p.id ? " on" : "")} aria-pressed={picked === p.id} onClick={() => setPicked(p.id)}>
                  <span className="rel">{p.relevance}</span>
                  <span className="info">
                    <div className="nm">{p.name}</div>
                    <div className="tt">{p.title || "Title not listed"}</div>
                    <div className="tt" style={{ color: "var(--ink)", marginTop: 4 }}>{p.why}</div>
                    <div className="em">{p.email || "No email"}</div>
                  </span>
                  <span style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-start" }}>
                    <span className="mono-label" style={{ textTransform: "none", letterSpacing: 0 }}>{ROLE[p.role_type]} · {p.source}</span>
                    <span className={"badge" + (p.email_status === "verified" ? "" : " warn")}>{EMAIL[p.email_status]}</span>
                  </span>
                </button>
              ))}
              <div className="row" style={{ justifyContent: "flex-end" }}>
                <button className="btn" type="button" disabled={picked == null} onClick={() => go("draft")}>Next: Writes the draft</button>
              </div>
            </div>
          )}

          {job.people.length === 0 && (
            <div className="row">
              <button className="btn ghost small" type="button" onClick={() => { setPicked(null); go("draft"); }}>Skip: draft without a contact</button>
            </div>
          )}
        </>
      )}
    </>
  );
}
