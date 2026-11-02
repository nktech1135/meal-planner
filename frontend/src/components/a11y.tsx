import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentPropsWithRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { matchPath, useLocation } from "react-router-dom";
import { activeProfile } from "../profile";

/*
 * Screen-reader plumbing shared by every page: visually hidden text, a polite/assertive announcer,
 * focus-safe buttons, per-route titles with focus moved to the new page's heading, and the tab pattern.
 */

export function VisuallyHidden({ children }: { children: ReactNode }) {
  return <span className="sr-only">{children}</span>;
}

/** Text for links that open a new tab: an icon for sight, words for screen readers. */
export function NewTab() {
  return (
    <>
      {" "}
      <span aria-hidden="true">↗</span>
      <VisuallyHidden>(opens in a new tab)</VisuallyHidden>
    </>
  );
}

// ---------------------------------------------------------------------------------------------
// Announcer: two live regions that exist from the first render, so messages are reliably read.

type Announce = (message: string, opts?: { assertive?: boolean }) => void;
const AnnounceContext = createContext<Announce>(() => {});

export function AnnouncerProvider({ children }: { children: ReactNode }) {
  const [polite, setPolite] = useState("");
  const [assertive, setAssertive] = useState("");
  const queue = useRef<{ polite: string[]; assertive: string[] }>({ polite: [], assertive: [] });
  const timers = useRef<{ flush?: number; clear?: number }>({});

  const announce = useCallback<Announce>((message, opts) => {
    const text = message.replace(/\s+/g, " ").trim();
    if (!text) return;
    const q = opts?.assertive ? queue.current.assertive : queue.current.polite;
    if (!q.includes(text)) q.push(text);
    // Empty the regions first so a repeated message is read again; messages in the same tick are joined.
    setPolite("");
    setAssertive("");
    window.clearTimeout(timers.current.flush);
    window.clearTimeout(timers.current.clear);
    timers.current.flush = window.setTimeout(() => {
      setPolite(queue.current.polite.join(" "));
      setAssertive(queue.current.assertive.join(" "));
      queue.current = { polite: [], assertive: [] };
      timers.current.clear = window.setTimeout(() => {
        setPolite("");
        setAssertive("");
      }, 8000);
    }, 120);
  }, []);

  useEffect(() => () => {
    window.clearTimeout(timers.current.flush);
    window.clearTimeout(timers.current.clear);
  }, []);

  return (
    <AnnounceContext.Provider value={announce}>
      {children}
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true" data-announcer="polite">
        {polite}
      </div>
      <div className="sr-only" role="alert" aria-live="assertive" aria-atomic="true" data-announcer="assertive">
        {assertive}
      </div>
    </AnnounceContext.Provider>
  );
}

export function useAnnounce(): Announce {
  return useContext(AnnounceContext);
}

/**
 * Announce an element's text whenever it changes to something new (for notices that appear
 * conditionally: a live role on an element that's only just been inserted is often not read).
 */
export function useAnnounceText<T extends HTMLElement>(opts?: { assertive?: boolean }) {
  const ref = useRef<T>(null);
  const last = useRef("");
  const announce = useAnnounce();
  const assertive = opts?.assertive ?? false;
  useEffect(() => {
    const text = ref.current?.textContent?.replace(/\s+/g, " ").trim() ?? "";
    if (text && text !== last.current) announce(text, { assertive });
    last.current = text;
  });
  return ref;
}

/** Announce `message` when it changes to a new non-empty value. */
export function useAnnounceWhen(message: string | null | undefined, opts?: { assertive?: boolean }) {
  const announce = useAnnounce();
  const last = useRef<string | null | undefined>(null);
  const assertive = opts?.assertive ?? false;
  useEffect(() => {
    if (message && message !== last.current) announce(message, { assertive });
    last.current = message;
  }, [message, announce, assertive]);
}

// ---------------------------------------------------------------------------------------------
// Focus

/** Move focus to an element that may not be focusable itself (a heading, a notice). */
export function focusElement(el: HTMLElement | null | undefined, opts?: { preventScroll?: boolean }) {
  if (!el) return;
  if (!el.matches("a[href], button, input, select, textarea, [tabindex]")) el.setAttribute("tabindex", "-1");
  el.focus({ preventScroll: opts?.preventScroll });
}

