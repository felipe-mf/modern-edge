// A month calendar to jump straight to a day. Only weekdays in the run's period can be picked
// (no shifts are scheduled on weekends); days below the contracted posts carry a small mark.

import { CalendarDays } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { formatDate } from "../format";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Every month between the first and last day, as "YYYY-MM". */
function monthsBetween(first: string, last: string): string[] {
  const out: string[] = [];
  for (let d = new Date(`${first.slice(0, 7)}-01T12:00:00`); d <= new Date(`${last}T12:00:00`); d.setMonth(d.getMonth() + 1)) {
    // From the local date, not toISOString (UTC), which can fall in the previous month east of UTC+12.
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  }
  return out;
}

/** The cells of a month grid starting on Monday: null for the blanks before the 1st. */
function monthCells(month: string): (string | null)[] {
  const first = new Date(`${month}-01T12:00:00`);
  const blanks = (first.getDay() + 6) % 7; // Monday = 0
  const length = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  const days = Array.from({ length }, (_, i) => `${month}-${String(i + 1).padStart(2, "0")}`);
  return [...Array(blanks).fill(null), ...days];
}

export function DatePicker({ value, days, short, onPick }: { value: string; days: string[]; short: Set<string>; onPick: (day: string) => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const allowed = new Set(days);

  // Close on a click outside or on Escape.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="datepicker" ref={box}>
      <button className="btn date" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}>
        <CalendarDays aria-hidden="true" />
        {formatDate(value, true)}
      </button>
      {open && (
        <div className="calendar" role="dialog" aria-label="Pick a day">
          {monthsBetween(days[0], days[days.length - 1]).map((month) => (
            <div key={month} className="calendar-month">
              <div className="calendar-title">
                {new Date(`${month}-01T12:00:00`).toLocaleDateString("en-US", { month: "long", year: "numeric" })}
              </div>
              <div className="calendar-grid">
                {WEEKDAYS.map((w) => (
                  <span key={w} className="calendar-weekday">
                    {w}
                  </span>
                ))}
                {monthCells(month).map((day, i) =>
                  day === null ? (
                    <span key={`blank-${i}`} />
                  ) : (
                    <button
                      key={day}
                      className="calendar-day"
                      disabled={!allowed.has(day)}
                      aria-pressed={day === value}
                      aria-label={`${formatDate(day, true)}${short.has(day) ? ", short-staffed" : ""}`}
                      onClick={() => {
                        onPick(day);
                        setOpen(false);
                      }}
                    >
                      {Number(day.slice(8, 10))}
                      {short.has(day) && <span className="calendar-mark" aria-hidden="true" />}
                    </button>
                  ),
                )}
              </div>
            </div>
          ))}
          <p className="secondary calendar-legend">
            <span className="calendar-mark" aria-hidden="true" /> below contracted posts · weekends have no shifts
          </p>
        </div>
      )}
    </div>
  );
}
