import { motion, useInView, useReducedMotion, useMotionValue, useSpring, animate } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "./ui/utils";

/* ---- Reveal: intent-expressing entrance, gated by reduced-motion ---- */
export function Reveal({
  children,
  className,
  delay = 0,
  variant = "rise",
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  variant?: "rise" | "wipe" | "draw";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-12% 0px" });
  const reduce = useReducedMotion();

  const initial =
    variant === "wipe"
      ? { opacity: 0, clipPath: "inset(0 100% 0 0)" }
      : { opacity: 0, y: 24 };
  const shown =
    variant === "wipe"
      ? { opacity: 1, clipPath: "inset(0 0% 0 0)" }
      : { opacity: 1, y: 0 };

  return (
    <motion.div
      ref={ref}
      initial={reduce ? false : initial}
      animate={inView || reduce ? shown : initial}
      transition={{ duration: 0.7, delay, ease: [0.22, 1, 0.36, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

/* ---- Section shell with editorial eyebrow ---- */
export function Section({
  id,
  eyebrow,
  className,
  children,
}: {
  id?: string;
  eyebrow?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className={cn("mx-auto w-full max-w-[1180px] px-6 md:px-10", className)}>
      {eyebrow && (
        <Reveal>
          <div className="mb-6 flex items-center gap-3">
            <span className="h-px w-8 bg-[var(--hairline)]" />
            <span className="font-mono text-[0.7rem] uppercase tracking-[0.22em] text-muted-foreground">
              {eyebrow}
            </span>
          </div>
        </Reveal>
      )}
      {children}
    </section>
  );
}

/* ---- Mechanical flip counter ---- */
export function Counter({
  to,
  prefix = "",
  suffix = "",
  className,
}: {
  to: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-20% 0px" });
  const reduce = useReducedMotion();
  const [val, setVal] = useState(reduce ? to : 0);

  useEffect(() => {
    if (!inView || reduce) {
      setVal(to);
      return;
    }
    const controls = animate(0, to, {
      duration: 1.6,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setVal(Math.round(v)),
    });
    return () => controls.stop();
  }, [inView, to, reduce]);

  return (
    <span ref={ref} className={cn("font-mono tabular-nums tnum", className)}>
      {prefix}
      {val.toLocaleString("en-US")}
      {suffix}
    </span>
  );
}

/* ---- Citation stamp: presses onto the page ---- */
export function CitationStamp({
  id,
  onClick,
  className,
}: {
  id: string;
  onClick?: () => void;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "group inline-flex items-center gap-1.5 rounded-[3px] border border-[var(--gold)]/60 bg-[var(--gold)]/8 px-2 py-0.5 align-super text-[0.62rem] font-mono uppercase tracking-wider text-[var(--gold)] transition-colors hover:bg-[var(--gold)]/16 focus-ring",
        className,
      )}
      aria-label={`Citation ${id}`}
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-[var(--gold)]" />
      {id}
    </button>
  );
}

/* ---- Wax/embossed seal (completed milestone) ---- */
export function Seal({ label, className }: { label?: string; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-8 w-8 items-center justify-center rounded-full border border-[var(--gold)] text-[var(--gold)]",
        className,
      )}
      title={label}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
        <path d="M4 12.5L9.5 18L20 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

/* ---- Animated horizon line (used as section divider) ---- */
export function HorizonRule({ className }: { className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true });
  const reduce = useReducedMotion();
  return (
    <div ref={ref} className={cn("relative h-px w-full overflow-hidden bg-[var(--hairline)]", className)}>
      <motion.span
        className="absolute inset-y-0 left-0 bg-primary"
        initial={reduce ? { width: "100%" } : { width: 0 }}
        animate={inView ? { width: "100%" } : {}}
        transition={{ duration: 1.1, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  );
}

export { motion, useMotionValue, useSpring };
