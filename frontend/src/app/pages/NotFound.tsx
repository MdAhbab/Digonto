import { Link } from "react-router";
import { useI18n } from "../lib/i18n";

export function NotFound() {
  const { t } = useI18n();
  return (
    <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-2xl flex-col items-center justify-center px-6 py-20 text-center">
      {/* boarding pass torn in half */}
      <div className="relative w-full max-w-md">
        <div className="grid grid-cols-[1fr_auto] overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-card">
          <div className="p-6 text-left">
            <div className="font-mono text-[0.62rem] uppercase tracking-[0.24em] text-muted-foreground">Boarding pass</div>
            <div className="mt-3 font-serif text-2xl">DAC → ???</div>
            <div className="mt-4 grid grid-cols-2 gap-3 font-mono text-xs text-muted-foreground">
              <div><div className="uppercase tracking-wider">Gate</div><div className="text-foreground">—</div></div>
              <div><div className="uppercase tracking-wider">Seat</div><div className="text-foreground">404</div></div>
            </div>
          </div>
          {/* torn stub with perforation */}
          <div className="relative flex items-center border-l border-dashed border-[var(--hairline)] p-6">
            <div className="font-mono text-4xl text-primary [writing-mode:vertical-rl]">404</div>
          </div>
        </div>
      </div>

      <h1 className="mt-10 font-serif text-3xl">{t("nf.title")}</h1>
      <p className="mt-3 text-muted-foreground">{t("nf.sub")}</p>
      <Link to="/" className="focus-ring mt-8 inline-flex h-11 items-center rounded-[3px] bg-primary px-6 text-primary-foreground transition-opacity hover:opacity-90">
        {t("nf.home")}
      </Link>
    </div>
  );
}
