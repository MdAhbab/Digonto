import { BrowserRouter, Routes, Route } from "react-router";
import { ThemeProvider } from "./lib/theme";
import { I18nProvider } from "./lib/i18n";
import { AuthProvider } from "./lib/auth";
import { RequireAuth } from "./components/RequireAuth";
import { Layout } from "./components/layout/Layout";
import { Landing } from "./pages/Landing";
import { Planner } from "./pages/Planner";
import { Ask } from "./pages/Ask";
import { Vault } from "./pages/Vault";
import { Funding } from "./pages/Funding";
import { Interview } from "./pages/Interview";
import { Destinations } from "./pages/Destinations";
import { Ledger } from "./pages/Ledger";
import { Security } from "./pages/Security";
import { About } from "./pages/About";
import { Auth } from "./pages/Auth";
import { NotFound } from "./pages/NotFound";

export default function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<Landing />} />
                {/* Agent / high-compute pages — require a session */}
                <Route path="/planner" element={<RequireAuth><Planner /></RequireAuth>} />
                <Route path="/ask" element={<RequireAuth><Ask /></RequireAuth>} />
                <Route path="/vault" element={<RequireAuth><Vault /></RequireAuth>} />
                <Route path="/funding" element={<RequireAuth><Funding /></RequireAuth>} />
                <Route path="/interview" element={<RequireAuth><Interview /></RequireAuth>} />
                {/* Public pages */}
                <Route path="/destinations" element={<Destinations />} />
                <Route path="/ledger" element={<Ledger />} />
                <Route path="/security" element={<Security />} />
                <Route path="/about" element={<About />} />
                <Route path="/auth" element={<Auth />} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </I18nProvider>
    </ThemeProvider>
  );
}
