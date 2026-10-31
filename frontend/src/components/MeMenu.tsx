import { useEffect, useId, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { activeProfile, switchProfile } from "../profile";
import type { User } from "../types";
import { VisuallyHidden } from "./a11y";
import { useSharedProfiles } from "./Sharing";

/**
 * Compact account menu: switching between your profile and those shared with you, then Profile, Account,
 * Settings (admins), Sign out. A disclosure, not an ARIA menu.
 */
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
  const using = activeProfile();
  const others = useSharedProfiles().data?.shared_with_me ?? [];
  const shown = using?.name ?? name;
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
        className={`me-button ${active ? "active" : ""} ${using ? "me-button-other" : ""}`}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        title={user.email}
      >
        <span className="me-avatar" aria-hidden="true">
          {shown.trim().charAt(0).toUpperCase() || "?"}
        </span>
        {using ? (
          <>
            <span className="me-using">{using.name}</span>
            <VisuallyHidden>(using their profile; account and profile menu)</VisuallyHidden>
          </>
        ) : (
          <>
            Me<VisuallyHidden>(account menu)</VisuallyHidden>
          </>
        )}{" "}
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <nav className="me-panel" id={id} aria-label="Account">
          <p className="me-who small">
            <strong>{user.display_name || "Signed in"}</strong>
            <span className="muted">{user.email}</span>
          </p>
          {others.length > 0 && (
            <div className="me-profiles" role="group" aria-labelledby={`${id}-profiles`}>
              <p className="me-label small muted" id={`${id}-profiles`}>
                Switch profile
              </p>
              <button
                type="button"
                className="me-profile"
                aria-current={using ? undefined : "true"}
                onClick={() => using && switchProfile(null)}
              >
                Your own
              </button>
              {others.map((p) => (
                <button
                  key={p.user_id}
                  type="button"
                  className="me-profile"
                  aria-current={using?.id === p.user_id ? "true" : undefined}
                  onClick={() => using?.id !== p.user_id && switchProfile({ id: p.user_id, name: p.name })}
                >
                  {p.name}
                  {!p.can_edit && <span className="muted small"> · view only</span>}
                </button>
              ))}
            </div>
          )}
          <NavLink to="/profile" className={link}>
            {using ? `${using.name}'s profile` : "Profile"}
          </NavLink>
          <NavLink to="/account" className={link}>
            {using ? "Your account" : "Account"}
          </NavLink>
          <NavLink to="/about/data" className={link}>
            Data sources & credits
          </NavLink>
          {user.is_admin && (
            <NavLink to="/settings" className={link}>
              Settings (admin)
            </NavLink>
          )}
          <button type="button" className="me-signout" onClick={onSignOut}>
            Sign out
          </button>
        </nav>
      )}
    </div>
  );
}
