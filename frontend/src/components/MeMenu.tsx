import { useEffect, useId, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import type { User } from "../types";

/** Compact account menu: Profile, Account, Settings (admins), Sign out. A disclosure, not an ARIA menu. */
export function MeMenu({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();
  const { pathname } = useLocation();

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const active = ["/profile", "/account", "/settings"].some((p) => pathname.startsWith(p));
  const name = user.display_name || user.email;
  const link = ({ isActive }: { isActive: boolean }) => (isActive ? "active" : "");

  return (
    <div
      className="me-menu"
      ref={wrap}
      onBlur={(e) => {
        if (open && !e.currentTarget.contains(e.relatedTarget as Node | null) && e.relatedTarget) setOpen(false);
      }}
    >
      <button
        ref={button}
        type="button"
        className={`me-button ${active ? "active" : ""}`}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        title={user.email}
      >
        <span className="me-avatar" aria-hidden="true">
          {name.trim().charAt(0).toUpperCase() || "?"}
        </span>
        Me <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="me-panel" id={id}>
          <p className="me-who small">
            <strong>{user.display_name || "Signed in"}</strong>
            <span className="muted">{user.email}</span>
          </p>
          <NavLink to="/profile" className={link}>
            Profile
          </NavLink>
          <NavLink to="/account" className={link}>
            Account
          </NavLink>
          {user.is_admin && (
            <NavLink to="/settings" className={link}>
              Settings (admin)
            </NavLink>
          )}
          <button type="button" className="me-signout" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}
