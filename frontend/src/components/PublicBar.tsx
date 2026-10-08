import { useState } from "react";
import { api, clearKeyFor, getKeyFor, setKeyFor, type KeyService } from "../api";
import type { Ctx } from "./ctx";
import { message } from "./ctx";
import { Spinner } from "./Logo";

interface KeyInfo {
  service: KeyService;
  name: string;
  need: string;
  does: string;
  without: string;
  link: string;
  linkText: string;
  placeholder: string;
}

/** Every key Doorknock can use, what it unlocks, and what happens without it. */
const KEYS: KeyInfo[] = [
  {
    service: "openrouter", name: "OpenRouter", need: "For the AI steps",
    does: "Reads your resume, runs the brief chat, scores every job with a reason, and writes the email drafts. A free key works; free models have a daily limit.",
    without: "You can still click through the sample data, but nothing runs on your own resume.",
    link: "https://openrouter.ai/keys", linkText: "Get a free key", placeholder: "sk-or-v1-…",
  },
  {
    service: "hunter", name: "Hunter", need: "Optional · find contacts",
    does: "Finds the recruiter, hiring manager or teammate and their email when you press Find contacts. Each search costs one token (the free plan has 50 a month).",
    without: "You get only contacts printed in the posting, and you can add people by hand.",
    link: "https://hunter.io/api-keys", linkText: "Get a free key", placeholder: "40-character Hunter key",
  },
  {
    service: "jooble", name: "Jooble", need: "Optional · more jobs",
    does: "Adds a job feed with many Indian employers that have no public job board. The free key allows 500 requests in total; Doorknock spends only a few per search.",
    without: "Searches read employers' own job boards only.",
    link: "https://jooble.org/api/about", linkText: "Get a free key", placeholder: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  },
  {
    service: "adzuna", name: "Adzuna", need: "Optional · more jobs",
    does: "Adds a second job feed across many employers. Paste your app id and key together as id:key.",
    without: "Searches read employers' own job boards, plus Jooble if you added it.",
    link: "https://developer.adzuna.com", linkText: "Get a free key", placeholder: "app_id:app_key",
  },
];

