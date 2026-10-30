import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Loading } from "../components/common";
import { RichText } from "../components/RichText";
import { useAppInfo } from "../lib";
import type { ChatMessage } from "../types";

const QUICK_PROMPTS = [
  "Review today's intake and tell me what to adjust.",
  "Check my supplements against the upper limits.",
  "Suggest meals for the rest of today to hit my protein target.",
  "How has my fiber and micronutrient intake looked over the past two weeks?",
];

const TOOL_LABELS: Record<string, string> = {
  get_profile_and_targets: "profile & targets",
  get_day_summary: "day summary",
  get_daily_totals: "daily totals",
  get_log_entries: "log entries",
  search_foods: "food search",
  get_food_details: "food details",
  list_recipes: "recipes",
};

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
      {m.role === "assistant" ? <RichText text={m.text || "(no text)"} /> : <p className="pre">{m.text}</p>}
      {tools.length > 0 && (
        <div className="row wrap small">
          <span className="muted">Looked at:</span>
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
    <div className="alert alert-info stack-sm" role="status">
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
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const conversations = useQuery({ queryKey: ["conversations"], queryFn: api.conversations });
  const convo = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.conversation(conversationId!),
    enabled: !!conversationId,
  });

  const send = useMutation({
    mutationFn: (message: string) => api.chat(message, conversationId),
    onMutate: (message) => setPending(message),
    onSuccess: (detail) => {
      setText("");
      qc.setQueryData(["conversation", detail.id], detail);
      qc.invalidateQueries({ queryKey: ["conversations"] });
      if (detail.id !== conversationId) navigate(`/advisor/${detail.id}`);
    },
    onSettled: () => setPending(null),
  });
  const remove = useMutation({
    mutationFn: (cid: number) => api.deleteConversation(cid),
    onSuccess: (_, cid) => {
      qc.invalidateQueries({ queryKey: ["conversations"] });
      if (cid === conversationId) navigate("/advisor");
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

  return (
    <div className="advisor">
      <aside className="convo-list card">
        <div className="row between">
          <h2>Conversations</h2>
          <Link to="/advisor" className="btn">
            New
          </Link>
        </div>
        <ErrorBox error={conversations.error} />
        <ul className="plain-list">
          {conversations.data?.map((c) => (
            <li key={c.id} className={`convo ${c.id === conversationId ? "active" : ""}`}>
              <Link to={`/advisor/${c.id}`}>
                <span className="convo-title">{c.title}</span>
                <span className="muted small">{new Date(c.updated_at).toLocaleDateString()}</span>
              </Link>
              <button type="button" className="btn-link danger small" onClick={() => remove.mutate(c.id)} aria-label={`Delete ${c.title}`}>
                ×
              </button>
            </li>
          ))}
          {conversations.data?.length === 0 && <li className="muted small">No conversations yet.</li>}
        </ul>
      </aside>

      <section className="chat card">
        <p className="disclaimer small">
          The advisor reads your logged data to give general nutrition guidance. It is not medical advice — check with your doctor, pharmacist or a
          registered dietitian about medical conditions, medications or supplement interactions.
        </p>
        {unavailable && <SetupNotice />}
        <div className="thread" aria-live="polite">
          {conversationId && convo.isLoading && <Loading />}
          <ErrorBox error={convo.error} />
          {messages.length === 0 && !pending && !unavailable && (
            <div className="stack">
              <p className="muted">Ask about your intake, targets, supplements or meal ideas. Some starting points:</p>
              <div className="quick">
                {QUICK_PROMPTS.map((p) => (
                  <button key={p} type="button" className="btn" disabled={send.isPending} onClick={() => send.mutate(p)}>
                    {p}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <Bubble key={i} m={m} />
          ))}
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
        {friendly ? <div className="alert alert-warn">{friendly}</div> : <ErrorBox error={send.error} />}
        {messages.length > 0 && !unavailable && (
          <div className="quick small">
            {QUICK_PROMPTS.slice(0, 3).map((p) => (
              <button key={p} type="button" className="btn btn-sm" disabled={send.isPending} onClick={() => send.mutate(p)}>
                {p}
              </button>
            ))}
          </div>
        )}
        {!unavailable && (
          <form className="composer" onSubmit={submit}>
            <textarea
              rows={2}
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
            <button type="submit" className="btn btn-primary" disabled={send.isPending || !text.trim()}>
              {send.isPending ? "…" : "Send"}
            </button>
          </form>
        )}
      </section>
    </div>
  );
}
