import { useEffect, useState } from "react";
import { activeProfile, switchProfile, takeProfileNotice } from "../profile";
import { useAnnounceWhen } from "./a11y";
import { useSharedProfiles } from "./Sharing";

// Read once per page load (a switch reloads the page); not in a state initialiser, which may run twice.
const switchNotice = takeProfileNotice();

/**
 * Top of every page while using someone else's profile: whose it is, what you may do, and the way back.
 * Also shows the notice left by the last switch (e.g. that the profile was unshared).
 */
export function ProfileBanner() {
  const using = activeProfile();
  const [notice, setNotice] = useState(switchNotice);
  const shared = useSharedProfiles();
  const entry = using ? shared.data?.shared_with_me.find((p) => p.user_id === using.id) : undefined;
  useAnnounceWhen(notice);

  // Unshared since it was picked (the server says so too, on the next request that uses it).
  const gone = Boolean(using && shared.data && !entry);
  useEffect(() => {
    if (gone && using) switchProfile(null, `${using.name}'s profile isn't shared with you any more, so you're back on your own.`);
  }, [gone, using]);

  if (!using && !notice) return null;
  return (
    <div className="stack-sm profile-banners">
      {notice && (
        <div className="alert alert-info row wrap profile-notice">
          <span className="grow">{notice}</span>
          <button type="button" className="btn btn-sm" onClick={() => setNotice(null)}>
            Dismiss
          </button>
        </div>
      )}
      {using && (
        <section className="alert alert-info profile-banner" aria-label="Profile in use">
          <p>
            <strong>You're using {using.name}'s profile</strong>
            {entry && <> · {entry.can_edit ? "you can change anything in it" : "view only"}</>}.
          </p>
          <p className="small">
            Everything you see here is {using.name}'s
            {entry?.can_edit ? "; whatever you log or plan is recorded as added by you" : ""}.{" "}
            <button type="button" className="btn-link" onClick={() => switchProfile(null)}>
              Switch back to your own profile
            </button>
          </p>
        </section>
      )}
    </div>
  );
}
