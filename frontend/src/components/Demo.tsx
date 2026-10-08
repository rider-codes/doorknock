import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { FlowCaption, type StepKey } from "./FlowDiagram";

/** Fixed sample data. The overview never calls the API, so anyone can click through it. */
type Band = "All" | "Strong fit" | "Good fit" | "Stretch";
type Level = "entry" | "mid" | "senior";
type Place = "Bengaluru" | "Remote" | "Hyderabad";
const BANDS: Band[] = ["All", "Strong fit", "Good fit", "Stretch"];
const LEVELS: [Level, string, number][] = [["entry", "Early career", 2], ["mid", "Mid-level", 5], ["senior", "Senior", 99]];
const PLACES: Place[] = ["Bengaluru", "Remote", "Hyderabad"];
const SIGNAL_LABELS = ["Role", "Profile", "Skills", "Location", "Seniority"] as const;
const MAX = [25, 30, 20, 15, 10];

interface Contact { name: string; title: string; why: string; role: string; verified: boolean; score: number }
interface DemoJob {
  id: number;
  title: string;
  company: string;
  where: string;
  place: Place;
  years: number; // years of experience the posting asks for
  pay: string;
  posted: string;
  score: number[]; // role, profile, skills, location, seniority
  why: string[];
  person: Contact;
  alt: Contact;
  claim: string; // the sentence in the email that comes from the resume
  resumeQuote: string;
  postingQuote: string;
}

