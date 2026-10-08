import type { AppState } from "../types";

type Allowance = AppState["allowances"][number];

const low = (a: Allowance) => a.left <= Math.max(2, Math.ceil(a.limit * 0.1));

/** What is limited, and how much is left. Shown beside the steps so nothing runs out unexpectedly. */
export function Allowances({ items, variant }: { items: Allowance[]; variant: "rail" | "strip" }) {
  if (items.length === 0) return null;
  return (
    <div className={"allow " + variant} aria-label="What is left to use">
      <div className="mono-label">Allowances</div>
      {items.map((a) => (
        <div key={a.key} className={"allow-row" + (low(a) ? " low" : "")}>
          <div className="allow-line">
            <span className="allow-name">{a.label}</span>
            <span className="allow-n">{a.left}<i> / {a.limit}</i></span>
          </div>
          <div className="allow-track" role="img" aria-label={`${a.left} of ${a.limit} ${a.unit} left ${a.period}`}>
            <div style={{ width: `${a.limit ? (a.left / a.limit) * 100 : 0}%` }} />
          </div>
          <div className="allow-sub">{a.unit} left {a.period}{a.detail ? ` · ${a.detail}` : ""}</div>
        </div>
      ))}
    </div>
  );
}
