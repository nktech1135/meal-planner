import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Loading } from "../components/common";
import { RichText } from "../components/RichText";
import { fmtDay, fmtNum, mealLabel, unitText, useAppInfo } from "../lib";
import type { ChatMessage, ChatSource, ConversationDetail, Proposal } from "../types";
import { Button, rescueFocus, useAnnounce, useAnnounceText, VisuallyHidden } from "../components/a11y";

const QUICK_PROMPTS = [
  "Review my last 7 days",
  "Plan tomorrow's meals to hit my targets",
  "Is my supplement stack safe? Check upper limits and interactions",
  "Review today's intake and tell me what to adjust.",
  "Check my supplements against the upper limits.",
  "Suggest meals for the rest of today to hit my protein target.",
  "How has my fiber and micronutrient intake looked over the past two weeks?",
];

const TOOL_LABELS: Record<string, string> = {
  get_profile_and_targets: "read your profile & targets",
  get_day_summary: "checked a day's summary",
  get_daily_totals: "looked at daily totals",
  get_log_entries: "read log entries",
  search_foods: "searched foods",
  get_food_details: "looked up food details",
  list_recipes: "looked at recipes",
  get_trends: "looked at trends",
  get_body_measurements: "checked body measurements",
  get_exercise: "looked at exercise",
  get_meal_plan: "read your meal plan",
  propose_plan_items: "proposed plan items",
  check_supplement: "checked a supplement against your intake",
  search_pubmed: "searched PubMed",
  web_search: "searched trusted sources",
  web_fetch: "read a source page",
};

