import { NavLink, Outlet } from "react-router-dom";
import { SettingsPanel } from "./SettingsPanel";

const navItem =
  "px-3 py-2 rounded-md text-sm font-medium hover:bg-neutral-100 dark:hover:bg-neutral-800";
const navItemActive = "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900";

export function Layout() {
  return (
    <div className="min-h-screen bg-neutral-50 text-neutral-900 dark:bg-neutral-950 dark:text-neutral-100">
      <header className="border-b border-neutral-200 dark:border-neutral-800">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-6">
            <span className="text-lg font-semibold">CORP</span>
            <nav className="flex gap-1">
              <NavLink
                to="/"
                end
                className={({ isActive }) => `${navItem} ${isActive ? navItemActive : ""}`}
              >
                Creators
              </NavLink>
              <NavLink
                to="/runs"
                className={({ isActive }) => `${navItem} ${isActive ? navItemActive : ""}`}
              >
                Research Runs
              </NavLink>
              <NavLink
                to="/campaigns"
                className={({ isActive }) => `${navItem} ${isActive ? navItemActive : ""}`}
              >
                Campaigns
              </NavLink>
              <NavLink
                to="/jobs"
                className={({ isActive }) => `${navItem} ${isActive ? navItemActive : ""}`}
              >
                Jobs
              </NavLink>
            </nav>
          </div>
          <SettingsPanel />
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
