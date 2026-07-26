/* Shown while a lazily loaded route chunk arrives.

   Deliberately a skeleton of the shared page shape rather than a spinner. Every
   page in this product opens with a PageHeader (eyebrow rule, serif title,
   sub-line) above a content band, so reserving those exact bands means the real
   page replaces the placeholder without the layout shifting under the reader —
   which the design brief asks for specifically, because the audience is on slow
   connections where that shift is most visible.

   No spinner, no pulsing dot. The tone is a page being set, not a system
   thinking: the bands hold still and only their tone breathes. */
export function RouteFallback() {
  return (
    <div aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading</span>

      {/* PageHeader band */}
      <div className="border-b border-[var(--hairline)] bg-paper-2">
        <div className="mx-auto max-w-[1180px] px-6 py-16 md:px-10 md:py-20">
          <div className="mb-5 flex items-center gap-3">
            <span className="h-px w-8 bg-primary/40" />
            <Bar className="h-2 w-28" />
          </div>
          <Bar className="h-9 w-full max-w-xl md:h-12" />
          <Bar className="mt-5 h-4 w-full max-w-md" />
        </div>
      </div>

      {/* Content band */}
      <div className="mx-auto max-w-[1180px] px-6 py-14 md:px-10">
        <div className="space-y-4">
          <Bar className="h-4 w-11/12" />
          <Bar className="h-4 w-10/12" />
          <Bar className="h-4 w-8/12" />
        </div>
      </div>
    </div>
  );
}

function Bar({ className = "" }: { className?: string }) {
  return (
    <div
      className={`skeleton-band rounded-[2px] bg-[var(--hairline)] ${className}`}
    />
  );
}
