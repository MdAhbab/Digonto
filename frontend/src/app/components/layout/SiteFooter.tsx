import { Link } from "react-router";
import { useI18n } from "../../lib/i18n";

export function SiteFooter() {
  const { t } = useI18n();
  const year = new Date().getFullYear();

  const cols: { head: string; items: { to: string; key: string }[] }[] = [
    {
      head: "footer.product",
      items: [
        { to: "/planner", key: "nav.planner" },
        { to: "/ask", key: "nav.ask" },
        { to: "/vault", key: "nav.vault" },
        { to: "/funding", key: "nav.funding" },
        { to: "/interview", key: "nav.interview" },
      ],
    },
    {
      head: "footer.company",
      items: [
        { to: "/about", key: "nav.about" },
        { to: "/destinations", key: "nav.destinations" },
        { to: "/ledger", key: "nav.ledger" },
      ],
    },
    {
      head: "footer.legal",
      items: [
        { to: "/security", key: "nav.security" },
        { to: "/auth", key: "nav.signin" },
      ],
    },
  ];

  return (
    <footer className="relative z-10 mt-32 border-t border-[var(--hairline)] bg-paper-2">
      <div className="mx-auto max-w-[1180px] px-6 py-16 md:px-10">
        <div className="grid gap-12 md:grid-cols-[1.4fr_repeat(3,1fr)]">
          <div>
            <div className="font-serif text-2xl">{t("brand.name")}</div>
            <p className="mt-3 max-w-xs text-sm text-muted-foreground">{t("brand.tagline")}</p>
            <p className="mt-6 font-mono text-[0.7rem] uppercase tracking-[0.2em] text-muted-foreground">
              {t("common.free")}
            </p>
          </div>
          {cols.map((c) => (
            <nav key={c.head}>
              <div className="mb-4 font-mono text-[0.68rem] uppercase tracking-[0.2em] text-muted-foreground">
                {t(c.head)}
              </div>
              <ul className="space-y-2.5">
                {c.items.map((it) => (
                  <li key={it.to}>
                    <Link to={it.to} className="focus-ring text-sm text-foreground/80 transition-colors hover:text-primary">
                      {t(it.key)}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>

        <div className="mt-14 border-t border-[var(--hairline)] pt-8">
          <p className="max-w-3xl text-sm text-muted-foreground">{t("footer.sdg")}</p>
          <div className="mt-6 flex flex-col justify-between gap-2 text-xs text-muted-foreground md:flex-row">
            <span>© {year} {t("brand.name")}. {t("footer.rights")}</span>
            <span className="font-mono uppercase tracking-[0.18em]">Dhaka · 23.8103° N, 90.4125° E</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
