// Review queue: absences held before payroll, and every exception the pipeline logged.
// Approving sends the absence through the same exactly-once payroll writer as the pipeline.
// Reviewed items stay in the list, marked, so the history is visible. Exceptions follow the payroll
// screen's pattern: a quiet table to scan, and a detail panel to read and act on one item.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, CircleAlert, CornerDownRight, FileText, Landmark, PhoneCall, Receipt, Users, type LucideIcon } from "lucide-react";
import { Fragment, useRef, useState } from "react";

import { api, type Row } from "../api";
import { RefLink } from "../components/Sources";
import { ErrorNote, Skeleton } from "../components/States";
import { codeText, formatDate, formatValue, label } from "../format";
import { revealOnNarrow } from "../reveal";

// Exceptions are grouped by the area before the colon in their source ("callout:reception_log"). Each
// area has a name, an icon and a line on what it is about, so the sections read as categories.
const AREAS: Record<string, { name: string; icon: LucideIcon; about: string }> = {
  employee: { name: "Employees", icon: Users, about: "matching people across HR, payroll and dispatch" },
  building: { name: "Buildings", icon: Building2, about: "linking each system's site names to the client buildings" },
  finance: { name: "Finance", icon: Landmark, about: "customers and entities in the finance reports" },
  personnel_action_forms: { name: "Personnel forms", icon: FileText, about: "transfers, hires and terminations on paper forms" },
  callout: { name: "Call-outs", icon: PhoneCall, about: "reading call-out messages and coding them for payroll" },
  billing: { name: "Billing", icon: Receipt, about: "coverage billed, or not, to cost-plus clients" },
};

function area(source: unknown): string {
  return String(source ?? "other").split(":")[0];
}

function areaName(key: string): string {
  return AREAS[key]?.name ?? label(key);
}

function AreaIcon({ area: key }: { area: string }) {
  const Icon = AREAS[key]?.icon ?? CircleAlert;
  return (
    <span className="group-icon">
      <Icon aria-hidden="true" />
    </span>
  );
}

function groups(items: Row[]): [string, Row[]][] {
  const out = new Map<string, Row[]>();
  for (const x of items) {
    const key = area(x.source);
    const list = out.get(key);
    if (list) list.push(x);
    else out.set(key, [x]);
  }
  return [...out.entries()];
}

// What a review decided, in words, with the tint of its status pill.
const OUTCOMES: Record<string, { text: string; tone: string }> = {
  acknowledge: { text: "Acknowledged", tone: "ok" },
  approve: { text: "Approved", tone: "ok" },
  dismiss: { text: "Dismissed", tone: "" },
};

function outcomeOf(review: Row | null, otherwise: { text: string; tone: string }): { text: string; tone: string } {
  if (!review) return otherwise;
  return OUTCOMES[String(review.action)] ?? { text: label(String(review.action)), tone: "" };
}

/** True once `value` differs from what it was when the card opened: a change made on this card,
 *  which earns the settle-in (an outcome already on record does not). */
function useChangedHere(value: string): boolean {
  const opened = useRef(value);
  return value !== opened.current;
}

type Filter = "open" | "reviewed" | "all";

// Source kinds as people say them; anything else is shown with underscores as spaces.
const SOURCES: Record<string, string> = {
  reception_log: "Reception log",
  area_manager_chat: "Managers' chat",
  personnel_action_forms: "Personnel form",
  hr_location: "HR location",
};

function sourceName(source: unknown): string {
  const kind = String(source ?? "").split(":").pop() ?? "";
  return SOURCES[kind] ?? label(kind);
}

/** A short name for the record: "Reception log row 31" instead of "31 (callout_log_….xlsx [Oct 2026] row 31)".
 *  It reads the "(file … row N)" form the pipeline writes into record_ref; any other form is shown whole. */
function recordName(x: Row): string {
  const ref = String(x.record_ref ?? "");
  const inner = ref.match(/\((.+)\)$/)?.[1];
  const where = inner?.match(/(row|line) \d+$/)?.[0];
  return where ? `${sourceName(x.source)} ${where}` : ref;
}

