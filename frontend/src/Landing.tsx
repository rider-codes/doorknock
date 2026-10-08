import { GithubButton } from "./components/GithubButton";
import { useState } from "react";
import { Demo } from "./components/Demo";
import { FlowDiagram, type StepKey } from "./components/FlowDiagram";
import { Logo } from "./components/Logo";
import { Link } from "./router";

const PROMISES = [
  { title: "Drafts only", body: "Doorknock can create a draft in your Gmail. It cannot send. You press send, or you don't." },
  { title: "Facts you can check", body: "Every line comes from a quote in your resume or the job posting, and you can see which one." },
  { title: "Scores that explain themselves", body: "Five signals, each with a one-line reason. The total always matches the parts." },
];

export default function Landing() {
  const [step, setStep] = useState<StepKey>("resume");
  const [playing, setPlaying] = useState(false);

  return (
    <div className="app land">
      <header className="header">
        <Link to="/" className="brand" style={{ textDecoration: "none" }}>
          <span className="logo"><Logo /></span>Doorknock
        </Link>
        <span className="spacer" />
        <GithubButton />
        <Link to="/app" className="btn small">Try it yourself</Link>
      </header>

      <main className="main">
        <section className="hero hero-grid">
          <div className="hero-copy">
            <h1>Find the right person. Knock with a real reason.</h1>
            <p className="lede" style={{ maxWidth: 560, fontSize: 18 }}>
              Upload your resume and describe the job you want. Doorknock finds matching jobs, scores your fit, finds who to write to, and saves a draft email
              in your Gmail. Nothing sends without you.
            </p>
            <div className="row" style={{ marginTop: 16 }}>
              <Link to="/app" className="btn">Try it yourself</Link>
              <a href="#example" className="btn ghost">See how it works</a>
            </div>
          </div>

          <div className="hero-art">
            <FlowDiagram />
            <div className="hero-promises">
              <div className="mono-label">Built to be trusted</div>
              {PROMISES.map((p) => (
                <article className="promise" key={p.title}>
                  <span className="promise-mark" aria-hidden="true">✓</span>
                  <div>
                    <h3>{p.title}</h3>
                    <p>{p.body}</p>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="example" className="section" aria-labelledby="example-h" style={{ scrollMarginTop: 80 }}>
          <div className="section-head">
            <div>
              <h2 id="example-h" className="section-h">See how it works</h2>
              <p className="lede" style={{ marginTop: 6 }}>Press play to watch a full run, or click anything yourself. It uses sample data and sends nothing.</p>
            </div>
            <button type="button" className="btn play-btn" aria-pressed={playing} onClick={() => setPlaying((p) => !p)}>
              <span aria-hidden="true">{playing ? "❚❚" : "▶"}</span>
              {playing ? "Pause" : "Play"}
            </button>
          </div>
          <Demo step={step} onStep={setStep} playing={playing} onPlayingChange={setPlaying} />
        </section>
      </main>

      <footer className="foot-land">
        <span className="mono-label">Doorknock</span>
        <span className="mono-label">Nothing sends without you</span>
      </footer>
    </div>
  );
}
