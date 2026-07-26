/* The low-power stand-in for the WebGL hero.

   Pure SVG, no WebGL context, no animation loop: a single arc of the earth's
   limb, a thin flight path lifting off from Dhaka, and a scatter of waypoints.
   It is drawn rather than degraded — the point of the fallback is that a student
   on a 2 GB phone sees something composed, not an empty box where the good
   version would have been.

   The only motion is a one-shot stroke draw on the flight path, gated by
   prefers-reduced-motion in CSS rather than in JS so it costs nothing to
   evaluate. Everything is theme-token coloured, so it tracks the light/dark
   cross-fade with the rest of the page. */
export function StaticHorizon({ theme }: { theme: "light" | "dark" }) {
  const isDark = theme === "dark";
  const limb = isDark ? "#4ba38c" : "#0f3d33";
  const gold = isDark ? "#cba85c" : "#9a7b32";

  return (
    <div className="h-full w-full" aria-hidden>
      <svg
        viewBox="0 0 800 500"
        preserveAspectRatio="xMidYMid slice"
        className="h-full w-full"
      >
        {/* earth's limb: a wide, shallow arc across the lower third */}
        <path
          d="M -120 470 Q 400 300 920 470"
          fill="none"
          stroke={limb}
          strokeWidth="1.25"
          opacity={isDark ? 0.55 : 0.4}
        />
        {/* atmosphere: the same arc, thicker and faint, sitting just above */}
        <path
          d="M -120 462 Q 400 292 920 462"
          fill="none"
          stroke={limb}
          strokeWidth="14"
          opacity={isDark ? 0.1 : 0.06}
        />

        {/* flight path out of Dhaka */}
        <path
          className="horizon-path"
          d="M 392 352 C 470 300 560 232 700 150"
          fill="none"
          stroke={gold}
          strokeWidth="1"
          strokeLinecap="round"
          opacity="0.75"
        />

        {/* Dhaka */}
        <circle cx="392" cy="352" r="3" fill={gold} />
        <circle cx="392" cy="352" r="8" fill="none" stroke={gold} strokeWidth="0.75" opacity="0.45" />

        {/* waypoints along the path */}
        <circle cx="470" cy="300" r="1.25" fill={gold} opacity="0.5" />
        <circle cx="560" cy="232" r="1.25" fill={gold} opacity="0.5" />
        <circle cx="700" cy="150" r="1.75" fill={gold} opacity="0.7" />

        {/* a few fixed stars, only in the dark theme */}
        {isDark && (
          <g fill={gold} opacity="0.35">
            <circle cx="120" cy="90" r="1" />
            <circle cx="255" cy="170" r="0.75" />
            <circle cx="620" cy="70" r="1" />
            <circle cx="735" cy="255" r="0.75" />
            <circle cx="80" cy="300" r="0.75" />
          </g>
        )}
      </svg>
    </div>
  );
}