const JOBS: DemoJob[] = [
  {
    id: 1, title: "Backend Engineer, Payments", company: "Fenwick Pay", where: "Bengaluru (Hybrid)", place: "Bengaluru", years: 2, pay: "₹18–26L", posted: "3 days ago",
    score: [23, 27, 18, 15, 9],
    why: ["Backend-only posting", "Payments ledger at scale", "Go · Postgres · Kafka", "A city you named", "Asks 2–4 yrs"],
    person: { name: "Jane Doe", title: "Technical Recruiter, Engineering", why: "Owns this requisition", role: "Recruiting", verified: true, score: 88 },
    alt: { name: "Arjun Mehta", title: "Engineering Manager, Payments", why: "Manages the hiring team", role: "Hiring manager", verified: true, score: 79 },
    claim: "I spent three years on a double-entry ledger reconciling ~40k txn/day",
    resumeQuote: "Built a double-entry ledger reconciling ~40k txn/day for three years",
    postingQuote: "You will build ledger services in Go and Postgres",
  },
  {
    id: 2, title: "Backend Developer", company: "Northwind Labs", where: "Bengaluru", place: "Bengaluru", years: 1, pay: "₹16–24L", posted: "2 days ago",
    score: [21, 24, 16, 15, 8],
    why: ["Backend APIs, your target role", "Two API projects match", "Python and PostgreSQL listed", "A city you named", "Asks 1–3 yrs"],
    person: { name: "Priya Nair", title: "Talent Partner", why: "Recruits for engineering", role: "Recruiting", verified: true, score: 83 },
    alt: { name: "Dev Malhotra", title: "Engineering Lead", why: "Leads the team hiring", role: "Hiring manager", verified: true, score: 74 },
    claim: "I built REST APIs in Python backed by PostgreSQL",
    resumeQuote: "Built REST APIs in Python backed by PostgreSQL for an internal tools team",
    postingQuote: "You will design and ship REST APIs in Python",
  },
  {
    id: 3, title: "Software Engineer I", company: "Harbor Systems", where: "Remote (India)", place: "Remote", years: 1, pay: "₹14–20L", posted: "5 days ago",
    score: [19, 21, 15, 15, 7],
    why: ["Backend, leans toward tooling", "Relevant projects, no payments work", "Go preferred, not on your resume", "Remote in India", "Entry level, 3+ yrs nice to have"],
    person: { name: "Arjun Rao", title: "Engineering Manager, Platform", why: "Manages the hiring team", role: "Hiring manager", verified: true, score: 81 },
    alt: { name: "Sam Rao", title: "Staff Engineer", why: "Works on the same service", role: "Teammate", verified: false, score: 58 },
    claim: "I built a Go service on Postgres that handles ~2k requests a minute",
    resumeQuote: "Built a Go service on Postgres handling ~2k requests a minute",
    postingQuote: "Our stack is Go and Postgres",
  },
  {
    id: 4, title: "API Engineer", company: "Fieldnote", where: "Remote (Worldwide)", place: "Remote", years: 2, pay: "₹15–22L", posted: "1 week ago",
    score: [18, 20, 14, 15, 7],
    why: ["API work, a little product-side", "Projects show API design", "Node is core, you list it once", "Remote, no restrictions", "Asks 2+ yrs"],
    person: { name: "Sam Whitlock", title: "Founder", why: "Makes the hiring call", role: "Hiring manager", verified: true, score: 70 },
    alt: { name: "Maya Chen", title: "Head of Product", why: "Shapes the role", role: "Hiring manager", verified: false, score: 52 },
    claim: "I designed the REST API for a project with 200 weekly users",
    resumeQuote: "Designed the REST API for a side project with 200 weekly users",
    postingQuote: "You will own our public API",
  },
  {
    id: 5, title: "Software Engineer, Integrations", company: "Quartz Mobility", where: "Remote (India)", place: "Remote", years: 3, pay: "₹14–19L", posted: "1 week ago",
    score: [17, 18, 12, 15, 6],
    why: ["Integration work, less core backend", "Little automotive overlap", "Java required, not on your resume", "Remote in India", "Asks 3+ yrs"],
    person: { name: "Tomas Berg", title: "Talent Partner", why: "Recruits for engineering", role: "Recruiting", verified: false, score: 61 },
    alt: { name: "Leo Fischer", title: "Engineering Manager", why: "Runs the team", role: "Hiring manager", verified: true, score: 60 },
    claim: "I connected three third-party APIs into one internal service",
    resumeQuote: "Integrated three third-party APIs into a single internal service",
    postingQuote: "You will build integrations with partner APIs",
  },
  {
    id: 6, title: "Platform Engineer", company: "Lumen Data", where: "Bengaluru (Onsite)", place: "Bengaluru", years: 3, pay: "₹20–30L", posted: "1 week ago",
    score: [15, 16, 11, 15, 4],
    why: ["Infrastructure, adjacent to your roles", "One data pipeline project", "Spark and Airflow missing", "A city you named", "Mid-level scope"],
    person: { name: "Ines Duarte", title: "Recruiter, Data", why: "Recruits for the data team", role: "Recruiting", verified: false, score: 64 },
    alt: { name: "Sara Iyer", title: "Data Engineer", why: "Works on the same team", role: "Teammate", verified: false, score: 49 },
    claim: "I built a batch pipeline that loads ~50k rows a night into Postgres",
    resumeQuote: "Built a batch pipeline loading ~50k rows a night into Postgres",
    postingQuote: "You will own our data platform pipelines",
  },
  {
    id: 7, title: "Junior Full-stack Developer", company: "Brightloop", where: "Hyderabad", place: "Hyderabad", years: 2, pay: "₹9–14L", posted: "2 weeks ago",
    score: [14, 17, 12, 8, 6],
    why: ["Full-stack is broader than your target", "Portfolio shows front-end work", "React listed once, in a project", "Not a city you named", "Junior title, wants 2+ yrs"],
    person: { name: "Kavya Rao", title: "HR Generalist", why: "Handles hiring", role: "Recruiting", verified: false, score: 55 },
    alt: { name: "Rohan Das", title: "CTO", why: "Makes the hiring call", role: "Hiring manager", verified: true, score: 66 },
    claim: "I built and deployed a React front end for my portfolio",
    resumeQuote: "Built and deployed a React front end for my portfolio site",
    postingQuote: "You will build features across React and Node",
  },
];

