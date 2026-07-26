import { Sun, Moon } from "lucide-react";
import { useTheme } from "../../lib/theme";
import { useI18n } from "../../lib/i18n";

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const { t } = useI18n();
  return (
    <button
      onClick={toggleTheme}
      className="focus-ring inline-flex size-9 items-center justify-center rounded-[3px] border border-border text-muted-foreground transition-colors hover:text-foreground"
      aria-label={theme === "light" ? t("toggle.theme.dark") : t("toggle.theme.light")}
    >
      {theme === "light" ? <Moon className="size-4" /> : <Sun className="size-4" />}
    </button>
  );
}

export function LangToggle() {
  const { lang, toggleLang } = useI18n();
  return (
    <button
      onClick={toggleLang}
      className="focus-ring inline-flex h-9 items-center rounded-[3px] border border-border px-3 text-xs transition-colors hover:text-foreground"
      aria-label="Switch language"
    >
      <span className={lang === "en" ? "font-sans" : "opacity-40"}>EN</span>
      <span className="mx-1.5 h-3 w-px bg-border" />
      <span className={lang === "bn" ? "font-sans-bn" : "opacity-40"} style={{ fontFamily: "var(--font-sans-bn)" }}>
        বাং
      </span>
    </button>
  );
}
