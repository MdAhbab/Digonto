import { useEffect } from "react";
import { Outlet, useLocation } from "react-router";
import DeletionBanner from "../DeletionBanner";
import { SiteHeader } from "./SiteHeader";
import { SiteFooter } from "./SiteFooter";

export function Layout() {
  const { pathname } = useLocation();

  // scroll to top on route change
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [pathname]);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* Above the header, and on every route. A student whose account is scheduled
          for deletion should not have to visit a settings page to find that out;
          scheduling signs every session out, so the likely reader is somebody
          signing in weeks later having forgotten they asked. Renders nothing at all
          when no deletion is pending, which is the ordinary case. */}
      <DeletionBanner />
      <SiteHeader />

      <main className="flex-1">
        <Outlet />
      </main>

      <SiteFooter />
    </div>
  );
}
