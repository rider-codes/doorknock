import { useState } from "react";

export const GITHUB_URL: string = (import.meta.env.VITE_GITHUB_URL as string | undefined) || "https://github.com/rider-codes/doorknock";

const MARK = (
  <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
    <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
  </svg>
);

/** A link to the code, with the clone command one click away. */
export function GithubButton() {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const command = `git clone ${GITHUB_URL}.git`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* the command is shown, so it can be copied by hand */
    }
  }

  return (
    <span className="gh">
      <button type="button" className="btn ghost small gh-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
        {MARK}<span>GitHub</span>
      </button>
      {open && (
        <div className="gh-pop" role="dialog" aria-label="Clone Doorknock">
          <div className="mono-label">Run it yourself</div>
          <p>Doorknock is open source. Clone it to use your own keys and keep everything on your machine.</p>
          <div className="gh-cmd"><code>{command}</code><button type="button" onClick={copy}>{copied ? "Copied" : "Copy"}</button></div>
          <a className="btn small" href={GITHUB_URL} target="_blank" rel="noreferrer">Open on GitHub ↗</a>
        </div>
      )}
    </span>
  );
}
