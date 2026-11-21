// Building view: one building, date and shift. Who is assigned, who punched in and out, who is out
// and why, and who is covering, with every row opening its source record.

import { useQueries, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type Assigned, type Board, type MonthDay, type Person, type RunInfo } from "../api";
import { MonthChart, TonightChart } from "../components/ShiftCharts";
import { RefLink } from "../components/Sources";
import { ErrorNote, Skeleton } from "../components/States";
import { codeText, formatDate, formatTime, formatValue, label } from "../format";
import { go } from "../route";

type Shift = "day" | "night";

function weekdays(start: string, end: string): string[] {
  const out: string[] = [];
  for (let d = new Date(`${start}T12:00:00`); d <= new Date(`${end}T12:00:00`); d.setDate(d.getDate() + 1)) {
    if (d.getDay() !== 0 && d.getDay() !== 6) out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

export function BuildingView({ run, params }: { run: RunInfo; params: string[] }) {
  const days = weekdays(run.period_start, run.period_end);
  const building = params[0] && run.buildings.includes(params[0]) ? params[0] : [...run.buildings].sort()[0];
  const day = params[1] && days.includes(params[1]) ? params[1] : days[0];
  const shift: Shift = params[2] === "day" ? "day" : "night";
  const open = (b: string, d: string, s: Shift) => go("buildings", b, d, s);

  const board = useQuery({ queryKey: ["board", building, day, shift], queryFn: () => api.board(building, day, shift) });
  const month = useQuery({ queryKey: ["month", building, shift], queryFn: () => api.month(building, shift) });
  const others = useQueries({
    queries: [...run.buildings].sort().map((b) => ({
      queryKey: ["board", b, day, shift],
      queryFn: () => api.board(b, day, shift),
    })),
  });

  const index = days.indexOf(day);
  const step = (delta: number) => {
    const next = days[index + delta];
    if (next) open(building, next, shift);
  };

  // Left and right arrows step through the month from anywhere on the page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "ArrowLeft") step(-1);
      if (e.key === "ArrowRight") step(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <>
      <section className="buildingbar glass" aria-label="Building, date and shift">
        <h1>{building}</h1>
        <div className="pills" role="list">
          {[...run.buildings].sort().map((b, i) => {
            const s = others[i]?.data?.summary;
            const contracted = others[i]?.data?.contracted;
            return (
              <button key={b} role="listitem" className="btn" aria-pressed={b === building} onClick={() => open(b, day, shift)}>
                {b}
                {s && contracted !== undefined && (
                  <span className={s.on_site < contracted ? "strong" : undefined}>
                    {s.on_site}/{contracted}
                  </span>
                )}
              </button>
            );
          })}
        </div>
        <div className="datestep">
          <button className="btn icon" onClick={() => step(-1)} disabled={index <= 0} aria-label="Previous weekday">
            <ChevronLeft />
          </button>
          <span className="date">{formatDate(day, true)}</span>
          <button className="btn icon" onClick={() => step(1)} disabled={index >= days.length - 1} aria-label="Next weekday">
            <ChevronRight />
          </button>
        </div>
        <div className="segmented">
          {(["day", "night"] as Shift[]).map((s) => (
            <button key={s} className="btn" aria-pressed={s === shift} onClick={() => open(building, day, s)}>
              {s === "day" ? "Day" : "Night"}
            </button>
          ))}
        </div>
      </section>

      {board.isError && <ErrorNote error={board.error} />}
      {board.isPending && <div className="glass tile"><Skeleton rows={8} /></div>}
      {board.data && (
        <Shift
          key={`${building}-${day}-${shift}`}
          board={board.data}
          month={month.data ? <MonthChart days={month.data} selected={day} onPick={(d) => open(building, d, shift)} /> : <Skeleton rows={4} />}
          monthNote={month.data && <MonthNote days={month.data} />}
        />
      )}
    </>
  );
}

type Selected = { kind: "assigned"; row: Assigned } | { kind: "person"; row: Person; note: string };

function Shift({ board, month, monthNote }: { board: Board; month: React.ReactNode; monthNote: React.ReactNode }) {
  const firstOut = board.assigned.find((a) => a.status === "out") ?? board.assigned[0];
  const [selected, setSelected] = useState<Selected | null>(firstOut ? { kind: "assigned", row: firstOut } : null);
  const s = board.summary;
  const outs = board.assigned.filter((a) => a.status === "out");
  const openPostings = board.covering.filter((c) => c.status.toUpperCase() !== "FILLED");

  if (!board.scheduled_day) {
    return <p className="glass tile empty">No shift is scheduled on weekends. Pick a weekday.</p>;
  }

  return (
    <div className="bv-grid">
      <section className="glass tile hero" aria-label="Staffing">
        <div className="tile-title">
          On site / contracted
          <span className="aside">{board.shift === "day" ? "Day shift 07:00–15:00" : "Night shift 16:00–24:00"}</span>
        </div>
        <div className="hero-row">
          <div className="big">
            {s.on_site}
            <span>/{board.contracted}</span>
          </div>
          <dl className="counts">
            <div><dt>Assigned</dt><dd>{s.assigned}</dd></div>
            <div><dt>Out</dt><dd className={s.out ? "strong" : undefined}>{s.out}</dd></div>
            <div><dt>Covered</dt><dd>{s.covered}</dd></div>
            <div><dt>Open</dt><dd className={s.open ? "strong" : undefined}>{s.open}</dd></div>
            <div><dt>Unexpected</dt><dd className={board.unexpected.length ? "strong" : undefined}>{board.unexpected.length}</dd></div>
          </dl>
        </div>
      </section>

      <section className="glass tile out-tile" aria-label="Out and covering">
        <div className="tile-title">
          Out and covering<span className="aside">{outs.length ? `${outs.length} out` : "nobody out"}</span>
        </div>
        {outs.length === 0 && openPostings.length === 0 && board.unexpected.length === 0 && (
          <p className="empty">Everyone assigned to this shift is on site.</p>
        )}
        <ul className="pairs">
          {outs.map((a) => {
            const cover = board.covering.find((c) => c.posting_id === a.posting_id);
            return (
              <li key={a.employee_id}>
                <button className="pair" onClick={() => setSelected({ kind: "assigned", row: a })}>
                  <span className="strong">{a.name}</span>
                  <span className="secondary">{a.code ? codeText(a.code) : label(a.reason ?? "out")}</span>
                </button>
                <span className="arrow">{cover?.covering ? (cover.fill_type === "OT" ? "covered on overtime by" : "covered by") : "not covered"}</span>
                {cover?.covering ? (
                  <button className="pair" onClick={() => setSelected({ kind: "person", row: cover.covering!, note: `Covering ${cover.posting_id}` })}>
                    <span className="strong">{cover.covering.name}</span>
                    <span className="secondary">
                      {cover.posting_id} · in {formatTime(cover.covering.clock_in)}
                    </span>
                  </button>
                ) : (
                  <span className="secondary">{cover ? `${cover.posting_id} ${cover.status.toLowerCase()}` : "no posting in dispatch"}</span>
                )}
              </li>
            );
          })}
          {board.unexpected.map((u) => (
            <li key={u.employee_id}>
              <button className="pair" onClick={() => setSelected({ kind: "person", row: u, note: "Clocked in here without an assignment or posting" })}>
                <span className="strong">{u.name}</span>
                <span className="secondary">clocked in {formatTime(u.clock_in)}, not assigned here</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <RecordTile selected={selected} />

      <section className="glass tile tonight-tile" aria-label="Tonight on site">
        <div className="tile-title">
          {board.shift === "night" ? "Tonight" : "Today"} on site
          <span className="aside">only exceptions are marked</span>
        </div>
        <TonightChart board={board} />
      </section>

      <section className="glass tile month-tile" aria-label="Month">
        <div className="tile-title">
          {new Date(`${board.date}T12:00:00`).toLocaleDateString("en-US", { month: "long", year: "numeric" })} · on site each weekday
          <span className="aside">click a day</span>
        </div>
        {month}
        {monthNote}
      </section>

      <section className="glass tile roster" aria-label="Roster">
        <div className="tile-title">
          Roster<span className="aside">{board.assigned.length} assigned · {board.covering.length} postings</span>
        </div>
        <div className="table-wrap roster-scroll">
          <table>
            <thead>
              <tr>
                <th>Employee</th><th>ID</th><th>Class</th><th>In</th><th>Out</th><th>Status</th><th>Basis</th><th>Source</th>
              </tr>
            </thead>
            <tbody>
              {board.assigned.map((a) => (
                <tr
                  key={a.employee_id}
                  className="clickable"
                  aria-selected={selected?.row.employee_id === a.employee_id}
                  onClick={() => setSelected({ kind: "assigned", row: a })}
                >
                  <td className="strong">{a.name}</td>
                  <td>{a.employee_id}</td>
                  <td>{a.job_class ?? "—"}</td>
                  <td>{formatTime(a.clock_in)}</td>
                  <td>{formatTime(a.clock_out)}</td>
                  <td><AssignedStatus row={a} /></td>
                  <td className="secondary">{a.assignment_basis?.split(" (")[0] ?? "—"}</td>
                  <td><RefLink value={a.callout_ref ?? a.source_ref} /></td>
                </tr>
              ))}
              {board.covering.map((c) => (
                <tr
                  key={c.posting_id}
                  className={c.covering ? "clickable" : undefined}
                  aria-selected={c.covering ? selected?.row.employee_id === c.covering.employee_id : undefined}
                  onClick={() => c.covering && setSelected({ kind: "person", row: c.covering, note: `Covering ${c.posting_id}` })}
                >
                  <td className="strong">{c.covering?.name ?? "Unfilled"}</td>
                  <td>{c.covering?.employee_id ?? "—"}</td>
                  <td>{c.covering?.job_class ?? "—"}</td>
                  <td>{formatTime(c.covering?.clock_in)}</td>
                  <td>{formatTime(c.covering?.clock_out)}</td>
                  <td>
                    <span className={c.status.toUpperCase() === "FILLED" ? "status" : "status alert"}>
                      {c.status.toUpperCase() === "FILLED" ? `Covering${c.fill_type === "OT" ? " · OT" : ""}` : label(c.status.toLowerCase())}
                    </span>
                  </td>
                  <td className="secondary">for {c.absent_as_posted ?? "—"}</td>
                  <td><RefLink value={c.source_ref} text={c.posting_id} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function MonthNote({ days }: { days: MonthDay[] }) {
  const short = days.filter((d) => d.on_site < d.contracted);
  const outs = days.reduce((sum, d) => sum + d.out, 0);
  const covered = days.reduce((sum, d) => sum + d.covered, 0);
  return (
    <p className="secondary month-note">
      {outs} people out over {days.length} shifts, {covered} covered.{" "}
      {short.length === 0
        ? "Every shift reached its contracted posts."
        : `Short-staffed: ${short.map((d) => `${formatDate(d.date).slice(0, 6)} (${d.on_site}/${d.contracted})`).join(", ")}.`}
    </p>
  );
}

function AssignedStatus({ row }: { row: Assigned }) {
  if (row.status === "on_site") return <span className="status">On site</span>;
  if (row.status === "no_punch") return <span className="status alert">No punch</span>;
  const held = row.decision === "held_for_review";
  return (
    <span className={held ? "status solid" : "status alert"}>
      Out{row.code ? ` · ${row.code}` : row.reason ? ` · ${row.reason}` : ""}
      {held ? " · held" : ""}
    </span>
  );
}

const EVENT_FIELDS = ["reason", "contact_at", "contact_basis", "notice_hours", "code", "code_reason", "decision", "hold_reason", "submission_id", "final_status", "confidence", "evidence"];

function RecordTile({ selected }: { selected: Selected | null }) {
  const ref = selected?.kind === "assigned" && selected.row.status === "out" ? selected.row.callout_ref : undefined;
  const found = useQuery({ queryKey: ["records", ref], queryFn: () => api.records(ref!), enabled: Boolean(ref) });
  const event = found.data?.find((r) => r.table === "callout_events")?.record;
  const message = found.data?.find((r) => r.table === "callout_log" || r.table === "chat_messages")?.record;

  return (
    <section className="glass tile record" aria-label="Record">
      <div className="tile-title">Record</div>
      {!selected && <p className="empty">Pick a person in the roster to see their record and sources.</p>}
      {selected && (
        <>
          <div className="record-head">
            <span className="name">{selected.row.name}</span>
            <span className="secondary">
              {selected.row.employee_id} · {selected.row.job_class ?? "no class"} · {selected.row.employment_type ?? ""}
            </span>
          </div>
          {selected.kind === "person" && <p className="secondary record-note">{selected.note}</p>}

          {ref && found.isPending && <Skeleton rows={6} />}
          {ref && found.isError && <ErrorNote error={found.error} />}
          {event && (
            <dl className="facts">
              {EVENT_FIELDS.filter((f) => event[f] !== null && event[f] !== undefined && event[f] !== "").map((f) => (
                <Fact key={f} name={f === "contact_at" ? "reported" : f} value={f === "code" ? codeText(event[f]) : f === "reason" ? label(String(event[f])) : formatValue(f, event[f])} />
              ))}
            </dl>
          )}
          {message && (
            <blockquote>
              {String(message.message ?? message.text ?? "")}
              <span className="secondary"> · {String(message.caller ?? message.author ?? "")}</span>
            </blockquote>
          )}

          {!ref && (
            <dl className="facts">
              <Fact name="Clock in" value={formatTime(selected.row.clock_in)} />
              <Fact name="Clock out" value={formatTime(selected.row.clock_out)} />
              {selected.kind === "assigned" && (
                <Fact name="Assigned by" value={selected.row.assignment_basis ?? "—"} />
              )}
            </dl>
          )}

          <div className="sources">
            <div className="secondary">Sources</div>
            {ref && <RefLink value={ref} />}
            {selected.kind === "assigned" && selected.row.posting_id && <RefLink value={`dispatch posting ${selected.row.posting_id}`} />}
            <RefLink value={selected.row.source_ref} />
            {selected.row.punch_refs.map((p) => (
              <RefLink key={p} value={p} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function Fact({ name, value }: { name: string; value: string }) {
  return (
    <>
      <dt>{label(name)}</dt>
      <dd>{value}</dd>
    </>
  );
}
