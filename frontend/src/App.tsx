import { Allowances } from "./components/Allowances";
import { GithubButton } from "./components/GithubButton";
import { PublicBar } from "./components/PublicBar";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { AppState } from "./types";
import { BriefStep } from "./components/BriefStep";
import { DraftStep } from "./components/DraftStep";
import { STEPS, type StepKey } from "./components/FlowDiagram";
import { Logo } from "./components/Logo";
import { MatchesStep } from "./components/MatchesStep";
import { PeopleStep } from "./components/PeopleStep";
import { ResumeStep } from "./components/ResumeStep";
import { message, type Ctx } from "./components/ctx";
import { Link } from "./router";

export default function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [step, setStep] = useState<StepKey>("resume");
  const [jobId, setJobId] = useState<number | null>(null);
  const [personId, setPersonId] = useState<number | null>(null);
  const [toast, setToast] = useState("");
  const [fatal, setFatal] = useState("");
  const first = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const s = await api.state();
      setState(s);
      setFatal("");
      if (first.current) {
        first.current = false;
        setStep(s.profile ? (s.counts.scored ? "matches" : "brief") : "resume");
      }
    } catch (e) {
      setFatal(message(e));
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // poll while a search is running
  const running = state?.run?.status === "running";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(refresh, 1500);
    return () => clearInterval(t);
  }, [running, refresh]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 7000);
    return () => clearTimeout(t);
  }, [toast]);

  const go = useCallback((s: StepKey) => {
    setStep(s);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  if (!state) {
    return (
      <div className="app">
        <div className="main">
          <div className="hero"><h1>Doorknock</h1></div>
          {fatal ? <div className="notice bad">{fatal}</div> : <p className="lede">Loading…</p>}
        </div>
      </div>
    );
  }

  const ctx: Ctx = {
    state, refresh, notify: setToast, go, jobId,
    selectJob: (id) => { setJobId(id); setPersonId(null); },
    personId, selectPerson: setPersonId,
  };
  const idx = STEPS.findIndex((s) => s.key === step);

  return (
    <div className="app">
      <header className="header">
        <Link to="/" className="brand" style={{ textDecoration: "none" }} aria-label="Doorknock overview">
          <span className="logo"><Logo /></span>Doorknock
        </Link>
        <span className="spacer" />
        <GithubButton />
        <Link to="/" className="btn ghost small">How it works</Link>
      </header>

      <main className="main">
        {fatal && <div className="notice bad">{fatal}</div>}
        {state.setup.public && <PublicBar ctx={ctx} />}

        <section className="workspace" aria-label="Workspace">
          <div className="ws-bar">
            <span className="traffic" aria-hidden="true"><span /><span /><span /></span>
            <span className="t">Doorknock / Workspace</span>
            <span className="mono-label">0{idx + 1} / 05</span>
          </div>
          <div className="ws-body">
            <nav className="stepper" aria-label="Steps">
              {STEPS.map((s, i) => (
                <button key={s.key} type="button" className={"step" + (s.key === step ? " on" : "") + (i < idx ? " done" : "")} aria-current={s.key === step ? "step" : undefined} onClick={() => go(s.key)}>
                  <span className="n">0{i + 1}</span>
                  <span className="label">{s.label}</span>
                  <span className="tick" />
                </button>
              ))}
              <Allowances items={state.allowances} variant="rail" />
            </nav>
            <div className="stage">
              <Allowances items={state.allowances} variant="strip" />
              {step === "resume" && <ResumeStep ctx={ctx} />}
              {step === "brief" && <BriefStep ctx={ctx} />}
              {step === "matches" && <MatchesStep ctx={ctx} />}
              {step === "people" && <PeopleStep ctx={ctx} />}
              {step === "draft" && <DraftStep ctx={ctx} />}
            </div>
          </div>
        </section>
      </main>

      {toast && (
        <div className="toast" role="status">
          <span>{toast}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setToast("")}>×</button>
        </div>
      )}
    </div>
  );
}
