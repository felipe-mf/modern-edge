// Ask the data: a side panel that answers only from Northgate's tables and lists the records it used.

import { useMutation } from "@tanstack/react-query";
import { ArrowUp, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import { RefLink } from "./Sources";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: string[];
}

const EXAMPLES = [
  "Who covered for Besnik Rexhepi this month?",
  "Which building had the most call-outs in October?",
  "Why is the gross margin at Meridian One lower than at Halcyon Tower?",
];

export function ChatPanel({ onClose }: { onClose: () => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const ask = useMutation({
    mutationFn: (history: Message[]) => api.chat(history.map(({ role, content }) => ({ role, content }))),
    onSuccess: (answer) => setMessages((m) => [...m, { role: "assistant", content: answer.answer, sources: answer.sources }]),
  });

  // Braces matter: scrollIntoView returns a Promise in recent Chrome, and an effect may only return a cleanup function.
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages, ask.isPending]);

  const send = (text: string) => {
    if (!text.trim() || ask.isPending) return;
    const history: Message[] = [...messages, { role: "user", content: text.trim() }];
    setMessages(history);
    setDraft("");
    ask.mutate(history);
  };

  return (
    <aside className="sheet glass chat" aria-label="Ask the data">
      <header>
        <h2>Ask the data</h2>
        <button className="btn icon" onClick={onClose} aria-label="Close chat">
          <X />
        </button>
      </header>
      <div className="body">
        {messages.length === 0 && (
          <div className="chat-intro">
            <p className="secondary">
              Answers come only from Northgate's records and list the sources they used. When the data cannot answer, it says so.
            </p>
            {EXAMPLES.map((e) => (
              <button key={e} className="btn example" onClick={() => send(e)}>
                {e}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            <div className="text">{m.content}</div>
            {m.sources && m.sources.length > 0 && (
              <div className="msg-sources">
                <span className="secondary">Sources</span>
                {m.sources.map((s) => (
                  <RefLink key={s} value={s} />
                ))}
              </div>
            )}
          </div>
        ))}
        {ask.isPending && <div className="msg assistant secondary">Looking through the records…</div>}
        {ask.isError && (
          <p className="error" role="alert">
            {(ask.error as Error).message}. Try again, or rephrase the question.
          </p>
        )}
        <div ref={end} />
      </div>
      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <textarea
          aria-label="Question"
          placeholder="Ask about buildings, call-outs, payroll, billing…"
          rows={2}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(draft);
            }
          }}
        />
        <button className="btn primary icon" type="submit" disabled={!draft.trim() || ask.isPending} aria-label="Send">
          <ArrowUp />
        </button>
      </form>
    </aside>
  );
}