/** The public site's top strip: a simple first choice, then the visitor's own keys, then what is stored about them. */
export function PublicBar({ ctx }: { ctx: Ctx }) {
  const { state, refresh, notify, go } = ctx;
  const [drafts, setDrafts] = useState<Partial<Record<KeyService, string>>>({});
  const [busy, setBusy] = useState<"" | KeyService | "demo" | "clear" | "delete">("");
  const [chosen, setChosen] = useState(false); // the visitor picked "use my own resume"
  const [manage, setManage] = useState(false); // the full key panel, opened from the summary line
  const [more, setMore] = useState(false); // the optional keys inside the panel
  const saved = state.setup.keys;
  const hasAi = saved.openrouter;
  const empty = !state.profile;
  const [ai, ...optional] = KEYS;
  const optionalSaved = optional.some((k) => saved[k.service]);

  async function run(kind: typeof busy, fn: () => Promise<unknown>, done?: string) {
    setBusy(kind);
    try {
      await fn();
      await refresh();
      if (done) notify(done);
    } catch (e) {
      notify(message(e));
    } finally {
      setBusy("");
    }
  }

  async function save(info: KeyInfo) {
    const value = (drafts[info.service] ?? "").trim();
    if (!value) return;
    setKeyFor(info.service, value);
    setBusy(info.service);
    try {
      const r = (await api.checkKey(info.service)) as { ok: boolean; free_tier?: boolean; detail?: string };
      setDrafts({ ...drafts, [info.service]: "" });
      await refresh();
      notify(
        r.detail ? `${info.name} key saved in this browser: ${r.detail}.`
          : r.free_tier ? `${info.name} key saved in this browser. It is a free key, so free models have a daily limit.`
          : `${info.name} key saved in this browser.`,
      );
      if (info.service === "openrouter") setChosen(false);
    } catch (e) {
      clearKeyFor(info.service);
      await refresh();
      notify(message(e));
    } finally {
      setBusy("");
    }
  }

  const loadSample = () => run("demo", async () => { await api.loadDemo(); go("matches"); });

  const keyRow = (info: KeyInfo) => (
    <div className="key-row" key={info.service}>
      <div className="key-top">
        <b>{info.name}</b>
        <span className="mono-label">{info.need}</span>
        {saved[info.service] && <span className="badge">✓ saved</span>}
      </div>
      <p>{info.does}</p>
      <p className="without"><b>Without it:</b> {info.without}</p>
      {saved[info.service] ? (
        <div className="row">
          <button type="button" className="linkish" disabled={busy !== ""} onClick={() => { clearKeyFor(info.service); refresh(); }}>Remove this key</button>
          <a href={info.link} target="_blank" rel="noreferrer">Manage on {info.name} ↗</a>
        </div>
      ) : (
        <form className="row" onSubmit={(e) => { e.preventDefault(); save(info); }}>
          <input
            className="field" type="password" autoComplete="off" spellCheck={false} placeholder={info.placeholder} aria-label={`${info.name} key`}
            value={drafts[info.service] ?? ""} onChange={(e) => setDrafts({ ...drafts, [info.service]: e.target.value })} style={{ flex: "1 1 220px" }}
          />
          <button className="btn small" type="submit" disabled={busy !== "" || !(drafts[info.service] ?? "").trim()}>
            {busy === info.service ? <><Spinner /> Checking</> : "Save key"}
          </button>
          <a href={info.link} target="_blank" rel="noreferrer">{info.linkText} ↗</a>
        </form>
      )}
      {getKeyFor(info.service) && !saved[info.service] && <p className="without">That key was not accepted. Check it and paste it again.</p>}
    </div>
  );

  // 1. A first-time visitor: two plain choices, nothing else.
  const choosing = !hasAi && empty && !state.demo && !chosen && !manage;
  // 2. The key panel: shown after "use my own resume", or from "Manage keys".
  const panel = !choosing && (manage || (chosen && !hasAi && !state.demo));

  return (
    <div className="publicbar">
      {state.demo && (
        <div className="pb-card sample">
          <div>
            <div className="mono-label">Sample data</div>
            <p><b>You are looking at a made-up candidate.</b> The jobs, scores, contacts and draft below are examples, so you can click through every step. Nothing here is real.</p>
          </div>
          <div className="row">
            <button className="btn dark small" type="button" disabled={busy !== ""} onClick={() => run("clear", async () => { await api.clearDemo(); setChosen(true); go("resume"); })}>
              {busy === "clear" ? <><Spinner /> Clearing</> : "Use my own resume"}
            </button>
          </div>
        </div>
      )}

      {choosing && (
        <div className="choose">
          <div className="choice primary">
            <div className="mono-label">Look around first</div>
            <h3>Explore with sample data</h3>
            <p>See every step with a made-up candidate: scored jobs, contacts and a draft email. No key and nothing to set up.</p>
            <button className="btn" type="button" disabled={busy !== ""} onClick={loadSample}>
              {busy === "demo" ? <><Spinner /> Loading</> : "Explore with sample data"}
            </button>
          </div>
          <div className="choice">
            <div className="mono-label">Use your own data</div>
            <h3>Start with my own resume</h3>
            <p>Runs the AI steps on your resume. It needs one free OpenRouter key, which stays in your browser.</p>
            <button className="btn ghost" type="button" disabled={busy !== ""} onClick={() => setChosen(true)}>Add my key</button>
          </div>
        </div>
      )}

      {panel && (
        <div className="pb-card keys">
          <div className="keys-head">
            <div className="mono-label">Your keys</div>
            <div className="row">
              {chosen && !hasAi && !state.demo && empty && <button type="button" className="btn ghost small" onClick={() => setChosen(false)}>← Back</button>}
              {manage && <button type="button" className="btn ghost small" onClick={() => setManage(false)}>Hide</button>}
            </div>
          </div>
          <p className="keys-intro">
            Each key stays in this browser, is sent only with your own requests, and is never saved on the server.
            {!hasAi && " Paste your OpenRouter key to run the AI steps; a free one works."}
          </p>
          <div className="keys-list one">{keyRow(ai)}</div>

          <button type="button" className="more-toggle" aria-expanded={more || optionalSaved} onClick={() => setMore(!more)}>
            {more || optionalSaved ? "▾" : "▸"} Optional keys: find contacts and add more job feeds (Hunter, Jooble, Adzuna)
          </button>
          {(more || optionalSaved) && (
            <>
              <div className="keys-list">{optional.map(keyRow)}</div>
              <p className="keys-off">
                <b>Not on the public site:</b> saving drafts to Gmail, the automatic 6-hour refresh, and reading job portals such as Internshala, Unstop,
                Instahyre and Foundit. To use those, run Doorknock yourself (the GitHub button has the clone command).
              </p>
            </>
          )}
          {empty && !state.demo && (
            <div className="pb-or">
              <span className="mono-label">or look around first</span>
              <button className="btn ghost small" type="button" disabled={busy !== ""} onClick={loadSample}>
                {busy === "demo" ? <><Spinner /> Loading</> : "Try with sample data"}
              </button>
            </div>
          )}
        </div>
      )}

      {!choosing && !panel && !state.demo && (
        <div className="pb-card keys slim">
          <p className="keys-sum">
            <span className="mono-label">Your keys</span>
            {KEYS.map((k) => (
              <span key={k.service} className={"keychip" + (saved[k.service] ? " on" : "")}>{saved[k.service] ? "✓ " : ""}{k.name}</span>
            ))}
          </p>
          <button type="button" className="btn ghost small" onClick={() => setManage(true)}>{hasAi ? "Manage keys" : "Add keys"}</button>
        </div>
      )}

      <div className="pb-foot">
        <span>Your resume and results are kept in a private workspace for {state.workspace_days} days.</span>
        <button
          type="button" className="linkish" disabled={busy !== ""}
          onClick={() => { if (window.confirm("Delete your resume, jobs and drafts from this site now?")) run("delete", async () => { await api.deleteWorkspace(); setChosen(false); go("resume"); }, "Your data was deleted."); }}
        >
          Delete my data
        </button>
      </div>
    </div>
  );
}