const total = (j: DemoJob) => j.score.reduce((a, b) => a + b, 0);
const bandOf = (n: number): Exclude<Band, "All"> => (n >= 80 ? "Strong fit" : n >= 65 ? "Good fit" : "Stretch");
const SORTED = [...JOBS].sort((a, b) => total(b) - total(a));
const PROFILE_SKILLS = ["Python", "Go", "PostgreSQL", "Kafka", "Docker", "REST APIs", "Git"];
const DEFAULT_PLACES: Place[] = ["Bengaluru", "Remote"];

/** The same kind of hard rules the real app applies before any scoring. */
function ruleFor(j: DemoJob, level: Level, places: Place[]): string | null {
  const cap = LEVELS.find((l) => l[0] === level)![2];
  if (j.years > cap) return `Asks for ${j.years}+ years of experience (your level allows up to ${cap})`;
  if (!places.includes(j.place)) return `${j.place === "Remote" ? "Remote roles" : j.place} isn't one of your places`;
  return null;
}

const ORDER: StepKey[] = ["resume", "matches", "people", "draft"];
const STEP_NAMES: Record<string, string> = { resume: "Resume & brief", matches: "Matches", people: "Person", draft: "Draft" };
const TRY: Record<string, string> = {
  resume: "Try it: change your level or where you'd work. The next step only keeps jobs that pass.",
  matches: "Try it: pick a job to see why it scored that way, or filter by fit.",
  people: "Try it: choose who to write to. The draft will be addressed to them.",
  draft: "Try it: click an evidence line to see its quote, then save the draft.",
};

/** What the Play button runs through. Each frame is a state the viewer could have clicked into. */
const TOUR_MS = 3600;
const FRAMES: { step: StepKey; job?: number; ev?: number; person?: 0 | 1 }[] = [
  { step: "resume" },
  { step: "matches", job: SORTED[0].id },
  { step: "matches", job: SORTED[1].id },
  { step: "matches", job: SORTED[2].id },
  { step: "people", job: SORTED[0].id, person: 0 },
  { step: "people", job: SORTED[0].id, person: 1 },
  { step: "draft", job: SORTED[0].id, person: 0, ev: 0 },
  { step: "draft", job: SORTED[0].id, person: 0, ev: 1 },
];

