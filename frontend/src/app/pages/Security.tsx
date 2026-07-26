import { Lock, Server, Eye, KeyRound, ShieldCheck, FileWarning } from "lucide-react";
import { useI18n } from "../lib/i18n";
import { PageHeader } from "../components/PageHeader";
import { Reveal } from "../components/primitives";
import { Seo, SEO_ROUTES } from "../lib/seo";

export function Security() {
  const { t, lang } = useI18n();
  const meta = SEO_ROUTES["/security"];

  const commitments = [
    { icon: <Lock className="size-5" />, title: "Encrypted at rest & in transit", body: "Every document you upload is encrypted with AES-256 at rest and TLS 1.3 in transit. Keys are never stored beside the data." },
    { icon: <Eye className="size-5" />, title: "No selling, no referrals", body: "Digonto takes no commission from universities or agents. Your data is never sold, brokered, or used to advertise." },
    { icon: <KeyRound className="size-5" />, title: "You hold the keys", body: "Your password is hashed with Argon2id and never stored in plain text. You can export or permanently erase your entire vault at any time, no questions asked." },
    { icon: <Server className="size-5" />, title: "Minimal retention", body: "We keep only what your plan needs. Source snapshots are hashed and public; your personal files are private and yours." },
  ];

  const threats = [
    { icon: <FileWarning className="size-5" />, title: "Fraudulent agents", body: "We defend by citing every claim to an official portal snapshot, so no middleman can invent requirements or fees." },
    { icon: <ShieldCheck className="size-5" />, title: "Data breach", body: "Encryption at rest, scoped access tokens, and no plaintext document storage limit the blast radius of any incident." },
    { icon: <Eye className="size-5" />, title: "Surveillance / profiling", body: "No third-party trackers, no ad SDKs. Analytics are aggregate and stripped of personal identifiers." },
  ];

  return (
    <div>
      <Seo title={meta.title[lang]} description={meta.description[lang]} path={meta.path} noindex={meta.noindex} lang={lang} />
      <PageHeader eyebrow={t("nav.security")} title={t("sec.title")} sub={t("sec.sub")} />

      <div className="mx-auto max-w-[1180px] space-y-16 px-6 py-16 md:px-10">
        <section className="grid gap-px overflow-hidden rounded-[4px] border border-[var(--hairline)] bg-[var(--hairline)] md:grid-cols-2">
          {commitments.map((c, i) => (
            <Reveal key={c.title} delay={i * 0.06}>
              <div className="flex h-full flex-col bg-card p-7">
                <span className="text-primary">{c.icon}</span>
                <h3 className="mt-5 font-serif text-xl">{c.title}</h3>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{c.body}</p>
              </div>
            </Reveal>
          ))}
        </section>

        <section>
          <h2 className="font-serif text-2xl">{t("sec.threat")}</h2>
          <div className="mt-6 space-y-px overflow-hidden rounded-[4px] border border-[var(--hairline)]">
            {threats.map((th) => (
              <div key={th.title} className="flex gap-5 border-b border-[var(--hairline)] bg-card p-6 last:border-0">
                <span className="mt-0.5 text-[var(--gold)]">{th.icon}</span>
                <div>
                  <h3 className="font-serif text-lg">{th.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{th.body}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
