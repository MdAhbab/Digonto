import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router";
import { ThemeProvider } from "./lib/theme";
import { I18nProvider } from "./lib/i18n";
import { AuthProvider } from "./lib/auth";
import { RequireAuth, RequireRole } from "./components/RequireAuth";
import { Layout } from "./components/layout/Layout";
import { RouteFallback } from "./components/RouteFallback";

/* Route-level code splitting.
   Everything used to arrive in one 1.2 MB chunk, so a student opening /auth on a
   mid-range Android over a slow connection downloaded Three.js, the planner, and
   the moderator console before they could type an email address. The design
   brief's budget is under 300 KB gzip on first load with the 3D scenes lazy, and
   that is only achievable if the router splits.

   Landing is eager: it is the entry point for most visits, and lazily loading it
   would only add a round trip to the one route that must feel instant. Every
   other page is deferred, which also means the Three.js hero and the globe are
   fetched by the routes that actually render them. */
import { Landing } from "./pages/Landing";

const Planner = lazy(() => import("./pages/Planner").then(m => ({ default: m.Planner })));
const Ask = lazy(() => import("./pages/Ask").then(m => ({ default: m.Ask })));
const Vault = lazy(() => import("./pages/Vault").then(m => ({ default: m.Vault })));
const Funding = lazy(() => import("./pages/Funding").then(m => ({ default: m.Funding })));
const Interview = lazy(() => import("./pages/Interview").then(m => ({ default: m.Interview })));
const Destinations = lazy(() => import("./pages/Destinations").then(m => ({ default: m.Destinations })));
const Ledger = lazy(() => import("./pages/Ledger").then(m => ({ default: m.Ledger })));
const Security = lazy(() => import("./pages/Security").then(m => ({ default: m.Security })));
const About = lazy(() => import("./pages/About").then(m => ({ default: m.About })));
const Auth = lazy(() => import("./pages/Auth").then(m => ({ default: m.Auth })));
const Profile = lazy(() => import("./pages/Profile"));
const Moderator = lazy(() => import("./pages/Moderator").then(m => ({ default: m.Moderator })));
const NotFound = lazy(() => import("./pages/NotFound").then(m => ({ default: m.NotFound })));

export default function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <AuthProvider>
          <BrowserRouter>
            {/* One boundary inside Layout, so the header and footer stay put
                while a route chunk arrives. A fallback outside Layout would
                blank the whole page and shift everything on every navigation. */}
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<Landing />} />
                {/* Agent / high-compute pages — require a session */}
                <Route path="/planner" element={<RequireAuth><Suspense fallback={<RouteFallback />}><Planner /></Suspense></RequireAuth>} />
                <Route path="/ask" element={<RequireAuth><Suspense fallback={<RouteFallback />}><Ask /></Suspense></RequireAuth>} />
                <Route path="/vault" element={<RequireAuth><Suspense fallback={<RouteFallback />}><Vault /></Suspense></RequireAuth>} />
                <Route path="/funding" element={<RequireAuth><Suspense fallback={<RouteFallback />}><Funding /></Suspense></RequireAuth>} />
                <Route path="/interview" element={<RequireAuth><Suspense fallback={<RouteFallback />}><Interview /></Suspense></RequireAuth>} />
                {/* Moderator console — session + role gated */}
                <Route path="/profile" element={<RequireAuth><Suspense fallback={<RouteFallback />}><Profile /></Suspense></RequireAuth>} />
                <Route path="/moderator" element={<RequireRole role="moderator"><Suspense fallback={<RouteFallback />}><Moderator /></Suspense></RequireRole>} />
                {/* Public pages */}
                <Route path="/destinations" element={<Suspense fallback={<RouteFallback />}><Destinations /></Suspense>} />
                <Route path="/ledger" element={<Suspense fallback={<RouteFallback />}><Ledger /></Suspense>} />
                <Route path="/security" element={<Suspense fallback={<RouteFallback />}><Security /></Suspense>} />
                <Route path="/about" element={<Suspense fallback={<RouteFallback />}><About /></Suspense>} />
                <Route path="/auth" element={<Suspense fallback={<RouteFallback />}><Auth /></Suspense>} />
                <Route path="*" element={<Suspense fallback={<RouteFallback />}><NotFound /></Suspense>} />
              </Route>
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </I18nProvider>
    </ThemeProvider>
  );
}
