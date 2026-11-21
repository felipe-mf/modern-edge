// Review queue: absences held before payroll, and every exception the pipeline logged.
// Approving sends the absence through the same exactly-once payroll writer as the pipeline.
// Reviewed items stay in the list, marked, so the history is visible.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Row } from "../api";
import { RefLink } from "../components/Sources";
import { ErrorNote, Skeleton } from "../components/States";
import { codeText, formatDate, formatValue, label } from "../format";

export function Review() {
  const queue = useQuery({ queryKey: ["review"], queryFn: api.review });
  const [filter, setFilter] = useState<"open" | "all">("open");

  if (queue.isError) return <ErrorNote error={queue.error} />;
  if (!queue.data) return <div className="glass tile"><Skeleton rows={8} /></div>;
  const exceptions = queue.data.exceptions.filter((x) => filter === "all" || !x.review);

  return (
    <div className="review-grid">
      <section className="glass tile" aria-label="Held absences">
        <div className="tile-title">
          Absences held before payroll<span className="aside">{queue.data.absences.filter((a) => !a.review).length} waiting</span>
        </div>
        {queue.data.absences.length === 0 && <p className="empty">No absence is held. Every call-out was written to payroll.</p>}
        <div className="held-list">
          {queue.data.absences.map((a) => (
            <HeldAbsence key={String(a.id)} absence={a} />
          ))}
        </div>
      </section>

      <section className="glass tile" aria-label="Exceptions">
        <div className="tile-title">
          Exceptions
          <span className="aside">
            <span className="segmented small">
              <button className="btn" aria-pressed={filter === "open"} onClick={() => setFilter("open")}>Open</button>
              <button className="btn" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All {queue.data.exceptions.length}</button>
            </span>
          </span>
        </div>
        {exceptions.length === 0 && <p className="empty">Nothing open. Switch to All to see acknowledged and dismissed items.</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Source</th><th>Record</th><th>Issue</th><th>Action taken</th><th>Confidence</th><th>Review</th>
              </tr>
            </thead>
            <tbody>
              {exceptions.map((x) => (
                <ExceptionRow key={String(x.id)} item={x} />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function HeldAbsence({ absence: a }: { absence: Row }) {
  const client = useQueryClient();
  const [note, setNote] = useState("");
  const act = useMutation({
    mutationFn: (action: "approve" | "dismiss") => api.reviewAbsence(Number(a.id), action, note),
    onSuccess: () => client.invalidateQueries(),
  });
  const review = a.review as Row | null;
  const done = Boolean(review) || a.decision !== "held_for_review";

  return (
    <article className={`held${done ? " done" : ""}`}>
      <div className="held-head">
        <span className="strong">{String(a.name_as_written ?? "Unknown")}</span>
        <span className="secondary">
          {a.employee_id ? String(a.employee_id) : "not matched"} · {formatDate(a.absence_date as string, true)} · {String(a.shift ?? "")} · {String(a.building ?? "")}
        </span>
        {done && (
          <span className="status solid">{review ? `${label(String(review.action))}d` : label(String(a.decision))}</span>
        )}
      </div>
      <dl className="facts">
        <dt>Held because</dt>
        <dd className="strong">{String(a.hold_reason ?? "—")}</dd>
        <dt>Code</dt>
        <dd>{codeText(a.code)}{a.code_reason ? ` · ${a.code_reason}` : ""}</dd>
        <dt>Reported</dt>
        <dd>{formatValue("contact_at", a.contact_at)} · {String(a.contact_basis ?? "")}</dd>
        <dt>Confidence</dt>
        <dd>{String(a.confidence ?? "—")} · {String(a.evidence ?? "")}</dd>
        {review && (
          <>
            <dt>Result</dt>
            <dd>{String(review.result ?? "")}{review.note ? ` · “${review.note}”` : ""}</dd>
          </>
        )}
        <dt>Source</dt>
        <dd><RefLink value={a.record_ref} /></dd>
      </dl>
      {!done && (
        <div className="held-actions">
          <input
            aria-label="Note for this decision"
            placeholder="Note (optional): why you approve or dismiss"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button className="btn primary" disabled={act.isPending} onClick={() => act.mutate("approve")}>
            {act.isPending ? "Writing…" : "Approve and write to payroll"}
          </button>
          <button className="btn" disabled={act.isPending} onClick={() => act.mutate("dismiss")}>
            Keep out of payroll
          </button>
        </div>
      )}
      {act.isError && <p className="error" role="alert">{(act.error as Error).message}</p>}
    </article>
  );
}

function ExceptionRow({ item: x }: { item: Row }) {
  const client = useQueryClient();
  const act = useMutation({
    mutationFn: (action: "acknowledge" | "dismiss") => api.reviewException(String(x.item_key), action, ""),
    onSuccess: () => client.invalidateQueries({ queryKey: ["review"] }),
  });
  const review = x.review as Row | null;
  return (
    <tr>
      <td className="secondary">{String(x.source)}</td>
      <td className="wrap"><RefLink value={x.record_ref} /></td>
      <td className={`wrap${review ? " struck" : ""}`}>{String(x.issue)}</td>
      <td className="wrap">{String(x.action_taken)}</td>
      <td><span className={x.confidence === "low" ? "status alert" : "status"}>{String(x.confidence)}</span></td>
      <td>
        {review ? (
          <span className="status solid">{label(String(review.action))}d</span>
        ) : (
          <span className="row-actions">
            <button className="btn" disabled={act.isPending} onClick={() => act.mutate("acknowledge")}>Acknowledge</button>
            <button className="btn" disabled={act.isPending} onClick={() => act.mutate("dismiss")}>Dismiss</button>
          </span>
        )}
      </td>
    </tr>
  );
}