/** Focus `get()` on the next frame (after React has rendered what it returns). */
export function focusSoon(get: () => HTMLElement | null | undefined) {
  requestAnimationFrame(() => focusElement(get()));
}

/** Is focus nowhere useful (the element that had it was removed or disabled)? */
const focusLost = () => !document.activeElement || document.activeElement === document.body;

/**
 * After an action that may remove the control that had focus (deleting a row, a button that goes away),
 * put focus on a sensible fallback, but only if it was actually lost.
 */
export function rescueFocus(fallback: () => HTMLElement | null | undefined, ms = 3000) {
  // The control usually goes away only once refetched data arrives, so keep an eye out for a while.
  const until = performance.now() + ms;
  const tick = () => {
    if (focusLost()) focusElement(fallback());
    else if (performance.now() < until) window.setTimeout(tick, 50);
  };
  window.setTimeout(tick, 0);
}

/**
 * For inline panels and editors: when `open` goes from true to false and focus was lost with the
 * panel, put it back on the control that opened it. Returns the ref for that control.
 */
export function useReturnFocus<T extends HTMLElement>(open: boolean) {
  const ref = useRef<T>(null);
  const was = useRef(open);
  useEffect(() => {
    if (was.current && !open) {
      requestAnimationFrame(() => {
        if (focusLost()) ref.current?.focus();
      });
    }
    was.current = open;
  }, [open]);
  return ref;
}

/**
 * A <button> that doesn't throw focus away. A focused control that becomes `disabled` (e.g. while its
 * own request is running) drops focus to <body>, which sends screen readers back to the top of the page.
 * While focused, this one is only aria-disabled (and ignores clicks); otherwise it's really disabled.
 */
export function Button({ disabled, onClick, onFocus, onBlur, ...rest }: ComponentPropsWithRef<"button">) {
  const [focused, setFocused] = useState(false);
  return (
    <button
      {...rest}
      disabled={disabled && !focused}
      aria-disabled={disabled || undefined}
      onFocus={(e) => {
        setFocused(true);
        onFocus?.(e);
      }}
      onBlur={(e) => {
        setFocused(false);
        onBlur?.(e);
      }}
      onClick={(e) => {
        if (disabled) {
          e.preventDefault();
          return;
        }
        onClick?.(e);
      }}
    />
  );
}

// ---------------------------------------------------------------------------------------------
// Page titles and route changes

const ROUTE_TITLES: [string, string][] = [
  ["/", "Today"],
  ["/log", "Add entry"],
  ["/plan", "Plan"],
  ["/plan/shopping", "Shopping list"],
  ["/exercise", "Exercise"],
  ["/trends", "Trends"],
  ["/foods", "Foods"],
  ["/foods/new", "New food"],
  ["/foods/:id/edit", "Edit food"],
  ["/foods/:id", "Food"],
  ["/recipes", "Recipes"],
  ["/recipes/new", "New recipe"],
  ["/recipes/:id", "Recipe"],
  ["/supplements/check", "Supplement check"],
  ["/advisor", "Advisor"],
  ["/advisor/:id", "Advisor"],
  ["/profile", "Profile"],
  ["/account", "Account"],
  ["/about/data", "Data sources & credits"],
  ["/settings", "Settings"],
  ["/settings/data", "Data – Settings"],
  ["/settings/users", "Users – Settings"],
  ["/reset-password", "Choose a password"],
];

export const APP_NAME = "Mealplan";
/** Page title; while using someone else's profile it says whose, so tabs and screen readers make it plain. */
export const titleText = (title: string) => {
  const profile = activeProfile();
  return profile ? `${title} – ${profile.name}'s profile – ${APP_NAME}` : `${title} – ${APP_NAME}`;
};

export function routeTitle(pathname: string, fallback = APP_NAME): string {
  for (const [pattern, title] of ROUTE_TITLES) if (matchPath(pattern, pathname)) return title;
  return fallback;
}

/** A more specific title once the page knows it (a food's or recipe's name). */
export function usePageTitle(title: string | null | undefined) {
  useEffect(() => {
    if (title) document.title = titleText(title);
  }, [title]);
}

/** Wait (up to ~3 s, while the page loads) for an element, then hand it over. */
function whenPresent(find: () => HTMLElement | null, then: (el: HTMLElement) => void): () => void {
  let cancelled = false;
  const started = performance.now();
  const tick = () => {
    if (cancelled) return;
    const el = find();
    if (el) then(el);
    else if (performance.now() - started < 3000) window.setTimeout(tick, 50);
  };
  tick();
  return () => {
    cancelled = true;
  };
}