function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function Sources({ sources }: { sources: ChatSource[] }) {
  if (!sources.length) return null;
  return (
    <div className="sources small">
      <h4 className="h-xs">Sources</h4>
      <ol>
        {sources.map((s) => (
          <li key={s.url}>
            <a href={s.url} target="_blank" rel="noopener noreferrer">
              {s.title || hostname(s.url)}
              <VisuallyHidden> (opens in a new tab)</VisuallyHidden>
            </a>{" "}
            <span className="muted">
              ({hostname(s.url)}) <span aria-hidden="true">↗</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Plain text of a reply for the screen-reader announcement (markdown marks dropped, long replies cut). */
function spokenReply(text: string): string {
  const plain = text
    .replace(/^\s*\|?\s*:?-{2,}.*$/gm, "")
    .replace(/[#*`|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return plain.length > 600 ? `${plain.slice(0, 600).replace(/\s+\S*$/, "")}… The full reply is in the conversation.` : plain;
}

function ProposalCard({ p, conversationId }: { p: Proposal; conversationId: number }) {
  const qc = useQueryClient();
  const heading = useRef<HTMLHeadingElement>(null);
  const announce = useAnnounce();
  const statusRef = useAnnounceText<HTMLParagraphElement>();
  const [chosen, setChosen] = useState<boolean[]>(() => p.items.map(() => true));
  const update = (next: Proposal) => {
    qc.setQueryData<ConversationDetail>(["conversation", conversationId], (old) =>
      old ? { ...old, proposals: old.proposals.map((x) => (x.id === next.id ? next : x)) } : old,
    );
  };
  const [added, setAdded] = useState<number | null>(null);
  const accept = useMutation({
    mutationFn: () => {
      const indexes = chosen.flatMap((c, i) => (c ? [i] : []));
      return api.acceptProposal(p.id, indexes.length === p.items.length ? null : indexes);
    },
    onSuccess: (next) => {
      setAdded(chosen.filter(Boolean).length);
      update(next);
      rescueFocus(() => heading.current);
      qc.invalidateQueries({ queryKey: ["plan"] });
      qc.invalidateQueries({ queryKey: ["shopping"] });
    },
  });
  const dismiss = useMutation({
    mutationFn: () => api.dismissProposal(p.id),
    onSuccess: (next) => {
      update(next);
      announce("Proposal dismissed.");
      rescueFocus(() => heading.current);
    },
  });
  const count = chosen.filter(Boolean).length;
  const firstDate = [...p.items].map((i) => i.date).sort()[0];
  const planLink = firstDate ? `/plan?date=${firstDate}` : "/plan";

  return (
    <section className={`proposal card stack-sm proposal-${p.status}`} aria-label="Meal plan proposal">
      <div className="row between wrap">
        <h3 className="h-card" ref={heading}>
          Proposed for your meal plan
        </h3>
        {p.status === "accepted" && (
          <span className="chip chip-ok">
            <span aria-hidden="true">✓ </span>Accepted
          </span>
        )}
        {p.status === "dismissed" && <span className="chip chip-off">Dismissed</span>}
      </div>
      {p.rationale && <p className="small">{p.rationale}</p>}
      {p.status === "pending" ? (
        <fieldset className="proposal-items" disabled={accept.isPending || dismiss.isPending}>
          <legend className="sr-only">Items to add</legend>
          {p.items.map((it, i) => (
            <label key={i} className="checkbox proposal-item">
              <input type="checkbox" checked={chosen[i]} onChange={(e) => setChosen(chosen.map((c, j) => (j === i ? e.target.checked : c)))} />
              <span className="min-0">
                <strong>{it.label}</strong>{" "}
                <span className="muted">
                  {fmtNum(it.quantity)} {unitText(it.unit)} · {mealLabel(it.meal)}, {fmtDay(it.date)}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      ) : (
        <ul className="plain-list small proposal-items">
          {p.items.map((it, i) => (
            <li key={i}>
              {p.status === "accepted" && p.accepted_indexes && (
                <>
                  <span aria-hidden="true">{p.accepted_indexes.includes(i) ? "✓ " : "– "}</span>
                  <VisuallyHidden>{p.accepted_indexes.includes(i) ? "Added: " : "Not added: "}</VisuallyHidden>
                </>
              )}
              {it.label}{" "}
              <span className="muted">
                {fmtNum(it.quantity)} {unitText(it.unit)} · {mealLabel(it.meal)}, {fmtDay(it.date)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {p.status === "pending" && (
        <div className="row wrap">
          <Button type="button" className="btn btn-primary btn-sm" disabled={!count || accept.isPending} onClick={() => accept.mutate()}>
            {accept.isPending ? "Adding…" : `Add ${count === p.items.length ? "all" : count} to plan`}
          </Button>
          <Button type="button" className="btn btn-sm" disabled={dismiss.isPending} onClick={() => dismiss.mutate()}>
            Dismiss
          </Button>
        </div>
      )}
      {p.status === "accepted" && (
        <p className="small" ref={statusRef}>
          {added !== null && <>Added {added} item{added === 1 ? "" : "s"} to your meal plan. </>}
          <Link to={planLink}>View plan →</Link>
        </p>
      )}
      <ErrorBox error={accept.error || dismiss.error} />
    </section>
  );
}

function friendlyError(err: unknown): string | null {
  if (!err) return null;
  if (err instanceof ApiError) {
    if (err.status === 429) return `${err.message}. Please wait a bit before sending another message.`;
    if (err.status === 503) return `The advisor is unavailable: ${err.message}`;
  }
  return null;
}

function Bubble({ m }: { m: ChatMessage }) {
  const tools = Array.from(new Set(m.tools_used));
  return (
    <div className={`bubble bubble-${m.role}`}>
      {/* A heading per message lets screen-reader users jump message to message. */}
      <h3 className="sr-only">{m.role === "assistant" ? "Advisor" : "You"}</h3>
      {m.role === "assistant" ? <RichText text={m.text || "(no text)"} headingLevel={4} /> : <p className="pre">{m.text}</p>}
      {m.role === "assistant" && <Sources sources={m.sources ?? []} />}
      {tools.length > 0 && (
        <div className="row wrap small">
          <span className="muted">The advisor</span>
          {tools.map((t) => (
            <span key={t} className="chip">
              {TOOL_LABELS[t] ?? t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function SetupNotice() {
  const { user } = useAuth();
  return (
    <div className="alert alert-info stack-sm">
      <strong>The advisor isn't set up yet.</strong>
      <span>
        It needs an Anthropic API key.{" "}
        {user?.is_admin ? (
          <>
            <Link to="/settings">Add one in Settings</Link> and it will be ready straight away.
          </>
        ) : (
          "Ask an admin to add one in Settings."
        )}
      </span>
      <span className="small">Your log, targets and the rest of the app work without it.</span>
    </div>
  );
}

export default function AdvisorPage() {
  const info = useAppInfo();
  const { id } = useParams();
  const conversationId = id ? Number(id) : null;
  const navigate = useNavigate();
  const qc = useQueryClient();
  // ?ask=… (from the supplement check): fill in a question for the user to review. Never sent automatically.
  const [params] = useSearchParams();
  const ask = conversationId ? null : params.get("ask")?.trim().slice(0, 8000) || null;
  const [text, setText] = useState(ask ?? "");
  useEffect(() => {
    if (ask) setText(ask);
  }, [ask]);
  const [pending, setPending] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const announce = useAnnounce();

  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.conversations });
  const convo = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.conversation(conversationId!),
    enabled: !!conversationId,
  });

  const send = useMutation({
    mutationFn: (message: string) => api.chat(message, conversationId),
    onMutate: (message) => {
      setPending(message);
      announce("Sent. The advisor is looking at your data and thinking…");
    },
    onSuccess: (detail) => {
      setText("");
      qc.setQueryData(["conversation", detail.id], detail);
      qc.invalidateQueries({ queryKey: ["conversations"] });
      const reply = [...detail.messages].reverse().find((m) => m.role === "assistant");
      const proposals = detail.proposals.filter((p) => p.status === "pending").length;
      if (reply) {
        announce(
          `The advisor replied: ${spokenReply(reply.text)}${proposals ? ` It proposed ${proposals === 1 ? "a meal plan change" : `${proposals} meal plan changes`}; they follow the reply.` : ""}`,
        );
      }
      // The URL gains the conversation id; stay in the composer rather than jumping to the page heading.
      if (detail.id !== conversationId) navigate(`/advisor/${detail.id}`, { state: { keepFocus: true } });
      rescueFocus(() => composer.current);
    },
    onSettled: () => setPending(null),
  });
  const remove = useMutation({
    mutationFn: (cid: number) => api.deleteConversation(cid),
    onSuccess: (_, cid) => {
      qc.invalidateQueries({ queryKey: ["conversations"] });
      const title = conversations.data?.find((c) => c.id === cid)?.title;
      announce(`Deleted the conversation${title ? ` “${title}”` : ""}.`);
      if (cid === conversationId) navigate("/advisor");
      else rescueFocus(() => document.getElementById("conversations-title"));
    },
  });

  const messages = conversationId ? (convo.data?.messages ?? []) : [];
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pending]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const msg = text.trim();
    if (msg && !send.isPending) send.mutate(msg);
  }

  const friendly = friendlyError(send.error);
  const unavailable = info?.advisor_configured === false;
  const current = conversations.data?.find((c) => c.id === conversationId);

  return (
    <div className="advisor">
      <h1 className="sr-only">Advisor</h1>
      <aside className="convo-list card" aria-labelledby="conversations-title">
        <div className="row between wrap">
          <h2 id="conversations-title">Conversations</h2>
          <Link to="/advisor" className="btn">
            New<VisuallyHidden> conversation</VisuallyHidden>
          </Link>
        </div>
        <ErrorBox error={conversations.error} />
        <ul className="plain-list">
          {conversations.data?.map((c) => (
            <li key={c.id} className={`convo ${c.id === conversationId ? "active" : ""}`}>
              <Link to={`/advisor/${c.id}`} aria-current={c.id === conversationId ? "page" : undefined}>
                <span className="convo-title">{c.title}</span>
                <span className="muted small">{new Date(c.updated_at).toLocaleDateString()}</span>
              </Link>
              <button type="button" className="btn-link danger small convo-delete" onClick={() => confirm(`Delete the conversation "${c.title}"? This can't be undone.`) && remove.mutate(c.id)}>
                <span aria-hidden="true">×</span>
                <VisuallyHidden>Delete conversation: {c.title}</VisuallyHidden>
              </button>
            </li>
          ))}
          {conversations.data?.length === 0 && <li className="muted small">No conversations yet.</li>}
        </ul>
      </aside>

      <section className="chat card" aria-labelledby="chat-title">
        <h2 id="chat-title" className="sr-only">
          {current?.title ?? "New conversation"}
        </h2>
        <p className="disclaimer small">
          The advisor reads your logged data to give general nutrition guidance. It is not medical advice — check with your doctor, pharmacist or a
          registered dietitian about medical conditions, medications or supplement interactions.
        </p>
        {unavailable && <SetupNotice />}
        {/* Not a live region: replies are announced once, as they arrive (see `send`). */}
        <div className="thread">
          {conversationId && convo.isLoading && <Loading />}
          <ErrorBox error={convo.error} />
          {messages.length === 0 && !pending && !unavailable && (
            <div className="stack">
              <p className="muted">Ask about your intake, targets, supplements or meal ideas. Some starting points:</p>
              <div className="quick">
                {QUICK_PROMPTS.map((p) => (
                  <Button
                    key={p}
                    type="button"
                    className="btn"
                    disabled={send.isPending}
                    onClick={() => {
                      send.mutate(p);
                    }}
                  >
                    {p}
                  </Button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <Bubble key={i} m={m} />
          ))}
          {conversationId &&
            convo.data?.proposals.map((p) => <ProposalCard key={p.id} p={p} conversationId={conversationId} />)}
          {pending && (
            <>
              <div className="bubble bubble-user">
                <p className="pre">{pending}</p>
              </div>
              <div className="bubble bubble-assistant muted">Looking at your data and thinking…</div>
            </>
          )}
          <div ref={endRef} />
        </div>
        {friendly ? (
          <div className="alert alert-warn" role="alert">
            {friendly}
          </div>
        ) : (
          <ErrorBox error={send.error} />
        )}
        {messages.length > 0 && !unavailable && (
          <div className="quick small">
            {QUICK_PROMPTS.slice(0, 3).map((p) => (
              <Button key={p} type="button" className="btn btn-sm" disabled={send.isPending} onClick={() => send.mutate(p)}>
                {p}
              </Button>
            ))}
          </div>
        )}
        {!unavailable && ask && text === ask && (
          <p id="composer-prefill" className="small muted composer-note">
            A question is filled in below. Edit it if you like; nothing is sent until you press Send.
          </p>
        )}
        {!unavailable && (
          <form className="composer" onSubmit={submit}>
            <textarea
              aria-describedby={ask && text === ask ? "composer-prefill" : undefined}
              ref={composer}
              rows={ask && text === ask ? 4 : 2}
              maxLength={8000}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Ask the advisor…"
              aria-label="Message"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(e);
                }
              }}
            />
            <Button type="submit" className="btn btn-primary" disabled={send.isPending || !text.trim()}>
              {send.isPending ? "Sending…" : "Send"}
            </Button>
          </form>
        )}
      </section>
    </div>
  );
}
