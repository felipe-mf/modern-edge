// Charts for the building view.
// MonthChart: people on site each weekday (ink line over a light green wash) against the contracted
//   posts (dashed ink); the shortfall is filled with the deeper green and
//   only the selected and the lowest day carry a label. Click a day to open it.
//   Motion: when a building's month opens, the line draws from the 1st to the last day and the
//   shortfall settles in under it; picking another day glides the day marker there.
// shiftLines: one line per person on the shift (and per open post), with a note only for exceptions
//   (out, overtime, late, missing punch, open post).

import { useLayoutEffect, useRef, useState } from "react";

import type { Assigned, Board, Coverage, MonthDay, Person } from "../api";
import { codeText, formatDate, formatTime } from "../format";

// The same values as the CSS tokens --ink, --muted and --green-300.
const INK = "#16171a";
const MUTED = "#696b73";
const GREEN = "#cdeccf";

/** A dispatch posting that someone took. Dispatch's word decides, as in the board's "covered" count;
 *  `covering` can still be null when the worker could not be matched to an HR employee. */
export function isFilled(c: Coverage): boolean {
  return c.status.toUpperCase() === "FILLED";
}

/** The day with the fewest people on site. */
export function lowestDay(days: MonthDay[]): MonthDay {
  return days.reduce((low, d) => (d.on_site < low.on_site ? d : low), days[0]);
}

export function MonthChart({ days, selected, onPick }: { days: MonthDay[]; selected: string; onPick: (day: string) => void }) {
  // Draw at the tile's real width so the labels keep their type size instead of being scaled down.
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  // Measured before the first paint, so the chart never draws once at a guessed width.
  useLayoutEffect(() => {
    if (!box.current) return;
    setWidth(Math.max(200, Math.round(box.current.getBoundingClientRect().width)));
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(200, Math.round(entry.contentRect.width))));
    observer.observe(box.current);
    return () => observer.disconnect();
  }, []);
  const narrow = width < 560;
  const height = 180;
  const left = 24;
  const right = narrow ? 24 : 92;
  const top = 28;
  const bottom = 32;
  const contracted = days[0]?.contracted ?? 0;
  const max = Math.max(contracted, ...days.map((d) => d.on_site)) + 1;
  const min = Math.max(0, Math.min(contracted, ...days.map((d) => d.on_site)) - 1);
  const x = (i: number) => left + (i * (width - left - right)) / Math.max(1, days.length - 1);
  const y = (v: number) => top + (1 - (v - min) / (max - min)) * (height - top - bottom);
  const line = days.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.on_site).toFixed(1)}`).join(" ");
  // Shortfall: the area between the contracted line and the on-site line, where on site is below it.
  const gap =
    days.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(Math.min(d.on_site, contracted)).toFixed(1)}`).join(" ") +
    ` L${x(days.length - 1).toFixed(1)},${y(contracted).toFixed(1)} L${x(0).toFixed(1)},${y(contracted).toFixed(1)} Z`;
  const lowest = lowestDay(days);
  const isMonday = (date: string) => new Date(`${date}T12:00:00`).getDay() === 1;
  const selectedIndex = days.findIndex((d) => d.date === selected);
  // Date labels on Mondays and the first day, skipping any that would touch the selected day's label.
  const dateLabel = (i: number) =>
    i === selectedIndex || ((i === 0 || isMonday(days[i].date)) && Math.abs(i - selectedIndex) > (narrow ? 3 : 2));

  return (
    <div ref={box}>
    <svg className="month-chart" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label="People on site each weekday against contracted posts">
      <defs>
        <linearGradient id="onsite-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={GREEN} stopOpacity="0.3" />
          <stop offset="1" stopColor={GREEN} stopOpacity="0" />
        </linearGradient>
      </defs>
      {Array.from({ length: max - min + 1 }, (_, i) => min + i).map((v) => (
        <g key={v}>
          <line x1={left} x2={width - right} y1={y(v)} y2={y(v)} stroke="rgba(22,23,26,0.06)" />
          <text x={left - 8} y={y(v) + 4} fontSize="11" textAnchor="end" fill={MUTED}>
            {v}
          </text>
        </g>
      ))}
      <path className="mc-fill" d={line + ` L${x(days.length - 1).toFixed(1)},${height - bottom} L${x(0).toFixed(1)},${height - bottom} Z`} fill="url(#onsite-fill)" />
      <path className="mc-fill" d={gap} fill={GREEN} />
      <line x1={left} x2={width - right} y1={y(contracted)} y2={y(contracted)} stroke={INK} strokeDasharray="4 4" />
      {!narrow && (
        <text x={width - right + 8} y={y(contracted) + 4} fontSize="11" fill={INK}>
          {contracted} contracted
        </text>
      )}
      <path className="mc-line" d={line} pathLength={1} fill="none" stroke={INK} strokeWidth="1.75" strokeLinejoin="round" />
      {days.map((d, i) => {
        const isSelected = d.date === selected;
        const short = d.on_site < d.contracted;
        const showLow = d === lowest && short && !isSelected;
        return (
          <g
            key={d.date}
            role="button"
            tabIndex={0}
            aria-label={`${formatDate(d.date)}: ${d.on_site} of ${d.contracted} on site, ${d.out} out, ${d.covered} covered`}
            onClick={() => onPick(d.date)}
            // A click picks the day without focusing it, so no focus ring flashes round the column.
            onMouseDown={(e) => e.preventDefault()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onPick(d.date)}
            style={{ cursor: "pointer" }}
          >
            <title>{`${formatDate(d.date)} · ${d.on_site}/${d.contracted} on site · ${d.out} out · ${d.covered} covered`}</title>
            <rect x={x(i) - 14} y={0} width={28} height={height} fill="transparent" />
            {showLow && (
              <text className="mc-mark" x={x(i)} y={y(d.on_site) + 18} fontSize="11" textAnchor="middle" fill={INK} fontWeight={600}>
                low {d.on_site}/{d.contracted}
              </text>
            )}
            {short && !isSelected && <circle className="mc-mark" cx={x(i)} cy={y(d.on_site)} r={3} fill={INK} />}
            {dateLabel(i) && (
              <text x={x(i)} y={height - 6} fontSize="11" textAnchor="middle" fill={isSelected ? INK : MUTED} fontWeight={isSelected ? 600 : 400}>
                {narrow ? Number(d.date.slice(8, 10)) : formatDate(d.date).slice(0, 6)}
              </text>
            )}
          </g>
        );
      })}
      {/* The day marker is drawn once, outside the days, so it can glide from the old day to the new one. */}
      {selectedIndex >= 0 && (
        <g className="mc-cursor" style={{ transform: `translateX(${x(selectedIndex)}px)` }} pointerEvents="none" aria-hidden="true">
          <line x1={0} x2={0} y1={top - 4} y2={height - bottom} stroke={INK} strokeDasharray="2 3" />
          <text x={selectedIndex === 0 ? -4 : 0} y={top - 10} fontSize="13" textAnchor={selectedIndex === 0 ? "start" : "middle"} fill={INK} fontWeight={600}>
            {days[selectedIndex].on_site}/{days[selectedIndex].contracted}
          </text>
          <circle className="mc-cursor-dot" r={5} fill="#fff" stroke={INK} strokeWidth={2} style={{ transform: `translateY(${y(days[selectedIndex].on_site)}px)` }} />
        </g>
      )}
    </svg>
    </div>
  );
}

