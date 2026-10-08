import { useRef, useState } from "react";
import { api } from "../api";
import { Spinner } from "./Logo";
import { message, type Ctx } from "./ctx";

const LEVELS: Record<string, string> = { intern: "Intern", entry: "Early career", mid: "Mid-level", senior: "Senior", staff: "Staff" };

export function ResumeStep({ ctx }: { ctx: Ctx }) {
  const { state, refresh, notify, go } = ctx;
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const profile = state.profile?.data;

  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    try {
      await api.uploadResume(file);
      await refresh();
    } catch (e) {
      notify(message(e));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function removeSkill(skill: string) {
    if (!profile) return;
    try {
      await api.saveProfile({ ...profile, skills: profile.skills.filter((s) => s !== skill) });
      await refresh();
    } catch (e) {
      notify(message(e));
    }
  }

  return (
    <>
      <div>
        <h2>Start with your resume.</h2>
        <p className="lede">
          Upload a PDF or Word file. Doorknock reads it into a profile of your skills, experience, projects and seniority, and everything
          else builds on that.
        </p>
      </div>

      {!state.setup.llm && (
        <div className="notice bad">
          No AI key found. Add <code>OPENROUTER_API_KEY</code> (one key, many models) or <code>ANTHROPIC_API_KEY</code> to{" "}
          <code>backend/.env</code> and restart the backend, or reading your resume will fail.
        </div>
      )}

      <div
        className={"drop" + (over ? " over" : "")}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files[0]); }}
      >
        <input ref={input} type="file" hidden accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(e) => upload(e.target.files?.[0])} />
        {busy ? (
          <div className="row"><Spinner /> Reading your resume…</div>
        ) : (
          <>
            <div style={{ fontWeight: 600 }}>{state.profile ? state.profile.filename : "Drop your resume here"}</div>
            <div className="mono-label">PDF or DOCX · up to 8 MB</div>
            <button className="btn dark" type="button" onClick={() => input.current?.click()}>
              {state.profile ? "Replace file" : "Choose file"}
            </button>
          </>
        )}
      </div>

      {profile && (
        <>
          <div className="stats">
            <div className="stat"><div className="mono-label">Seniority</div><div className="v">{LEVELS[profile.seniority] ?? profile.seniority}</div></div>
            <div className="stat"><div className="mono-label">Experience</div><div className="v">{profile.years_experience} yr</div></div>
            <div className="stat"><div className="mono-label">Projects</div><div className="v">{profile.projects.length}</div></div>
          </div>
          <div>
            <div className="mono-label" style={{ marginBottom: 10 }}>Skills found</div>
            <div className="chips">
              {profile.skills.map((s) => (
                <span className="chip" key={s}>
                  {s}
                  <button type="button" aria-label={`Remove ${s}`} onClick={() => removeSkill(s)}>×</button>
                </span>
              ))}
            </div>
          </div>
          {profile.experience.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <div className="mono-label">Experience</div>
              {profile.experience.slice(0, 4).map((x, i) => (
                <div className="xp" key={i}>
                  <div style={{ fontWeight: 600 }}>{x.title}{x.company && ` · ${x.company}`}</div>
                  {x.bullets.length > 0 && <ul>{x.bullets.slice(0, 3).map((b, j) => <li key={j}>{b}</li>)}</ul>}
                </div>
              ))}
            </div>
          )}
          <div className="notice">Check this over. Anything the parser missed cannot be used when scoring jobs or writing emails.</div>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn" type="button" onClick={() => go("brief")}>Next: Takes your brief</button>
          </div>
        </>
      )}
    </>
  );
}

