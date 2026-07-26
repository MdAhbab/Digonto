import { createContext, useContext } from "react";

export type Theme = "light" | "dark";

export interface ThemeCtx {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
}

/* Context object isolated in its own module so its identity is stable across
   HMR / Fast Refresh — prevents "must be used within ThemeProvider". */
export const ThemeContext = createContext<ThemeCtx | null>(null);

export function useTheme() {
  const c = useContext(ThemeContext);
  if (!c) throw new Error("useTheme must be used within ThemeProvider");
  return c;
}