type Tone = "warn" | "bad" | "info";

export interface Line {
  key: string;
  name: string;
  jobClass: string | null;
  start: string | null;
  end: string | null;
  note: string | null; // set only for exceptions
  tone: Tone | null; // how the exception reads: bad (out, uncovered), warn (punch problems), info (covering)
  assigned?: Assigned; // the assigned employee behind the line
  person?: Person; // a covering or unexpected person behind the line
  ref?: string; // the dispatch posting's source record, opened when there is no person to show
}

const SLACK_MINUTES = 10;

/** One line per person on the shift (and per open post), exceptions first. */
export function shiftLines(board: Board): Line[] {
  const start = new Date(board.shift_start).getTime();
  const end = start + 8 * 3600_000;
  const late = (t: string | null) => t !== null && new Date(t).getTime() > start + SLACK_MINUTES * 60_000;
  const early = (t: string | null) => t !== null && new Date(t).getTime() < end - SLACK_MINUTES * 60_000;

  const assigned = board.assigned.map((a): Line => {
    let note: string | null = null;
    if (a.status === "out") note = a.code ? `Out · ${codeText(a.code)}` : `Out · ${a.reason ?? "reason not recorded"}`;
    else if (!a.clock_in) note = "No clock-in";
    else if (!a.clock_out) note = "No clock-out";
    else if (late(a.clock_in)) note = `Late in ${formatTime(a.clock_in)}`;
    else if (early(a.clock_out)) note = `Left early ${formatTime(a.clock_out)}`;
    const out = a.status === "out";
    const tone: Tone | null = out ? "bad" : note ? "warn" : null;
    return { key: a.employee_id, name: a.name, jobClass: a.job_class, start: out ? null : a.clock_in, end: out ? null : a.clock_out, note, tone, assigned: a };
  });
  const covering = board.covering.map((c): Line => {
    const forWhom = c.absent_as_posted ?? "the absent employee";
    const role = c.fill_type === "OT" ? "Overtime" : "Covering";
    const base = { key: c.posting_id, jobClass: null, start: null, end: null, ref: c.source_ref };
    if (!isFilled(c)) return { ...base, name: "Open post", note: `Not covered · ${c.posting_id} ${c.status.toLowerCase()}`, tone: "bad" };
    if (!c.covering) return { ...base, name: "Unidentified worker", note: `${role} for ${forWhom} · not found in HR`, tone: "warn" };
    const p = c.covering;
    return { ...base, name: p.name, jobClass: p.job_class, start: p.clock_in, end: p.clock_out, note: `${role} for ${forWhom}`, tone: "info", person: p };
  });
  const unexpected = board.unexpected.map((u): Line => ({
    key: `u-${u.employee_id}`,
    name: u.name,
    jobClass: u.job_class,
    start: u.clock_in,
    end: u.clock_out,
    note: "Not assigned or posted here",
    tone: "warn",
    person: u,
  }));
  const lines = [...assigned, ...covering, ...unexpected];
  return [...lines.filter((l) => l.note), ...lines.filter((l) => !l.note)];
}
