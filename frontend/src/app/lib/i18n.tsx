import { useEffect, useState, type ReactNode } from "react";
import { I18nContext, dict, type Lang } from "./i18n-context";

// Re-export so existing imports (`from "../lib/i18n"`) keep working.
export { useI18n, dict } from "./i18n-context";
export type { Lang } from "./i18n-context";

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    if (typeof window === "undefined") return "en";
    return (localStorage.getItem("digonto-lang") as Lang) || "en";
  });

  useEffect(() => {
    localStorage.setItem("digonto-lang", lang);
    document.documentElement.lang = lang;
    document.documentElement.classList.toggle("lang-bn", lang === "bn");
  }, [lang]);

  const setLang = (l: Lang) => setLangState(l);
  const toggleLang = () => setLangState((p) => (p === "en" ? "bn" : "en"));
  const t = (key: string) => {
    const entry = dict[key];
    if (!entry) return key;
    return entry[lang];
  };

  return <I18nContext.Provider value={{ lang, setLang, toggleLang, t }}>{children}</I18nContext.Provider>;
}