export function Review() {
  const queue = useQuery({ queryKey: ["review"], queryFn: api.review });
  const [filter, setFilter] = useState<Filter>("open");
  const [selectedId, setSelectedId] = useState<unknown>(null);

  if (queue.isError) return <ErrorNote error={queue.error} />;
  if (!queue.data) return <div className="glass tile"><Skeleton rows={8} /></div>;
  const all = queue.data.exceptions;
  const matches = (x: Row, f: Filter) => f === "all" || (f === "open" ? !x.review : Boolean(x.review));
  const exceptions = all.filter((x) => matches(x, filter));
  const selected = all.find((x) => x.id === selectedId) ?? null;
  const waiting = queue.data.absences.filter((a) => !a.review).length;

  return (
    <div className="review-grid">
      <section className="glass tile" aria-label="Held absences">
        <div className="tile-title">
          Absences held before payroll
          <span className="aside">
            <span className={`status ${waiting ? "warn" : "ok"}`}>{waiting} waiting</span>
          </span>
        </div>
        {queue.data.absences.length === 0 && <p className="empty">No absence is held. Every call-out was written to payroll.</p>}
        <div className="held-list">
          {queue.data.absences.map((a) => (
            <HeldAbsence key={String(a.id)} absence={a} />
          ))}
        </div>
      </section>

      <div className="split-grid">
        <section className="glass tile" aria-label="Exceptions">
          <div className="tile-title">
            Exceptions
            <span className="aside segmented small">
              {(["open", "reviewed", "all"] as Filter[]).map((f) => (
                <button key={f} className="btn" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                  {label(f)} {all.filter((x) => matches(x, f)).length}
                </button>
              ))}
            </span>
          </div>
          {exceptions.length === 0 && (
            <p className="empty">{filter === "open"
                ? "Nothing open. Every exception has been reviewed."
                : filter === "reviewed"
                  ? "Nothing reviewed yet."
                  : "The pipeline logged no exceptions for this run."}</p>
          )}
          {exceptions.length > 0 && (
            <div className="table-wrap tall-scroll">
              <table className="exceptions">
                <thead>
                  <tr>
                    <th>Record</th>
                    <th>Issue</th>
                    <th>{filter === "open" ? "" : "Status"}</th>
                  </tr>
                </thead>
                <tbody className="rows-in">
                  {groups(exceptions).map(([area, items]) => (
                    <Fragment key={area}>
                      <tr className="group-row">
                        <th colSpan={3}>
                          <span className="group-head">
                            <AreaIcon area={area} />
                            <span className="group-name">{areaName(area)}</span>
                            <span className="group-count">{items.length}</span>
                            {AREAS[area] && <span className="secondary group-about">{AREAS[area].about}</span>}
                          </span>
                        </th>
                      </tr>
                      {items.map((x) => {
                        const status = outcomeOf(x.review as Row | null, { text: "Open", tone: "info" });
                        const name = recordName(x);
                        const kind = sourceName(x.source);
                        return (
                          <tr
                            key={String(x.id)}
                            className="clickable"
                            aria-selected={selectedId === x.id}
                            onClick={() => {
                              setSelectedId(x.id);
                              revealOnNarrow(".review-grid .record");
                            }}
                          >
                            <td className="stack record-cell">
                              <span className="strong">{name}</span>
                              {/* The source kind, unless the name or the section already says it. */}
                              {!name.startsWith(kind) && kind !== areaName(area) && <span className="secondary">{kind}</span>}
                            </td>
                            <td className="stack">
                              <span className="clamp">{String(x.issue)}</span>
                              <span className="secondary clamp">{String(x.action_taken)}</span>
                            </td>
                            <td className="stack">
                              {/* In the Open list every row is open; the word only helps when lists are mixed. */}
                              {(Boolean(x.review) || filter !== "open") && (
                                <span>
                                  <span className={`status ${status.tone}`}>{status.text}</span>
                                </span>
                              )}
                              {x.confidence !== "high" && <span className="secondary text-warn">{String(x.confidence)} confidence</span>}
                            </td>
                          </tr>
                        );
                      })}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className={`glass tile record${selected ? "" : " idle"}`} aria-label="Exception detail">
          <div className="tile-title">Detail</div>
          {!selected && <p className="empty">Pick an exception to see what happened and to acknowledge or dismiss it.</p>}
          {selected && <ExceptionDetail key={String(selected.id)} item={selected} />}
        </section>
      </div>
    </div>
  );
}

/** The detail of one exception, read top to bottom: what is wrong, what the pipeline did about it,
 *  how sure it was and where the record came from, then the review (or its outcome). */
function ExceptionDetail({ item: x }: { item: Row }) {
  const client = useQueryClient();
  const [note, setNote] = useState("");
  const act = useMutation({
    mutationFn: (action: "acknowledge" | "dismiss") => api.reviewException(String(x.item_key), action, note),
    onSuccess: () => client.invalidateQueries({ queryKey: ["review"] }),
  });
  const review = x.review as Row | null;
  const outcome = outcomeOf(review, { text: "Open", tone: "info" });
  const changed = useChangedHere(outcome.text);
  return (
    <div className="exception-detail">
      <header className="xd-head">
        <AreaIcon area={area(x.source)} />
        <div className="xd-title">
          <span className="name">{recordName(x)}</span>
          <span className="secondary">
            {areaName(area(x.source))} · {sourceName(x.source)}
          </span>
        </div>
        <span key={outcome.text} className={`status ${outcome.tone}${changed ? " pop-in" : ""}`}>
          {outcome.text}
        </span>
      </header>

      <section className="xd-block" aria-label="Issue">
        <div className="xd-label">Issue</div>
        <p className="xd-issue">{String(x.issue)}</p>
      </section>

      <section className="xd-block xd-action" aria-label="What the pipeline did">
        <CornerDownRight aria-hidden="true" />
        <div>
          <div className="xd-label">What the pipeline did</div>
          <p>{String(x.action_taken)}</p>
        </div>
      </section>

      <dl className="xd-meta">
        <div>
          <dt>Confidence</dt>
          <dd>{formatValue("confidence", x.confidence)}</dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>
            <RefLink value={x.record_ref} />
          </dd>
        </div>
      </dl>

      <section className="xd-review" aria-label="Review">
        <div className="xd-label">Your review</div>
        {review ? (
          <p className={`xd-outcome${changed ? " swap-in" : ""}`}>
            <span className="strong">{outcome.text}</span>
            {review.at ? <span className="secondary"> on {formatDate(String(review.at))}</span> : null}
            {review.note ? <span className="xd-note">“{String(review.note)}”</span> : null}
          </p>
        ) : (
          <DecisionForm
            choices={[["acknowledge", "Acknowledge"], ["dismiss", "Dismiss"]]}
            placeholder="Note (optional): why you acknowledge or dismiss it"
            rows={2}
            buttons="xd-buttons"
            note={note}
            onNote={setNote}
            pending={act.isPending ? act.variables : undefined}
            onChoose={(action) => act.mutate(action)}
          />
        )}
        {act.isError && <p className="error" role="alert">{(act.error as Error).message}</p>}
      </section>
    </div>
  );
}

/** One held absence, read left to right: who and when, why it was held, the code it would get and
 *  the evidence; then, set apart on the right, the decision (or its outcome in payroll). */
function HeldAbsence({ absence: a }: { absence: Row }) {
  const client = useQueryClient();
  const [note, setNote] = useState("");
  const act = useMutation({
    mutationFn: (action: "approve" | "dismiss") => api.reviewAbsence(Number(a.id), action, note),
    onSuccess: () => client.invalidateQueries(),
  });
  const review = a.review as Row | null;
  const done = Boolean(review) || a.decision !== "held_for_review";
  const decided = outcomeOf(review, done ? { text: formatValue("decision", a.decision), tone: "" } : { text: "Waiting", tone: "warn" });
  const changed = useChangedHere(decided.text);

  return (
    <article className={`held${done ? " done" : " waiting"}`}>
      <div className="held-main">
        <header className="held-head">
          <span className="name">{String(a.name_as_written ?? "Unknown")}</span>
          <span key={decided.text} className={`status ${decided.tone}${changed ? " pop-in" : ""}`}>
            {decided.text}
          </span>
          <span className="secondary held-when">
            {a.employee_id ? String(a.employee_id) : "not matched"} · {formatDate(a.absence_date as string, true)} · {formatValue("shift", a.shift)} shift ·{" "}
            {String(a.building ?? "")}
          </span>
        </header>

        {a.hold_reason ? (
          <section aria-label="Held because">
            <div className="xd-label">Held because</div>
            <p className="held-reason">{String(a.hold_reason)}</p>
          </section>
        ) : null}

        <section aria-label="Code">
          <div className="xd-label">Code</div>
          <p>
            <span className="strong">{codeText(a.code)}</span>
            {a.code_reason ? <span className="secondary"> · {String(a.code_reason)}</span> : null}
          </p>
        </section>

        <dl className="held-facts">
          <div>
            <dt>Reported</dt>
            <dd>
              {formatValue("contact_at", a.contact_at)}
              {a.contact_basis ? <span className="secondary">{String(a.contact_basis)}</span> : null}
            </dd>
          </div>
          <div>
            <dt>Confidence</dt>
            <dd>
              {formatValue("confidence", a.confidence)}
              {a.evidence ? <span className="secondary">{String(a.evidence)}</span> : null}
            </dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>
              <RefLink value={a.record_ref} />
            </dd>
          </div>
        </dl>
      </div>

      <section className="held-decision" aria-label="Decision">
        <div className="xd-label">{done ? "Decision" : "Your decision"}</div>
        {done ? (
          <div className={`held-outcome${changed ? " swap-in" : ""}`}>
            <p>
              <span className="strong">{decided.text}</span>
              {review?.at ? <span className="secondary"> on {formatDate(String(review.at))}</span> : null}
            </p>
            {a.submission_id ? (
              <p>
                <span className="secondary">Payroll </span>
                {String(a.submission_id)} · <span className="strong">{formatValue("final_status", a.final_status ?? "sent")}</span>
              </p>
            ) : review?.result ? (
              <p className="secondary">{String(review.result)}</p>
            ) : null}
            {review?.note ? <p className="xd-note">“{String(review.note)}”</p> : null}
          </div>
        ) : (
          <DecisionForm
            choices={[["approve", "Approve and write to payroll"], ["dismiss", "Keep out of payroll"]]}
            placeholder="Note (optional): why you approve or keep it out"
            rows={3}
            buttons="held-buttons"
            note={note}
            onNote={setNote}
            pending={act.isPending ? act.variables : undefined}
            onChoose={(action) => act.mutate(action)}
          />
        )}
        {act.isError && <p className="error" role="alert">{(act.error as Error).message}</p>}
      </section>
    </article>
  );
}

/** The note and the decision buttons of a review card. The first choice is the primary action; the
 *  button whose request is in flight carries the busy sweep, and all wait until it returns. */
function DecisionForm<A extends string>({
  choices,
  placeholder,
  rows,
  buttons,
  note,
  onNote,
  pending,
  onChoose,
}: {
  choices: [A, string][];
  placeholder: string;
  rows: number;
  buttons: string;
  note: string;
  onNote: (note: string) => void;
  pending: A | undefined;
  onChoose: (action: A) => void;
}) {
  return (
    <>
      <textarea
        className="xd-input"
        rows={rows}
        aria-label="Note for this decision"
        placeholder={placeholder}
        value={note}
        onChange={(e) => onNote(e.target.value)}
      />
      <div className={buttons}>
        {choices.map(([action, text], i) => (
          <button
            key={action}
            className={`btn${i === 0 ? " primary" : ""}${pending === action ? " busy" : ""}`}
            disabled={pending !== undefined}
            onClick={() => onChoose(action)}
          >
            {text}
          </button>
        ))}
      </div>
    </>
  );
}
