import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { JobDetail, JobSummary, JobView, Signal } from "../types";
import { Spinner } from "./Logo";
import { Ring, TONE_LABEL, tone } from "./Score";
import { message, type Ctx } from "./ctx";

const SIGNALS = [
  ["role", "Role fit"],
  ["profile", "Profile fit"],
  ["skills", "Skills and keywords"],
  ["location", "Location"],
  ["seniority", "Seniority"],
] as const;

const STAGE_LABEL: Record<string, string> = {
  fetch: "Reading job boards",
  filter: "Applying your rules",
  hydrate: "Reading the best matches in full",
  rank: "Ranking by fit",
  relevance: "Picking the relevant jobs",
  score: "Scoring the best matches",
};

const SOURCE: Record<string, string> = {
  greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", smartrecruiters: "SmartRecruiters", workday: "Workday", workable: "Workable",
  adzuna: "Adzuna", jooble: "Jooble", internshala: "Internshala", unstop: "Unstop", instahyre: "Instahyre", foundit: "Foundit", muse: "The Muse", remotive: "Remotive",
};

type Signals = NonNullable<JobSummary["signals"]>;

function ago(value: string): string {
  const t = Date.parse(value);
  if (Number.isNaN(t)) return value;
  const days = Math.max(0, Math.floor((Date.now() - t) / 86_400_000));
  if (days < 1) return "today";
  if (days < 31) return `${days}d ago`;
  if (days < 365) return `${Math.floor(days / 30)}mo ago`;
  return `${Math.floor(days / 365)}y ago`;
}

/** Strengths are the signals that scored well, gaps the ones that did not; the sentences are the scorer's own reasons. */
function split(signals: Signals): { strengths: string[]; gaps: string[] } {
  const rows = SIGNALS.map(([k]) => signals[k] as Signal);
  return {
    strengths: rows.filter((s) => s.score / s.max >= 0.7).map((s) => s.reason),
    gaps: rows.filter((s) => s.score / s.max <= 0.5).map((s) => s.reason),
  };
}

function Breakdown({ signals, total }: { signals: Signals; total: number }) {
  return (
    <div className="bd">
      <div className="bd-head"><span className="mono-label">Why it scored {total}</span><span className="mono-label">{total} / 100</span></div>
      {SIGNALS.map(([k, label]) => {
        const s = signals[k];
        return (
          <div className="bd-row" key={k}>
            <div className="bd-line"><span>{label}</span><span className="mono-label">{s.score}/{s.max}</span></div>
            <div className="bd-track"><div style={{ width: `${(s.score / s.max) * 100}%` }} /></div>
            <div className="bd-why">{s.reason}</div>
          </div>
        );
      })}
    </div>
  );
}

function StrengthsGaps({ signals }: { signals: Signals }) {
  const { strengths, gaps } = split(signals);
  return (
    <div className="sg">
      <div className="sg-col good">
        <div className="mono-label">Strengths</div>
        {strengths.length ? strengths.map((t) => <p key={t}>{t}</p>) : <p className="none">Nothing stands out yet.</p>}
      </div>
      <div className="sg-col gap">
        <div className="mono-label">Gaps</div>
        {gaps.length ? gaps.map((t) => <p key={t}>{t}</p>) : <p className="none">No clear gaps.</p>}
      </div>
    </div>
  );
}

function Meta({ j }: { j: JobSummary }) {
  return (
    <>
      <div className="mrow-meta">
        <span>{j.location || "Location not listed"}</span>
        {j.posted_at && <span>Posted {ago(j.posted_at)}</span>}
        <span>{j.aggregated ? "Job aggregator" : "Employer careers page"}</span>
        {j.source && <span>via {SOURCE[j.source] ?? j.source}</span>}
        {j.last_seen && <span>Checked {ago(j.last_seen)}</span>}
      </div>
      <div className="mrow-meta">
        <span>{j.people_count} contact{j.people_count === 1 ? "" : "s"}</span>
        <span>Opportunity {j.opportunity}</span>
        {j.has_draft && <span>1 draft</span>}
      </div>
    </>
  );
}

