import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Brief, Company } from "../types";
import { Spinner } from "./Logo";
import { message, type Ctx } from "./ctx";

const LEVELS: Record<string, string> = { intern: "Intern", entry: "Early career", mid: "Mid-level", senior: "Senior" };
const TYPES: Record<string, string> = { full_time: "Full-time", intern: "Internship", contract: "Contract", any: "Any" };

export function BriefStep({ ctx }: { ctx: Ctx }) {
  const { state, refresh, notify, go } = ctx;
  const brief = state.brief.data;
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [link, setLink] = useState("");
  const [showBoards, setShowBoards] = useState(false);

  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [state.brief.history.length, busy]);
  useEffect(() => { api.companies().then(setCompanies).catch(() => undefined); }, []);

  async function send() {
    const message_ = text.trim();
    if (!message_ || busy) return;
    setBusy(true);
    try {
      await api.chat(message_);
      setText("");
      await refresh();
    } catch (e) {
      notify(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function patch(next: Partial<Brief>) {
    try {
      await api.saveBrief({ ...brief, ...next });
      await refresh();
    } catch (e) {
      notify(message(e));
    }
  }

  async function addBoard() {
    if (!link.trim()) return;
    try {
      const r = await api.addCompany(link.trim());
      notify(r.duplicate ? "That job board is already in the list." : "Job board added.");
      setLink("");
      setCompanies(await api.companies());
    } catch (e) {
      notify(message(e));
    }
  }

  async function dropBoard(id: number) {
    await api.removeCompany(id).catch((e) => notify(message(e)));
    setCompanies(await api.companies());
  }

  const active = companies.filter((c) => c.enabled);
  const rows: [string, string][] = [
    ["Roles", brief.roles.join(", ") || "Not set yet"],
    ["Level", LEVELS[brief.level]],
    ["Cities", brief.cities.join(", ") || "Any"],
    ["Countries", brief.countries.join(", ") || "Any"],
    ["Job type", TYPES[brief.job_type]],
    ["Remote", brief.remote_ok ? "Okay" : "No"],
  ];

  return (
    <>
      <div>
        <h2>Say what you're after.</h2>
        <p className="lede">
          Describe the job in plain English. Doorknock turns it into roles, cities, level, keywords and job type, and you can keep refining it in the chat.
        </p>
      </div>
      {!state.profile && <div className="notice">Tip: upload your resume first so the assistant can use your background.</div>}

      <div className="split">
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div className="chat" aria-live="polite">
            {state.brief.history.length === 0 && (
              <div className="bubble bot">
                What kind of job do you want? For example: “Backend roles at product companies in Bengaluru or remote in India. Nothing senior.”
              </div>
            )}
            {state.brief.history.map((m, i) => (
              <div key={i} className={"bubble " + (m.role === "user" ? "user" : "bot")}>{m.content}</div>
            ))}
            {busy && <div className="bubble bot"><Spinner /></div>}
            <div ref={end} />
          </div>
          <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <label className="sr" htmlFor="brief-msg" style={{ position: "absolute", left: -9999 }}>Message</label>
            <textarea
              id="brief-msg" className="field" rows={1} value={text} placeholder="Refine your brief…"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            />
            <button className="btn" type="submit" disabled={busy || !text.trim()} aria-label="Send">Send</button>
          </form>
        </div>

        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="mono-label">Brief · version {state.brief.version}</div>
          <div className="kv">
            {rows.map(([k, v]) => (<div key={k}><div className="k">{k}</div><div className="v">{v}</div></div>))}
          </div>
          <div>
            <div className="k" style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>Keywords</div>
            <div className="chips">
              {brief.keywords.length === 0 && <span style={{ color: "var(--muted)", fontSize: 14 }}>None yet</span>}
              {brief.keywords.map((k) => (
                <span className="chip" key={k}>{k}<button type="button" aria-label={`Remove ${k}`} onClick={() => patch({ keywords: brief.keywords.filter((x) => x !== k) })}>×</button></span>
              ))}
            </div>
          </div>
          <div>
            <div className="k" style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>Job titles that count as a match</div>
            <div className="chips">
              {(brief.title_keywords ?? []).length === 0 && <span style={{ color: "var(--muted)", fontSize: 14 }}>Any title (say what role you want to narrow it)</span>}
              {(brief.title_keywords ?? []).map((k) => (
                <span className="chip" key={k}>{k}<button type="button" aria-label={`Remove ${k}`} onClick={() => patch({ title_keywords: brief.title_keywords.filter((x) => x !== k) })}>×</button></span>
              ))}
            </div>
          </div>
          {(brief.avoid_titles ?? []).length > 0 && (
            <div>
              <div className="k" style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>Titles skipped</div>
              <div className="chips">
                {brief.avoid_titles.map((k) => (
                  <span className="chip plain" key={k}>{k}<button type="button" aria-label={`Remove ${k}`} onClick={() => patch({ avoid_titles: brief.avoid_titles.filter((x) => x !== k) })}>×</button></span>
                ))}
              </div>
            </div>
          )}
          {brief.exclude_keywords.length > 0 && (
            <div>
              <div className="k" style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>Excluded</div>
              <div className="chips">
                {brief.exclude_keywords.map((k) => (
                  <span className="chip plain" key={k}>{k}<button type="button" aria-label={`Remove ${k}`} onClick={() => patch({ exclude_keywords: brief.exclude_keywords.filter((x) => x !== k) })}>×</button></span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <button type="button" className="btn ghost small" aria-expanded={showBoards} onClick={() => setShowBoards(!showBoards)}>
          Job boards to search · {active.length}
        </button>
        {showBoards && (
          <div style={{ marginTop: 12 }}>
            <form className="composer" onSubmit={(e) => { e.preventDefault(); addBoard(); }}>
              <input className="field" inputMode="url" placeholder="Paste a company job board link" value={link} onChange={(e) => setLink(e.target.value)} />
              <button className="btn small" type="submit">Add</button>
            </form>
            <div style={{ marginTop: 8 }}>
              {active.map((c) => (
                <div className="board" key={c.id}>
                  <div className="name">{c.name}<div className="sub">{c.ats}/{c.slug}{c.last_error ? ` · ${c.last_error}` : ""}</div></div>
                  <button type="button" className="btn ghost small" onClick={() => dropBoard(c.id)} aria-label={`Remove ${c.name}`}>Remove</button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn" type="button" onClick={() => go("matches")}>Next: Scores what it finds</button>
      </div>
    </>
  );
}

