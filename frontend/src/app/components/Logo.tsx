/* Digonto mark — a rising point crossing the horizon (দিগন্ত = horizon).
   No wordmark. Uses currentColor so it inverts cleanly between themes. */
export function Logo({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 40 40" className={className} fill="none" aria-label="Digonto" role="img">
      {/* horizon arc */}
      <path
        d="M4 26 C 12 20, 28 20, 36 26"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      {/* faint lower horizon */}
      <path
        d="M8 31 C 14 28, 26 28, 32 31"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        opacity="0.4"
      />
      {/* rising sun / departure point */}
      <circle cx="20" cy="16" r="4.4" stroke="currentColor" strokeWidth="2" />
      <circle cx="20" cy="16" r="1.4" fill="currentColor" />
      {/* flight path rising off the point */}
      <path
        d="M20 11.6 C 24 6, 30 5, 34 6"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        opacity="0.7"
      />
    </svg>
  );
}