export function MatchesStep({ ctx }: { ctx: Ctx }) {
  const { state, refresh, notify, go, jobId, selectJob } = ctx;
  const [view, setView] = useState<JobView>("scored");
  const [sort, setSort] = useState<"newest" | "best">("newest");
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [open, setOpen] = useState<number | null>(null); // row expanded in the list
  const [page, setPage] = useState(false); // the full match page for jobId
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const run = state.run;
  const tokens = state.allowances.find((a) => a.key === "hunter");
  const noTokens = tokens !== undefined && tokens.left <= 0;
  const costLabel = tokens ? " · 1 token" : "";
  const running = run?.status === "running";

  const loadJobs = useCallback(async () => {
    try {
      setJobs(await api.jobs(view, sort));
    } catch (e) {
      notify(message(e));
    }
  }, [view, sort, notify]);

  // reload when the view changes or a run finishes
  useEffect(() => { loadJobs(); }, [loadJobs, run?.id, run?.status, state.counts.scored]);

  useEffect(() => {
    if (jobId == null || !page) { setDetail(null); return; }
    api.job(jobId).then(setDetail).catch(() => setDetail(null));
  }, [jobId, page, run?.status]);

  async function start(stages: string[], limit = 25) {
    try {
      await api.startRun(stages, limit);
      await refresh();
    } catch (e) {
      notify(message(e));
    }
  }

  async function dismiss(id: number) {
    await api.dismiss(id).catch((e) => notify(message(e)));
    selectJob(null);
    setPage(false);
    await refresh();
    await loadJobs();
  }

  function openPage(id: number) {
    selectJob(id);
    setPage(true);
    window.scrollTo({ top: 0 });
  }

  const [finding, setFinding] = useState<number | null>(null);

  /** One contact token buys one search for people at this job's company. */
  async function findContacts(j: { id: number; company: string; domain: string; people_count: number }) {
    if (!j.domain) {
      notify(`Add ${j.company}'s website first so contacts can be found.`);
      selectJob(j.id);
      go("people");
      return;
    }
    setFinding(j.id);
    try {
      const found = await api.findPeople(j.id);
      selectJob(j.id);
      notify(found.length ? `Found ${found.length} contact${found.length === 1 ? "" : "s"} for ${j.company}.` : `No contacts found for ${j.company}.`);
      await refresh();
      await loadJobs();
    } catch (e) {
      notify(message(e));
    } finally {
      setFinding(null);
    }
  }

  function contacts(id: number) {
    selectJob(id);
    go("people");
  }

  function drafts(id: number) {
    selectJob(id);
    go("draft");
  }

  // ---- the full page for one match ----
  if (page && jobId != null) {
    const d = detail;
    return (
      <>
        <button className="mback" type="button" onClick={() => { setPage(false); loadJobs(); }}>← All matches</button>
        {!d ? (
          <div className="empty"><Spinner /> Loading</div>
        ) : (
          <>
            <div className="mhead">
              <div style={{ minWidth: 0 }}>
                <h2 style={{ marginBottom: 4 }}>{d.title}</h2>
                <div className="mrow-meta"><span className="co">{d.company}</span></div>
                <Meta j={d} />
              </div>
              {d.score != null && (
                <div className="mhead-fit">
                  <Ring score={d.score} size={84} />
                  <span className={"mono-label tonelabel " + tone(d.score)}>{TONE_LABEL[tone(d.score)]} fit</span>
                </div>
              )}
            </div>
            {d.url && <div><a className="btn dark small" href={d.url} target="_blank" rel="noreferrer">Apply ↗</a></div>}

            {d.signals && d.score != null ? (
              <>
                <div className="mcard">
                  <div className="mono-label">Why this score</div>
                  <p className="lead">{SIGNALS.map(([k]) => d.signals![k]).sort((a, b) => b.score / b.max - a.score / a.max)[0].reason}</p>
                  <StrengthsGaps signals={d.signals} />
                </div>

                <div className="mcard flush">
                  <div className="opp-head">
                    <div><b>Opportunity</b><div className="sub">How well you fit, and whether you can reach anyone about it.</div></div>
                    <div className="opp-n"><span>{d.opportunity}</span><i>Overall</i></div>
                  </div>
                  <div className="opp-grid">
                    <div>
                      <div className="opp-line"><span className="mono-label">Job fit</span><b>{d.score}</b></div>
                      <div className="bd-track"><div style={{ width: `${d.score}%` }} /></div>
                      <div className="sub">Your resume against this posting</div>
                    </div>
                    <div>
                      <div className="opp-line"><span className="mono-label">Reach</span><b>{d.has_people ? d.network : "Pending"}</b></div>
                      <div className={"bd-track" + (d.has_people ? "" : " dotted")}><div style={{ width: `${d.network}%` }} /></div>
                      <div className="sub">{d.has_people ? `${d.people_count} contact${d.people_count === 1 ? "" : "s"} found` : "Nobody has been looked for yet. Find people to score this."}</div>
                    </div>
                  </div>
                  <Breakdown signals={d.signals} total={d.score} />
                  <div className="sub" style={{ padding: "0 18px 16px" }}>Parts sum to {d.score}. Added up in code, not by the model. Opportunity = 0.65 × fit + 0.35 × reach.</div>
                </div>
              </>
            ) : d.status === "filtered" ? (
              <div className="notice">Filtered out: {d.filter_reason}</div>
            ) : (
              <div className="notice">Not scored yet. It will be scored when it reaches the top of the ranking.</div>
            )}

            <div className="row">
              {d.people_count > 0 && <button className="btn" type="button" onClick={() => contacts(d.id)}>See {d.people_count} contact{d.people_count === 1 ? "" : "s"}</button>}
              <button className={d.people_count ? "btn ghost small" : "btn"} type="button" disabled={finding === d.id || noTokens} title={noTokens ? "No contact tokens left" : undefined} onClick={() => findContacts(d)}>
                {finding === d.id ? <><Spinner /> Finding</> : <>Find contacts{costLabel}</>}
              </button>
              {d.draft && <button className="btn ghost small" type="button" onClick={() => drafts(d.id)}>Review draft</button>}
              <button className="btn ghost small" type="button" onClick={() => dismiss(d.id)}>Dismiss job</button>
            </div>
          </>
        )}
      </>
    );
  }

  const counts = state.counts;
  const tabs: [JobView, string, number][] = [
    ["scored", "Scored", counts.scored],
    ["waiting", "Waiting", counts.waiting],
    ["filtered", "Filtered out", counts.filtered],
  ];
  const scoring = state.allowances.find((a) => a.key === "scoring");
  const errs = [...(run?.detail?.board_errors ?? []), ...(run?.detail?.errors ?? [])];

  return (
    <>
      <div>
        <h2>See why each job fits.</h2>
      </div>
      <p className="lede" style={{ marginTop: -12 }}>
        Rules drop the wrong city or level first, then similarity ranks what's left. Every job is scored on five signals, with a one-line reason for each.
      </p>

      {!state.profile && <div className="notice">Upload your resume first, then come back to search.</div>}
      {state.profile && (
        <div className="mono-label" style={{ textTransform: "none", letterSpacing: 0 }}>
          {state.freshness.last_refreshed ? `Job boards last read ${ago(state.freshness.last_refreshed)}.` : "Job boards not read yet."}{" "}
          {state.freshness.auto_hours > 0
            ? `Refreshes by itself every ${state.freshness.auto_hours} h while the app is running, newest postings first.`
            : "Automatic refresh is off; press Refresh jobs."}
        </div>
      )}
      {!state.setup.aggregator && (
        <div className="notice">
          Only employers' own job boards are being read. For local Indian employers too, add a free Adzuna key: set <code>ADZUNA_APP_ID</code> and{" "}
          <code>ADZUNA_APP_KEY</code> in <code>backend/.env</code> (see <code>.env.example</code>), then restart.
        </div>
      )}

      <div className="row">
        <button className="btn" type="button" disabled={running || !state.profile} onClick={() => start(["fetch", "filter", "hydrate", "rank", "relevance", "score"])}>
          {running ? <><Spinner /> Working</> : counts.found ? "Refresh jobs" : "Search job boards"}
        </button>
        <button className="btn ghost small" type="button" disabled={running || counts.waiting === 0} onClick={() => start(["hydrate", "rank", "relevance", "score"])}>
          Score 25 more
        </button>
        {scoring && (
          <span className="mono-label" style={{ textTransform: "none", letterSpacing: 0 }}>
            {scoring.left > 0
              ? `Uses up to 25 of the ${scoring.left} ${scoring.unit} left ${scoring.period}.`
              : "The free scoring limit for today looks used up. Try again tomorrow, or add OpenRouter credit."}
          </span>
        )}
      </div>

      {running && run && (
        <div className="runsteps" role="status" aria-live="polite">
          {Object.keys(STAGE_LABEL).map((k, i, all) => {
            const at = all.indexOf(run.stage);
            const cls = i < at ? "done" : i === at ? "active" : "";
            return (
              <div key={k} className={"rs " + cls}>
                <span className="rs-dot">{i < at ? "✓" : i === at ? <Spinner /> : i + 1}</span>
                <span className="rs-label">{STAGE_LABEL[k]}</span>
              </div>
            );
          })}
        </div>
      )}
      {run && !running && run.status === "error" && <div className="notice bad" role="status">Run failed: {run.detail.error}</div>}
      {run && !running && run.status !== "error" && errs.length > 0 && (
        <div className="notice" role="status">
          {errs.every((e) => e.includes("429"))
            ? `Finished. ${errs.length} request${errs.length > 1 ? "s were" : " was"} refused for rate limits (free AI models, or a job board); they are tried again on the next search.`
            : `Finished, but ${errs.length} problem${errs.length > 1 ? "s" : ""}: ${errs.find((e) => !e.includes("429")) ?? errs[0]}`}
        </div>
      )}

      <div className="tabs" role="tablist">
        {tabs.map(([key, label, n]) => (
          <button key={key} type="button" role="tab" aria-selected={view === key} className={"tab" + (view === key ? " on" : "")} onClick={() => setView(key)}>
            {label} {n}
          </button>
        ))}
      </div>

      {jobs.length === 0 && (
        <div className="empty">
          {view === "scored" && (counts.found ? "Nothing scored yet. Press “Score 25 more”." : "No jobs yet. Press “Search job boards”.")}
          {view === "waiting" && "Nothing waiting to be scored."}
          {view === "filtered" && "Nothing filtered out yet."}
        </div>
      )}

      {view === "scored" && jobs.length > 0 && (
        <div className="mlist">
          <div className="mlist-head">
            <span className="sortbar">
              <span className="mono-label">Sort</span>
              {(["newest", "best"] as const).map((k) => (
                <button key={k} type="button" className={"sortbtn" + (sort === k ? " on" : "")} aria-pressed={sort === k} onClick={() => setSort(k)}>{k === "newest" ? "Newest" : "Best match"}</button>
              ))}
            </span>
            <span className="mono-label">{jobs.length} total</span>
          </div>
          {jobs.map((j) => {
            const t = j.score != null ? tone(j.score) : "weak";
            const expanded = open === j.id;
            return (
              <div key={j.id} className={"mrow " + t + (expanded ? " open" : "")}>
                <div className="mrow-main">
                  <button type="button" className="mrow-toggle" aria-expanded={expanded} aria-label={expanded ? "Hide the score breakdown" : "Show the score breakdown"} onClick={() => setOpen(expanded ? null : j.id)}>
                    <span className="chev">{expanded ? "⌄" : "›"}</span>
                  </button>
                  {j.score != null && <Ring score={j.score} />}
                  <div className="mrow-body">
                    <div className="mrow-title">
                      <b>{j.title}</b>
                      <span className="co">{j.company}</span>
                      <span className={"vbadge " + t}>{TONE_LABEL[t]}</span>
                      {j.has_draft && <span className="vbadge draft">Draft ready</span>}
                    </div>
                    <Meta j={j} />
                  </div>
                  <div className="mrow-actions">
                    {j.url && <a className="apply" href={j.url} target="_blank" rel="noreferrer">Apply ↗</a>}
                    {j.has_draft ? (
                      <button className="btn dark small" type="button" onClick={() => drafts(j.id)}>Review draft</button>
                    ) : (
                      j.people_count > 0 ? (
                        <button className="btn ghost small" type="button" onClick={() => contacts(j.id)}>{j.people_count} contact{j.people_count === 1 ? "" : "s"}</button>
                      ) : (
                        <button className="btn ghost small" type="button" disabled={finding === j.id || noTokens} title={noTokens ? "No contact tokens left" : undefined} onClick={() => findContacts(j)}>
                          {finding === j.id ? <><Spinner /> Finding</> : <>Find contacts{costLabel}</>}
                        </button>
                      )
                    )}
                  </div>
                </div>
                {expanded && j.signals && j.score != null && (
                  <div className="mrow-more">
                    <Breakdown signals={j.signals} total={j.score} />
                    <div className="sub">Overall opportunity <b>{j.opportunity}</b> = 0.65 × {j.score} fit + 0.35 × {j.network} reach.</div>
                    <StrengthsGaps signals={j.signals} />
                    <div className="row">
                      <button className="btn dark small" type="button" onClick={() => openPage(j.id)}>Open match</button>
                      {j.url && <a className="btn ghost small" href={j.url} target="_blank" rel="noreferrer">View posting ↗</a>}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {view !== "scored" && jobs.length > 0 && (
        <div className="list jobs">
          {jobs.map((j) => (
            <button key={j.id} type="button" className="job" onClick={() => openPage(j.id)}>
              <span className={"score" + (j.score == null ? " none" : j.score >= 80 ? " hi" : "")}>{j.score ?? "–"}</span>
              <span className="meta">
                <div className="t">{j.title}</div>
                <div className="s">{j.company} · {j.location || "Location not listed"}</div>
                {view === "filtered" && <div className="s" style={{ color: "var(--warn-fg)" }}>{j.filter_reason}</div>}
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
