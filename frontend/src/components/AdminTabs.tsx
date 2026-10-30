import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuth } from "../auth";

const TABS = [
  { to: "/settings", label: "App settings", end: true },
  { to: "/settings/data", label: "Data", end: false },
  { to: "/settings/users", label: "Users", end: false },
];

/** Admin area frame: heading, section links and the admins-only guard. */
export function AdminFrame({ children, intro }: { children: ReactNode; intro?: ReactNode }) {
  const { user } = useAuth();
  if (!user?.is_admin) {
    return (
      <div className="stack">
        <h1>Settings</h1>
        <div className="alert alert-info">Only admins can change app settings.</div>
      </div>
    );
  }
  return (
    <div className="stack">
      <div>
        <h1>Settings</h1>
        {intro}
      </div>
      <nav className="tabs link-tabs" aria-label="Admin sections">
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => (isActive ? "active" : "")}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      {children}
    </div>
  );
}
