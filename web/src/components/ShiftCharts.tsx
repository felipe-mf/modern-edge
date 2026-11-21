// Two small charts for the building view, drawn in ink only.
// MonthChart: people on site each weekday against the contracted posts; click a day to open it.
// TonightChart: one line per person on the shift; only exceptions (out, overtime, late, missing punch) stand out.

import type { Assigned, Board, Coverage, MonthDay } from "../api";
import { codeText, formatTime } from "../format";

export function MonthChart({ days, selected, onPick }: { days: MonthDay[]; selected: string; onPick: (day: string) => void }) {
  const width = 640;
  const height = 210;
  const left = 26;
  const right = 10;
  const top = 22;
  const bottom = 30;
  // Zoom the y axis to the range that moves, so one missing person is visible.
  const max = Math.max(1, ...days.map((d) => Math.max(d.contracted, d.on_site))) + 1;
  const min = Math.max(0, Math.min(...days.map((d) => d.on_site)) - 2);
  const x = (i: number) => left + (i * (width - left - right)) / Math.max(1, days.length - 1);
  const y = (v: number) => top + (1 - (v - min) / (max - min)) * (height - top - bottom);
  const line = days.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.on_site).toFixed(1)}`).join(" ");
  const contracted = days[0]?.contracted ?? 0;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" role="img" aria-label="People on site each weekday against contracted posts">
      {Array.from({ length: max - min + 1 }, (_, i) => min + i).map((v) => (
        <g key={v}>
          <line x1={left} x2={width - right} y1={y(v)} y2={y(v)} stroke="rgba(22,23,26,0.08)" />
          <text x={left - 8} y={y(v) + 4} fontSize="10" textAnchor="end" fill="#696b73">
            {v}
          </text>
        </g>
      ))}
      <line x1={left} x2={width - right} y1={y(contracted)} y2={y(contracted)} stroke="#16171a" strokeDasharray="4 4" strokeWidth="1" />
      <path d={line} fill="none" stroke="#16171a" strokeWidth="1.75" strokeLinejoin="round" />
      {days.map((d, i) => {
        const isSelected = d.date === selected;
        const short = d.on_site < d.contracted;
        return (
          <g
            key={d.date}
            role="button"
            tabIndex={0}
            aria-label={`${d.date}: ${d.on_site} on site, ${d.out} out, ${d.open} open`}
            onClick={() => onPick(d.date)}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onPick(d.date)}
            style={{ cursor: "pointer" }}
          >
            <rect x={x(i) - 12} y={top} width={24} height={height - top} fill="transparent" />
            {isSelected && <line x1={x(i)} x2={x(i)} y1={top - 6} y2={height - bottom} stroke="#16171a" strokeDasharray="2 3" />}
            {short && (
              <text x={x(i)} y={y(d.on_site) + 16} fontSize="10" textAnchor="middle" fill="#16171a" fontWeight={600}>
                {d.on_site}/{d.contracted}
              </text>
            )}
            <circle
              cx={x(i)}
              cy={y(d.on_site)}
              r={isSelected ? 5 : d.out ? 4 : 2.5}
              fill={isSelected || short ? "#16171a" : d.out ? "#fff" : "#16171a"}
              stroke="#16171a"
              strokeWidth={1.5}
            />
            {d.out > 0 && !short && (
              <text x={x(i)} y={y(d.on_site) - 9} fontSize="10" textAnchor="middle" fill="#16171a">
                {d.out} out
              </text>
            )}
            <text x={x(i)} y={height - bottom + 16} fontSize="10" textAnchor="middle" fill={isSelected ? "#16171a" : "#696b73"} fontWeight={isSelected ? 600 : 400}>
              {Number(d.date.slice(8, 10))}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

interface Line {
  key: string;
  name: string;
  start: string | null;
  end: string | null;
  note: string | null; // set only for exceptions
}

const SLACK_MINUTES = 10;

export function shiftLines(board: Board): Line[] {
  const start = new Date(board.shift_start).getTime();
  const end = start + 8 * 3600_000;
  const late = (t: string | null) => t !== null && new Date(t).getTime() > start + SLACK_MINUTES * 60_000;
  const early = (t: string | null) => t !== null && new Date(t).getTime() < end - SLACK_MINUTES * 60_000;

  const assigned = board.assigned.map((a: Assigned): Line => {
    let note: string | null = null;
    if (a.status === "out") note = a.code ? `Out · ${codeText(a.code)}` : `Out · ${a.reason ?? "reason not recorded"}`;
    else if (!a.clock_in) note = "No clock-in";
    else if (!a.clock_out) note = `In ${formatTime(a.clock_in)}, no clock-out`;
    else if (late(a.clock_in)) note = `Late in ${formatTime(a.clock_in)}`;
    else if (early(a.clock_out)) note = `Left ${formatTime(a.clock_out)}`;
    return { key: a.employee_id, name: a.name, start: a.status === "out" ? null : a.clock_in, end: a.status === "out" ? null : a.clock_out, note };
  });
  const covering = board.covering
    .filter((c: Coverage) => c.covering)
    .map((c): Line => ({
      key: c.posting_id,
      name: c.covering!.name,
      start: c.covering!.clock_in,
      end: c.covering!.clock_out,
      note: `${c.fill_type === "OT" ? "Overtime" : "Covering"} for ${c.absent_as_posted ?? "absent employee"}`,
    }));
  const unexpected = board.unexpected.map((u): Line => ({ key: `u-${u.employee_id}`, name: u.name, start: u.clock_in, end: u.clock_out, note: "Not assigned or posted here" }));
  return [...assigned, ...covering, ...unexpected];
}

export function TonightChart({ board }: { board: Board }) {
  const start = new Date(board.shift_start).getTime();
  const from = start - 2 * 3600_000;
  const to = start + 9 * 3600_000;
  const pct = (t: string) => Math.min(100, Math.max(0, ((new Date(t).getTime() - from) / (to - from)) * 100));
  const lines = shiftLines(board);
  const ticks = Array.from({ length: 4 }, (_, i) => from + 3600_000 + i * 3 * 3600_000);

  return (
    <div className="tonight">
      {lines.map((l) => (
        <div key={l.key} className={`tonight-row${l.note ? " exception" : ""}`}>
          <span className="who">{l.name}</span>
          <span className="track">
            <span className="shift-window" style={{ left: `${((start - from) / (to - from)) * 100}%`, width: `${(8 / 11) * 100}%` }} />
            {l.start && (
              <span className="span" style={{ left: `${pct(l.start)}%`, right: `${100 - pct(l.end ?? new Date(to).toISOString())}%` }} />
            )}
          </span>
          <span className="note">{l.note ?? `${formatTime(l.start)}–${formatTime(l.end)}`}</span>
        </div>
      ))}
      <div className="tonight-row axis">
        <span />
        <span className="track">
          {ticks.map((t) => (
            <span key={t} style={{ left: `${((t - from) / (to - from)) * 100}%` }}>
              {new Date(t).toTimeString().slice(0, 5)}
            </span>
          ))}
        </span>
        <span />
      </div>
    </div>
  );
}
