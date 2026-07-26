import { Reveal } from "./primitives";
import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  sub,
  children,
}: {
  eyebrow?: string;
  title: string;
  sub?: string;
  children?: ReactNode;
}) {
  return (
    <div className="border-b border-[var(--hairline)] bg-paper-2">
      <div className="mx-auto max-w-[1180px] px-6 py-16 md:px-10 md:py-20">
        {eyebrow && (
          <Reveal>
            <div className="mb-5 flex items-center gap-3">
              <span className="h-px w-8 bg-primary" />
              <span className="font-mono text-[0.7rem] uppercase tracking-[0.22em] text-muted-foreground">
                {eyebrow}
              </span>
            </div>
          </Reveal>
        )}
        <Reveal delay={0.05}>
          <h1 className="max-w-3xl font-serif text-[2rem] leading-tight md:text-[2.8rem]">{title}</h1>
        </Reveal>
        {sub && (
          <Reveal delay={0.12}>
            <p className="mt-5 max-w-2xl text-muted-foreground md:text-lg">{sub}</p>
          </Reveal>
        )}
        {children && (
          <Reveal delay={0.18}>
            <div className="mt-8">{children}</div>
          </Reveal>
        )}
      </div>
    </div>
  );
}
