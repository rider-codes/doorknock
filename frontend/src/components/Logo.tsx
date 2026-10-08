export function Logo({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--bg)"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 21V9a6 6 0 0 1 12 0v12" />
      <path d="M2.5 21h17" />
      <circle cx="13.5" cy="14.5" r="1" fill="var(--acc)" stroke="var(--acc)" />
      <path d="M20 8.5l1.8-1M20.5 12h2" />
    </svg>
  );
}

export function Spinner() {
  return <span className="spin" role="status" aria-label="Working" />;
}
