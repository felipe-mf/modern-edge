// Building view: one building, date and shift. First whether the posts are filled, then the people
// on the shift (exceptions first), then the month. Every row opens its source record.

import { keepPreviousData, useQueries, useQuery } from "@tanstack/react-query";
import { ArrowRight, ChevronLeft, ChevronRight } from "lucide-react";
import { useContext, useEffect, useState } from "react";

import { api, type Assigned, type Board, type MonthDay, type Person, type RunInfo } from "../api";
import { DatePicker } from "../components/DatePicker";
import { isFilled, type Line, lowestDay, MonthChart, shiftLines } from "../components/ShiftCharts";
import { Fact, RefLink, SourceContext } from "../components/Sources";
import { ErrorNote, Skeleton } from "../components/States";
import { codeText, formatDate, formatTime, label } from "../format";
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

  // While the next day loads, the current one stays on screen (dimmed) instead of collapsing to a skeleton.
  const board = useQuery({
    queryKey: ["board", building, day, shift],
    queryFn: () => api.board(building, day, shift),
    placeholderData: keepPreviousData,
  });
  const month = useQuery({ queryKey: ["month", building, shift], queryFn: () => api.month(building, shift), placeholderData: keepPreviousData });
  const others = useQueries({
    queries: [...run.buildings].sort().map((b) => ({
      queryKey: ["board", b, day, shift],
      queryFn: () => api.board(b, day, shift),
      placeholderData: keepPreviousData,
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
        <div className="datestep">
          <button className="btn icon" onClick={() => step(-1)} disabled={index <= 0} aria-label="Previous weekday">
            <ChevronLeft />
          </button>
          <DatePicker
            value={day}
            days={days}
            // Another building's month (still loading) must not mark this one's days.
            short={new Set(month.isPlaceholderData ? [] : (month.data ?? []).filter((d) => d.on_site < d.contracted).map((d) => d.date))}
            onPick={(d) => open(building, d, shift)}
          />
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
        <div className="pills" role="list">
          {[...run.buildings].sort().map((b, i) => {
            const s = others[i]?.data?.summary;
            const contracted = others[i]?.data?.contracted;
            return (
              <button key={b} role="listitem" className="btn" aria-pressed={b === building} onClick={() => open(b, day, shift)}>
                {b}
                {s && contracted !== undefined && (
                  // Dimmed while it still shows the previous day's count.
                  <span className={`${s.on_site < contracted ? "strong text-bad" : ""}${others[i].isPlaceholderData ? " stale" : ""}`}>
                    {s.on_site}/{contracted}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </section>

      {board.isError && <ErrorNote error={board.error} />}
      {board.isPending && <div className="glass tile"><Skeleton rows={8} /></div>}
      {board.data && (
        <Shift
          // Same building and shift: the board (and its chart) stays mounted while the day changes, so the
          // day marker can glide to the new day. A new building or shift is a new board and enters fresh.
          key={`${board.data.building}-${board.data.shift}`}
          board={board.data}
          stale={board.isPlaceholderData}
          monthStale={month.isPlaceholderData}
          month={
            month.data ? (
              <MonthChart days={month.data} selected={day} onPick={(d) => open(building, d, shift)} />
            ) : (
              <Skeleton rows={4} />
            )
          }
          monthNote={month.data && <MonthNote days={month.data} shift={shift} />}
        />
      )}
    </>
  );
}

type Selected = { kind: "assigned"; row: Assigned } | { kind: "person"; row: Person; note: string };

function pickLine(line: Line): Selected | null {
  if (line.assigned) return { kind: "assigned", row: line.assigned };
  if (line.person) return { kind: "person", row: line.person, note: line.note ?? "" };
  return null;
}

function Shift({
  board,
  stale,
  monthStale,
  month,
  monthNote,
}: {
  board: Board;
  stale: boolean;
  monthStale: boolean;
  month: React.ReactNode;
  monthNote: React.ReactNode;
}) {
  const openSource = useContext(SourceContext);
  const lines = shiftLines(board);
  const first = lines.map(pickLine).find(Boolean) ?? null;
  // A pick belongs to one day: on a new day the record shows that day's first exception again.
  const [pick, setPick] = useState<{ date: string; line: Selected | null } | null>(null);
  const selected = pick?.date === board.date ? pick.line : first;
  const setSelected = (line: Selected | null) => setPick({ date: board.date, line });
  const s = board.summary;
  const outs = board.assigned.filter((a) => a.status === "out");
  const exceptions = lines.filter((l) => l.note).length;

  if (!board.scheduled_day) {
    return <p className="glass tile empty">No shift is scheduled on weekends. Pick a weekday.</p>;
  }

  const short = board.contracted - s.on_site;
  const verdict = short > 0 ? `${short} ${short === 1 ? "post" : "posts"} short` : short < 0 ? `${-short} above contract` : "Fully staffed";
  const facts = [
    `${s.assigned} assigned`,
    s.out ? `${s.out} out` : null,
    s.covered ? `${s.covered} covered` : null,
    s.open ? `${s.open} open` : null,
    board.unexpected.length ? `${board.unexpected.length} not assigned here` : null,
  ].filter(Boolean);

  return (
    <div className={`bv-grid${stale ? " stale" : ""}`} aria-busy={stale}>
      <section className="glass tile hero" aria-label="Staffing">
        <div className="tile-title">On site / contracted</div>
        <div className="hero-row swap-in" key={board.date}>
          <div className="big">
            {s.on_site}
            <span>/{board.contracted}</span>
          </div>
          <div className="verdict">
            <span className={short > 0 ? "headline alert" : "headline ok"}>{verdict}</span>
            <span className="secondary">{facts.join(" · ")}</span>
          </div>
          {outs.length > 0 && (
            <ul className="pairs">
              {outs.map((a) => {
                const cover = board.covering.find((c) => c.posting_id === a.posting_id);
                const filled = cover && isFilled(cover);
                return (
                  <li key={a.employee_id}>
                    <button className="pair" onClick={() => setSelected({ kind: "assigned", row: a })}>
                      <span className="strong">{a.name}</span>
                      <span className="secondary">{a.code ? codeText(a.code) : label(a.reason ?? "out")}</span>
                    </button>
                    <ArrowRight className="arrow" aria-label={filled ? "covered by" : "not covered"} />
                    {filled && cover.covering ? (
                      <button className="pair" onClick={() => setSelected({ kind: "person", row: cover.covering!, note: `Covering ${cover.posting_id}` })}>
                        <span className="strong">{cover.covering.name}</span>
                        <span className="secondary">{cover.fill_type === "OT" ? "on overtime" : "covering"} · in {formatTime(cover.covering.clock_in)}</span>
                      </button>
                    ) : cover ? (
                      // No person to show: the pair opens the dispatch posting itself.
                      <button className={`pair${filled ? "" : " uncovered"}`} onClick={() => openSource(cover.source_ref)}>
                        <span className="strong">{filled ? "Covered" : "Not covered"}</span>
                        <span className="secondary">
                          {filled ? `worker not found in HR · ${cover.posting_id}` : `${cover.posting_id} ${cover.status.toLowerCase()}`}
                        </span>
                      </button>
                    ) : (
                      <span className="pair uncovered">
                        <span className="strong">Not covered</span>
                        <span className="secondary">no posting in dispatch</span>
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </section>

      <section className="glass tile people" aria-label="People on this shift">
        <div className="tile-title">
          {board.shift === "night" ? "Night shift 16:00–24:00" : "Day shift 07:00–15:00"}
          <span className="aside">
            {lines.length} people · {exceptions ? `${exceptions} ${exceptions === 1 ? "exception" : "exceptions"} first` : "nothing unusual"}
          </span>
        </div>
        <div className="table-wrap people-scroll">
          <table className="people-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Hours</th>
                <th>Exception</th>
              </tr>
            </thead>
            <tbody className="rows-in" key={board.date}>
              {lines.map((l, i) => {
                const line = pickLine(l);
                const id = l.assigned?.employee_id ?? l.person?.employee_id;
                return (
                  <tr
                    key={l.key}
                    style={{ "--i": i } as React.CSSProperties}
                    className={`${line || l.ref ? "clickable" : ""}${l.tone ? ` exception tone-${l.tone}` : ""}`}
                    aria-selected={line ? selected?.row.employee_id === id : undefined}
                    // A person opens in the Record tile; a posting with no person opens its dispatch record.
                    onClick={() => (line ? setSelected(line) : l.ref && openSource(l.ref))}
                  >
                    <td>
                      <span className="who">{l.name}</span>
                      {l.jobClass && <span className="role">{l.jobClass}</span>}
                    </td>
                    <td className="hours">{l.start ? `${formatTime(l.start)}–${formatTime(l.end)}` : "—"}</td>
                    <td className="note">{l.note && <span className="note-text">{l.note}</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <RecordTile selected={selected} />

      <section className={`glass tile month-tile${monthStale ? " stale" : ""}`} aria-label="Month" aria-busy={monthStale}>
        <div className="tile-title">
          {new Date(`${board.date}T12:00:00`).toLocaleDateString("en-US", { month: "long" })}, on site each {board.shift === "night" ? "night" : "day"}
          <span className="aside">click a day to open it</span>
        </div>
        {month}
        {monthNote}
      </section>
    </div>
  );
}

function MonthNote({ days, shift }: { days: MonthDay[]; shift: Shift }) {
  const short = days.filter((d) => d.on_site < d.contracted);
  const outs = days.reduce((sum, d) => sum + d.out, 0);
  const covered = days.reduce((sum, d) => sum + d.covered, 0);
  const lowest = lowestDay(days);
  const unit = shift === "night" ? "nights" : "days";
  return (
    <p className="month-note">
      {short.length === 0 ? (
        <span className="strong">Contracted posts met on all {days.length} {unit}.</span>
      ) : (
        <span className="strong">
          Short on {short.length} of {days.length} {unit}, lowest {lowest.on_site}/{lowest.contracted} on {formatDate(lowest.date).slice(0, 6)}.
        </span>
      )}{" "}
      <span className="secondary">
        {outs} out, {covered} covered.
      </span>
    </p>
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
      {!selected && <p className="empty">Pick a person to see their record and sources.</p>}
      {selected && (
        <div className="swap-in" key={`${selected.kind}-${selected.row.employee_id}`}>
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
                <Fact key={f} name={f} value={event[f]} />
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
        </div>
      )}
    </section>
  );
}