/**
 * Single-page navigation is silent for screen readers. On every change of path: set the document title,
 * scroll to the top and move focus to the new page's <h1> (or the #hash target), so the new page is read.
 * Query-string changes (filters, periods) keep focus where it is. `navigate(to, { state: { keepFocus: true } })`
 * opts out (the advisor moving to a new conversation URL while you type).
 */
export function RouteFocus({ title: fixedTitle, focusOnMount = false }: { title?: string; focusOnMount?: boolean }) {
  const location = useLocation();
  const { pathname, hash } = location;
  const keepFocus = (location.state as { keepFocus?: boolean } | null)?.keepFocus === true;
  const first = useRef(true);

  useLayoutEffect(() => {
    document.title = titleText(fixedTitle ?? routeTitle(pathname));
  }, [pathname, fixedTitle]);

  useEffect(() => {
    const initial = first.current;
    first.current = false;
    if ((initial && !focusOnMount) || keepFocus) return;
    if (hash.length > 1) {
      const id = decodeURIComponent(hash.slice(1));
      return whenPresent(
        () => document.getElementById(id),
        (el) => {
          el.scrollIntoView({ block: "start" });
          focusElement(el, { preventScroll: true });
        },
      );
    }
    window.scrollTo(0, 0);
    return whenPresent(
      () => document.querySelector<HTMLElement>("main h1"),
      (h1) => {
        h1.setAttribute("data-route-focus", "");
        focusElement(h1, { preventScroll: true });
      },
    );
    // Only path changes move focus; `hash` is read for the target.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  return null;
}

/** "Skip to main content": the first focusable thing on every signed-in page. */
export function SkipLink({ target = "main" }: { target?: string }) {
  return (
    <a
      className="skip-link"
      href={`#${target}`}
      onClick={(e) => {
        e.preventDefault();
        const el = document.getElementById(target);
        el?.scrollIntoView({ block: "start" });
        focusElement(el, { preventScroll: true });
      }}
    >
      Skip to main content
    </a>
  );
}

// ---------------------------------------------------------------------------------------------
// Tabs (WAI-ARIA tab pattern, automatic activation)

export type TabItem<T extends string> = { value: T; label: ReactNode; ariaLabel?: string };

export const tabId = (base: string, value: string) => `${base}-tab-${value}`;
export const panelId = (base: string) => `${base}-panel`;

export function TabList<T extends string>({
  id,
  label,
  tabs,
  value,
  onChange,
  className = "",
}: {
  id: string;
  label: string;
  tabs: TabItem<T>[];
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const i = tabs.findIndex((t) => t.value === value);
    const n = tabs.length;
    const next =
      e.key === "ArrowRight" ? (i + 1) % n : e.key === "ArrowLeft" ? (i - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : null;
    if (next === null) return;
    e.preventDefault();
    onChange(tabs[next].value);
    document.getElementById(tabId(id, tabs[next].value))?.focus();
  }
  return (
    <div className={`tabs ${className}`} role="tablist" aria-label={label} onKeyDown={onKey}>
      {tabs.map((t) => {
        const selected = t.value === value;
        return (
          <button
            key={t.value}
            id={tabId(id, t.value)}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={panelId(id)}
            aria-label={t.ariaLabel}
            tabIndex={selected ? 0 : -1}
            className={selected ? "active" : ""}
            onClick={() => onChange(t.value)}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}

export function tabPanelProps(id: string, value: string) {
  return { role: "tabpanel", id: panelId(id), "aria-labelledby": tabId(id, value) } as const;
}

// ---------------------------------------------------------------------------------------------

/**
 * A horizontally/vertically scrolling wrapper for wide tables. When it actually scrolls it becomes a
 * focusable, named region so keyboard users can scroll it; otherwise it's a plain wrapper.
 */
export function ScrollRegion({ label, className = "table-wrap", id, children }: { label: string; className?: string; id?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [scrolls, setScrolls] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => setScrolls(el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={ref} id={id} className={className} {...(scrolls ? { tabIndex: 0, role: "region", "aria-label": label } : {})}>
      {children}
    </div>
  );
}
