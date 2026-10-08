import type { ReactNode } from "react";

export const STEPS = [
  { key: "resume", label: "Resume", long: "Reads your resume" },
  { key: "brief", label: "Brief", long: "Takes your brief" },
  { key: "matches", label: "Matches", long: "Scores what it finds" },
  { key: "people", label: "People", long: "Finds the person" },
  { key: "draft", label: "Draft", long: "Writes the draft" },
] as const;

export type StepKey = (typeof STEPS)[number]["key"];

// The diagram has four cards; the brief shares the resume card.
type Card = "r" | "s" | "p" | "d";
const CARD_FOR: Record<StepKey, Card> = { resume: "r", brief: "r", matches: "s", people: "p", draft: "d" };
const STEP_FOR: Record<Card, StepKey> = { r: "resume", s: "matches", p: "people", d: "draft" };
const CAPTIONS: Record<StepKey, string> = {
  resume: "Your PDF or Word file is read into a profile of skills, experience and seniority. Everything else builds on it.",
  brief: "Say the job you want in plain English. It becomes roles, cities, level and keywords.",
  matches: "Rules drop the wrong city or level. Then every job is scored on five signals, each with a reason.",
  people: "Recruiters, hiring managers and teammates, ranked by relevance and by whether the email is verified.",
  draft: "Written only from quotes in your resume and the posting, then saved to Gmail. You decide whether it sends.",
};
const BARS = [20, 34, 18, 40, 14, 29, 11];

function DgCard({ on, onClick, label, tag, children }: { on: boolean; onClick?: () => void; label: string; tag: string; children: ReactNode }) {
  const inner = (
    <>
      <span className="dg-tag">{tag}</span>
      {children}
    </>
  );
  const cls = "dg-card" + (on ? " on" : "");
  if (!onClick) return <div className={cls}>{inner}</div>;
  return (
    <button type="button" className={cls} onClick={onClick} aria-pressed={on} aria-label={label}>
      {inner}
    </button>
  );
}

/** The pipeline picture, left to right: resume, scored, person, Gmail draft. Cards are clickable when `onStep` is given. */
export function FlowDiagram({ step, onStep }: { step?: StepKey; onStep?: (s: StepKey) => void }) {
  const active = step ? CARD_FOR[step] : null;
  const go = (c: Card) => (onStep ? () => onStep(STEP_FOR[c]) : undefined);
  return (
    <section className="dg" aria-label="How it works">
      <div className="dg-row">
        <DgCard on={active === "r"} onClick={go("r")} label="Reads your resume" tag="RESUME">
          {[100, 78, 90, 48].map((w, i) => (
            <span key={i} className="dg-line dg-parse" style={{ width: `${w}%`, animationDelay: `${0.15 + i * 0.22}s` }} />
          ))}
          <span className="dg-scan" aria-hidden="true" />
        </DgCard>
        <span className="dg-link" aria-hidden="true" />
        <DgCard on={active === "s"} onClick={go("s")} label="Scores what it finds" tag="SCORED">
          <span className="dg-bars" aria-hidden="true">
            {BARS.map((h, i) => (
              <span key={i} className="dg-bar" style={{ height: h }} />
            ))}
          </span>
        </DgCard>
        <span className="dg-link" aria-hidden="true" />
        <DgCard on={active === "p"} onClick={go("p")} label="Finds the person" tag="PERSON">
          <span className="dg-person">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--sage)" strokeWidth="1.8" aria-hidden="true">
              <circle cx="12" cy="12" r="10" />
              <circle cx="12" cy="10" r="3" />
              <path d="M6 19c1.5-3 4-4 6-4s4.5 1 6 4" />
            </svg>
            <span className="dg-name">First Last</span>
            <span className="dg-role">Recruiter</span>
            <span className="dg-verified" aria-hidden="true">✓ verified</span>
          </span>
        </DgCard>
        <span className="dg-link end" aria-hidden="true"><span className="dg-dot" /></span>
        <DgCard on={active === "d"} onClick={go("d")} label="Writes the draft" tag="DRAFT">
          {[84, 66, 40].map((w, i) => (
            <span key={i} className={"dg-line dg-write" + (i === 0 ? " accent" : "")} style={{ width: `${w}%`, animationDelay: `${4.8 + i * 0.35}s` }} />
          ))}
        </DgCard>
      </div>
    </section>
  );
}

/** One line saying what the selected step does. */
export function FlowCaption({ step }: { step: StepKey }) {
  return <p className="flow-caption" style={{ textAlign: "left" }}>{CAPTIONS[step]}</p>;
}
