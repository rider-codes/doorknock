export const tone = (score: number) => (score >= 80 ? "strong" : score >= 65 ? "good" : "weak");
export const TONE_LABEL = { strong: "Strong", good: "Good", weak: "Stretch" } as const;

/** The score ring used in the workspace's match list and in the landing page's example. */
export function Ring({ score, size = 52 }: { score: number; size?: number }) {
  const r = size / 2 - 4;
  const c = 2 * Math.PI * r;
  return (
    <svg className={"mring " + tone(score)} width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`Fit score ${score} out of 100`}>
      <circle cx={size / 2} cy={size / 2} r={r} className="bg" />
      <circle cx={size / 2} cy={size / 2} r={r} className="fg" strokeDasharray={`${(c * score) / 100} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle">{score}</text>
    </svg>
  );
}
