/**
 * The profile in use, when it's someone else's: another user who shared their whole profile with you.
 * Every API request then carries its id (see api.ts) and works on their data. It's kept per browser tab
 * (sessionStorage), so a new tab starts on your own profile, and switching reloads the app so nothing
 * from the previous profile is left on screen or in the cache.
 */
export type ActiveProfile = { id: number; name: string };

const KEY = "mealplan.profile";
const NOTICE_KEY = "mealplan.profile-notice";

export function activeProfile(): ActiveProfile | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as ActiveProfile) : null;
  } catch {
    return null;
  }
}

/** Switch to someone's profile (null: your own) and start over on Today, with an optional notice to show. */
export function switchProfile(profile: ActiveProfile | null, notice?: string): void {
  try {
    if (profile) sessionStorage.setItem(KEY, JSON.stringify(profile));
    else sessionStorage.removeItem(KEY);
    if (notice) sessionStorage.setItem(NOTICE_KEY, notice);
  } catch {
    // storage blocked: requests go out without the header, i.e. as yourself
  }
  window.location.assign("/");
}

/** Forget the profile without reloading (signing out or in). */
export function clearProfile(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // nothing stored
  }
}

/** The notice left by the last switch, once. */
export function takeProfileNotice(): string | null {
  try {
    const notice = sessionStorage.getItem(NOTICE_KEY);
    sessionStorage.removeItem(NOTICE_KEY);
    return notice;
  } catch {
    return null;
  }
}

export const PROFILE_HEADER = "X-Mealplan-Profile";
export const PROFILE_GONE_HEADER = "X-Mealplan-Profile-Gone";