export function Demo({
  step,
  onStep,
  playing,
  onPlayingChange,
}: {
  step: StepKey;
  onStep: (s: StepKey) => void;
  playing: boolean;
  onPlayingChange: (p: boolean) => void;
}) {
  const [level, setLevel] = useState<Level>("entry");
  const [places, setPlaces] = useState<Place[]>(DEFAULT_PLACES);
  const [band, setBand] = useState<Band>("All");
  const [jobId, setJobId] = useState(SORTED[0].id);
  const [personIx, setPersonIx] = useState<0 | 1>(0);
  const [ev, setEv] = useState(0);
  const [saved, setSaved] = useState(false);
  const [picking, setPicking] = useState(false);
  const [frame, setFrame] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const stepRef = useRef(onStep);
  stepRef.current = onStep;

  // Play: apply a frame, then the next one every few seconds. Any click by the viewer pauses it.
  useEffect(() => {
    if (!playing) return;
    const apply = (i: number) => {
      const f = FRAMES[i];
      stepRef.current(f.step);
      if (i === 0) { setLevel("entry"); setPlaces(DEFAULT_PLACES); }
      if (f.job) setJobId(f.job);
      setPersonIx(f.person ?? 0);
      setEv(f.ev ?? 0);
      setBand("All");
      setSaved(false);
      setPicking(false);
      setFrame(i);
    };
    let i = 0;
    apply(0);
    const id = setInterval(() => {
      i = (i + 1) % FRAMES.length;
      apply(i);
    }, TOUR_MS);
    return () => clearInterval(id);
  }, [playing]);

  const kept = useMemo(() => SORTED.filter((j) => !ruleFor(j, level, places)), [level, places]);
  const visible = useMemo(() => kept.filter((j) => band === "All" || bandOf(total(j)) === band), [kept, band]);
  const job = visible.find((j) => j.id === jobId) ?? visible[0] ?? kept[0] ?? null;

  // keep the selected row in view inside the scrolling list (without moving the page)
  useEffect(() => {
    const list = listRef.current;
    const row = list?.querySelector<HTMLElement>(".job.on");
    if (list && row) list.scrollTop += row.getBoundingClientRect().top - list.getBoundingClientRect().top - 8;
  }, [job?.id, step, band]);

  const stop = () => onPlayingChange(false);
  const go = (s: StepKey) => { stop(); onStep(s); };
  const cur = step === "brief" ? "resume" : step;
  const idx = Math.max(0, ORDER.indexOf(cur));
  const prev = ORDER[idx - 1];
  const next = ORDER[idx + 1];
  const needsJob = cur !== "resume";

  const onStepKeys = (e: KeyboardEvent) => {
    if (e.key === "ArrowRight" && next) { e.preventDefault(); go(next); }
    if (e.key === "ArrowLeft" && prev) { e.preventDefault(); go(prev); }
  };
  const toggleLevel = (l: Level) => { stop(); setLevel(l); setSaved(false); };
  const togglePlace = (p: Place) => {
    stop();
    setSaved(false);
    setPlaces((cur2) => (cur2.includes(p) ? cur2.filter((x) => x !== p) : [...cur2, p]));
  };

  const person = job ? (personIx === 0 ? job.person : job.alt) : null;
  const score = job ? total(job) : 0;
  const count = (b: Band) => (b === "All" ? kept.length : kept.filter((j) => bandOf(total(j)) === b).length);
  const showJobs = cur === "matches" || ((cur === "people" || cur === "draft") && picking);
  const showSelected = job && (cur === "people" || cur === "draft") && !picking;

  const empty = (
    <div className="empty">
      Your brief doesn't keep any jobs right now.
      <div style={{ marginTop: 12 }}><button type="button" className="btn dark small" onClick={() => go("resume")}>Change your brief</button></div>
    </div>
  );

  const jobList = job && (
    <div className="found">
      <div className="src-row" role="group" aria-label="Filter by fit">
        {BANDS.map((b) => (
          <button key={b} type="button" className={"tab" + (band === b ? " on" : "")} aria-pressed={band === b} onClick={() => { stop(); setBand(b); }}>
            {b} <span style={{ fontFamily: "var(--mono)", opacity: 0.75 }}>{count(b)}</span>
          </button>
        ))}
      </div>
      <div className="jobs found-list" ref={listRef}>
        {visible.map((j) => (
          <button key={j.id} type="button" className={"job" + (j.id === job.id ? " on" : "")} aria-pressed={j.id === job.id} onClick={() => { stop(); setJobId(j.id); setPersonIx(0); setEv(0); setSaved(false); setPicking(false); }}>
            <span className={"score" + (total(j) >= 80 ? " hi" : "")}>{total(j)}</span>
            <span className="meta">
              <div className="t">{j.title}</div>
              <div className="s">{j.company} · {j.where}</div>
            </span>
            <span className="badge mute src-badge">{bandOf(total(j))}</span>
          </button>
        ))}
      </div>
    </div>
  );

  const scorePane = job && (
    <div className="demo-pane">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "nowrap" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: "var(--muted)", fontSize: 14 }}>{job.company} · {job.where} · {job.pay} · {job.posted}</div>
          <h3 style={{ marginTop: 4 }}>{job.title}</h3>
        </div>
        <div className="ring" style={{ background: `conic-gradient(var(--acc) ${score}%, var(--line) 0)` }} role="img" aria-label={`Fit score ${score} out of 100, ${bandOf(score)}`}>
          <div><div className="mono-label" style={{ fontSize: 10 }}>FIT</div><div className="num">{score}</div></div>
        </div>
      </div>
      <div className="sig-grid">
        {SIGNAL_LABELS.map((label, i) => (
          <div className="sig" key={label}>
            <div className="name">{label}</div>
            <div className="track"><div className="fill" style={{ width: `${(job.score[i] / MAX[i]) * 100}%` }} /></div>
            <div className="val">{job.score[i]}/{MAX[i]}</div>
            <div className="why">{job.why[i]}</div>
          </div>
        ))}
      </div>
      <div className="mono-label" style={{ textTransform: "none", letterSpacing: 0 }}>Parts sum to {score}. Added up in code, not by the model.</div>
    </div>
  );

  return (
    <div className="demo">
      <section className="workspace" aria-label="Interactive example">
        <div className="ws-bar">
          <span className="traffic" aria-hidden="true"><span /><span /><span /></span>
          <span className="t">Example · not a live result</span>
          {playing && <span className="mono-label" aria-live="polite">Playing {frame + 1} / {FRAMES.length}</span>}
        </div>

        <div className="demo-steps" role="tablist" aria-label="Example steps" onKeyDown={onStepKeys}>
          {ORDER.map((k, i) => (
            <button key={k} type="button" role="tab" aria-selected={k === cur} tabIndex={k === cur ? 0 : -1} className={"dstep" + (k === cur ? " on" : "") + (i < idx ? " done" : "")} onClick={() => go(k)}>
              <span className="n">{i < idx ? "✓" : i + 1}</span>
              <span className="l">{STEP_NAMES[k]}</span>
            </button>
          ))}
        </div>

        <div className="demo-body">
          <FlowCaption step={cur} />
          <div className="try-tip">{TRY[cur]}</div>

          {cur === "resume" && (
            <div className="demo-pane">
              <div>
                <div className="mono-label" style={{ marginBottom: 8 }}>Your profile, read from your resume</div>
                <div className="chips">{PROFILE_SKILLS.map((s) => <span className="chip" key={s}>{s}</span>)}</div>
              </div>
              <div className="brief-box">
                <div className="mono-label">Your brief</div>
                <fieldset>
                  <legend>Your level</legend>
                  <div className="seg">
                    {LEVELS.map(([k, label]) => (
                      <button key={k} type="button" className={"tab" + (level === k ? " on" : "")} aria-pressed={level === k} onClick={() => toggleLevel(k)}>{label}</button>
                    ))}
                  </div>
                </fieldset>
                <fieldset>
                  <legend>Where you'd work</legend>
                  <div className="seg">
                    {PLACES.map((p) => (
                      <button key={p} type="button" className={"tab" + (places.includes(p) ? " on" : "")} aria-pressed={places.includes(p)} onClick={() => togglePlace(p)}>{p === "Remote" ? "Remote (India)" : p}</button>
                    ))}
                  </div>
                </fieldset>
                <div className={"live-count" + (kept.length === 0 ? " none" : "")} role="status" aria-live="polite">
                  <span className="num">{kept.length}</span> of {JOBS.length} jobs pass your brief
                </div>
              </div>
            </div>
          )}

          {cur === "matches" && (kept.length === 0 || !job ? empty : (
            <div className="matches-split">
              {jobList}
              {scorePane}
            </div>
          ))}

          {cur === "people" && (!job || !person ? empty : (
            <div className="demo-pane">
              {showSelected && (
                <div className="picked">
                  <span className={"score" + (score >= 80 ? " hi" : "")}>{score}</span>
                  <span className="meta">
                    <div className="t">{job.title}</div>
                    <div className="s">{job.company} · {job.where}</div>
                  </span>
                  <button type="button" className="btn ghost small" onClick={() => { stop(); setPicking(true); }}>Change job</button>
                </div>
              )}
              {showJobs && jobList}
              <h3>Who to write to at {job.company}</h3>
              <div className="people-pick" role="radiogroup" aria-label="Who to write to">
                {[job.person, job.alt].map((p, i) => (
                  <button key={p.name} type="button" role="radio" aria-checked={personIx === i} className={"person" + (personIx === i ? " on" : "")} onClick={() => { stop(); setPersonIx(i as 0 | 1); setSaved(false); }}>
                    <span className="rel">{p.score}</span>
                    <span className="info">
                      <div className="nm">{p.name}</div>
                      <div className="tt">{p.title}</div>
                      <div className="tt" style={{ color: "var(--ink)", marginTop: 4 }}>{p.why}</div>
                    </span>
                    <span style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-start" }}>
                      <span className="mono-label" style={{ textTransform: "none", letterSpacing: 0 }}>{p.role}</span>
                      <span className={"badge" + (p.verified ? "" : " warn")}>{p.verified ? "✓ verified" : "Unverified"}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}

          {cur === "draft" && (!job || !person ? empty : (
            <div className="demo-pane">
              {showSelected && (
                <div className="picked">
                  <span className={"score" + (score >= 80 ? " hi" : "")}>{score}</span>
                  <span className="meta">
                    <div className="t">{job.title}</div>
                    <div className="s">To {person.name} · {job.company}</div>
                  </span>
                  <button type="button" className="btn ghost small" onClick={() => { stop(); setPicking(true); }}>Change job</button>
                </div>
              )}
              {showJobs && jobList}
              <div className="mail">
                <div className="head">
                  <div><span style={{ color: "var(--muted)" }}>To </span><span style={{ fontFamily: "var(--mono)", fontSize: 13 }}>{person.name}</span></div>
                  <div style={{ fontWeight: 700, fontSize: 15 }}>{job.title} at {job.company}</div>
                </div>
                <div className="body">
                  Hi {person.name.split(" ")[0]} — <span className="hl on">{job.claim}</span>, which is close to what this posting describes. Worth a look?
                </div>
                <div className="foot row" style={{ justifyContent: "space-between" }}>
                  {saved ? (
                    <span className="saved-note" role="status">✓ Saved to your Gmail drafts. Nothing was sent.</span>
                  ) : (
                    <span className="mono-label" style={{ letterSpacing: "0.08em" }}>Not saved yet</span>
                  )}
                  <button type="button" className="btn small" disabled={saved} onClick={() => { stop(); setSaved(true); }}>{saved ? "Saved" : "Save to Gmail drafts"}</button>
                </div>
              </div>
              <div className="mono-label">Evidence checked</div>
              <div className="ev-grid">
                {[
                  { claim: "From your resume", from: "your resume", quote: job.resumeQuote },
                  { claim: "From the job posting", from: "the posting", quote: job.postingQuote },
                ].map((e, i) => (
                  <button key={e.claim} type="button" className={"person" + (ev === i ? " on" : "")} aria-pressed={ev === i} onClick={() => { stop(); setEv(i); }} style={{ padding: 12 }}>
                    <span style={{ color: "var(--acc-txt)", fontWeight: 700 }}>✓</span>
                    <span className="info"><div className="nm" style={{ fontSize: 15 }}>{e.claim}</div><div className="tt">{e.from}</div></span>
                  </button>
                ))}
              </div>
              <div className="quote">“{ev === 0 ? job.resumeQuote : job.postingQuote}”</div>
            </div>
          ))}
        </div>

        <div className="demo-nav">
          <button type="button" className="btn ghost small" disabled={!prev} onClick={() => prev && go(prev)}>← Back</button>
          <span className="mono-label demo-nav-count">Step {idx + 1} of {ORDER.length}</span>
          {next ? (
            <button type="button" className="btn small" disabled={needsJob === false ? false : !job} onClick={() => go(next)}>Next: {STEP_NAMES[next]} →</button>
          ) : (
            <button type="button" className="btn ghost small" onClick={() => go("resume")}>Start over</button>
          )}
        </div>
      </section>
    </div>
  );
}
