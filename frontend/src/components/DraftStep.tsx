import { useEffect, useState } from "react";
import { api } from "../api";
import type { Draft, JobDetail } from "../types";
import { Spinner } from "./Logo";
import { message, type Ctx } from "./ctx";

/** Split the body into plain text and the sentences that have evidence behind them. */
function segments(draft: Draft) {
  const parts: { text: string; ev: number | null }[] = [];
  let rest = draft.body;
  draft.evidence.forEach((e, i) => {
    const at = rest.indexOf(e.sentence);
    if (at < 0) return;
    if (at > 0) parts.push({ text: rest.slice(0, at), ev: null });
    parts.push({ text: e.sentence, ev: i });
    rest = rest.slice(at + e.sentence.length);
  });
  if (rest) parts.push({ text: rest, ev: null });
  return parts;
}

export function DraftStep({ ctx }: { ctx: Ctx }) {
  const { state, notify, refresh, go, jobId, personId } = ctx;
  const [job, setJob] = useState<JobDetail | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState<"" | "write" | "gmail" | "connect" | "save">("");
  const [sel, setSel] = useState(0);
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");

  useEffect(() => {
    setEditing(false);
    if (jobId == null) { setJob(null); setDraft(null); return; }
    api.job(jobId).then((j) => { setJob(j); setDraft(j.draft); }).catch(() => undefined);
  }, [jobId]);

  async function write() {
    if (jobId == null) return;
    setBusy("write");
    try {
      const d = await api.writeDraft(jobId, personId);
      setDraft(d);
      setSel(0);
      await refresh();
    } catch (e) {
      notify(message(e));
    } finally {
      setBusy("");
    }
  }

  async function saveEdit() {
    if (!draft) return;
    setBusy("save");
    try {
      setDraft(await api.editDraft(draft.id, subject, body));
      setEditing(false);
    } catch (e) {
      notify(message(e));
    } finally {
      setBusy("");
    }
  }

  async function toGmail() {
    if (!draft) return;
    setBusy("gmail");
    try {
      const r = await api.saveToGmail(draft.id);
      notify(r.to ? `Saved to your Gmail drafts, addressed to ${r.to}.` : "Saved to your Gmail drafts. Add the recipient there.");
      setDraft({ ...draft, in_gmail: true });
    } catch (e) {
      notify(message(e));
    } finally {
      setBusy("");
    }
  }

  async function connect() {
    setBusy("connect");
    try {
      await api.connectGmail();
      await refresh();
      notify("Gmail connected. Drafts only: Doorknock can never send.");
    } catch (e) {
      notify(message(e));
    } finally {
      setBusy("");
    }
  }

  async function copy() {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(`Subject: ${draft.subject}\n\n${draft.body}`);
      notify("Copied. Paste it into your email app.");
    } catch {
      notify("Could not copy. Select the text and copy it by hand.");
    }
  }

  const ev = draft?.evidence[sel];
  const setup = state.setup;

  return (
    <>
      <div>
        <h2>Write it from facts only.</h2>
        <p className="lede">
          Every line in the email is quoted from your resume or the job posting. The draft is saved to Gmail, and nothing is sent until you press send yourself.
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
            <div className="mono-label">Draft for</div>
            <div style={{ fontWeight: 600, fontSize: 17, marginTop: 2 }}>{job.title}</div>
            <div style={{ color: "var(--muted)", fontSize: 14 }}>
              {job.company} · {personId ? job.people.find((p) => p.id === personId)?.name ?? "chosen contact" : "no contact chosen"}
            </div>
          </div>

          {!draft ? (
            <div className="row">
              <button className="btn" type="button" disabled={busy !== ""} onClick={write}>
                {busy === "write" ? <><Spinner /> Writing</> : "Write the draft"}
              </button>
            </div>
          ) : (
            <>
              {draft.status === "needs_review" && (
                <div className="notice">
                  Review before using. {draft.problems.length > 0 ? draft.problems.join(" ") : "This draft needs a look."}
                </div>
              )}
              {draft.status === "verified" || draft.status === "in_gmail" ? (
                <div className="notice good">Every claim below traces to a verbatim quote from your resume or the posting.</div>
              ) : null}

              <div className="mail">
                <div className="head">
                  <div><span style={{ color: "var(--muted)" }}>To </span><span style={{ fontFamily: "var(--mono)", fontSize: 13 }}>{draft.to || "(no recipient yet)"}</span></div>
                  {editing ? (
                    <input className="field" aria-label="Subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
                  ) : (
                    <div style={{ fontWeight: 700, fontSize: 15 }}>{draft.subject}</div>
                  )}
                </div>
                {editing ? (
                  <div className="body"><textarea className="field" aria-label="Email body" rows={10} value={body} onChange={(e) => setBody(e.target.value)} /></div>
                ) : (
                  <div className="body">
                    {segments(draft).map((s, i) =>
                      s.ev === null ? (
                        <span key={i}>{s.text}</span>
                      ) : (
                        <button key={i} type="button" className={"hl" + (sel === s.ev ? " on" : "")} onClick={() => setSel(s.ev!)} aria-pressed={sel === s.ev}>{s.text}</button>
                      ),
                    )}
                  </div>
                )}
                <div className="foot row">
                  {editing ? (
                    <>
                      <button className="btn small" type="button" disabled={busy !== ""} onClick={saveEdit}>Save changes</button>
                      <button className="btn ghost small" type="button" onClick={() => setEditing(false)}>Cancel</button>
                    </>
                  ) : (
                    <>
                      <button className="btn ghost small" type="button" onClick={() => { setSubject(draft.subject); setBody(draft.body); setEditing(true); }}>Edit text</button>
                      <button className="btn ghost small" type="button" disabled={busy !== ""} onClick={write}>{busy === "write" ? "Writing…" : "Rewrite"}</button>
                      <button className="btn ghost small" type="button" onClick={copy}>Copy</button>
                    </>
                  )}
                </div>
              </div>

              {!editing && ev && (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div className="mono-label">Evidence · from {ev.source === "resume" ? "your resume" : "the posting"}</div>
                  <div className="quote">“{ev.quote}”</div>
                </div>
              )}

              {draft.in_gmail ? (
                <div className="notice good">Saved to your Gmail drafts. Open Gmail to review and send it yourself.</div>
              ) : !setup.gmail_connected ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {!setup.gmail_client_secret && (
                    <div className="notice">
                      Gmail is not set up yet. Save a Google OAuth “Desktop app” client file as <code>backend/data/google_client_secret.json</code>, then press Connect Gmail. You can still copy the email above.
                    </div>
                  )}
                  <div className="row">
                    <button className="btn" type="button" disabled={busy !== "" || !setup.gmail_client_secret} onClick={connect}>
                      {busy === "connect" ? <><Spinner /> Waiting for Google</> : "Connect Gmail"}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="row">
                  <button className="btn" type="button" disabled={busy !== "" || editing} onClick={toGmail}>
                    {busy === "gmail" ? <><Spinner /> Saving</> : "Save to Gmail drafts"}
                  </button>
                  <span className="mono-label" style={{ textTransform: "none", letterSpacing: 0 }}>Nothing is sent.</span>
                </div>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
