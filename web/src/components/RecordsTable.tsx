// A table for any list of records (KPI drill-downs, AR items). Records carry many fields; the table
// shows only the few that explain the figure, in reading order: when, who, what, how much. A field
// that is the same on every row is said once above the table instead of repeated in a column.
// Every row ends with its source, which opens the full original record.

import type { Row } from "../api";
import { formatValue, label } from "../format";
import { RefLink } from "./Sources";

const WHEN = ["absence_date", "shift_date", "service_date", "week_ending", "invoice_date", "doc_date", "agreement_date", "effective_date"];
const WHO = ["name_as_written", "covering_name", "covering_employee", "name", "absent_employee_text", "customer_name", "client_name", "customer_no"];
// Fields that decide whether a row counts toward the figure, or whose it is: shown whenever present.
const DECIDES = ["active_at_period_end", "coverage_billable", "entity", "doc_type"];
const WHAT = [
  "shift", "reason", "code", "decision", "status", "fill_type", "job_class", "line_type", "account_name",
  "description", "doc_no", "invoice_no", "pricing_basis", "day_posts", "night_posts", "hire_date",
  "termination_date", "due_date",
];
const HOW_MUCH = ["scheduled_shifts", "overtime_hours", "days_past_due", "base_rate", "markup_pct", "monthly_fee", "overtime_dollars", "billable_amount", "amount", "open_amount"];

function columnsFor(rows: Row[]): { shown: string[]; constant: string[] } {
  const present = (key: string) => rows.some((r) => r[key] !== null && r[key] !== undefined && r[key] !== "");
  const same = (key: string) => rows.length > 1 && rows.every((r) => String(r[key]) === String(rows[0][key]));
  const constant: string[] = [];
  const pick = (keys: string[], limit: number) => {
    const out: string[] = [];
    for (const key of keys) {
      if (out.length === limit || !present(key)) continue;
      if (same(key)) constant.push(key);
      else out.push(key);
    }
    return out;
  };
  // Two dates at most: a section can mix rows dated differently (agreements and their amendments).
  const shown = [...pick(WHEN, 2), ...pick(WHO, 1), ...pick(DECIDES, 2), ...pick(WHAT, 3), ...pick(HOW_MUCH, 2)];
  return { shown, constant };
}

const isNumber = (value: unknown) => typeof value === "number";

export function RecordsTable({ rows }: { rows: Row[] }) {
  if (rows.length === 0) return <p className="empty">No records behind this figure.</p>;
  const { shown, constant } = columnsFor(rows);
  return (
    <>
      {constant.length > 0 && (
        <p className="secondary table-caption">
          Every row: {constant.map((key) => `${label(key).toLowerCase()} ${formatValue(key, rows[0][key])}`).join(" · ")}
        </p>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {shown.map((key) => (
                <th key={key} className={isNumber(rows[0][key]) ? "num" : undefined}>
                  {label(key)}
                </th>
              ))}
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {shown.map((key) => (
                  <td key={key} className={isNumber(row[key]) ? "num" : key === "description" ? "wrap" : undefined}>
                    {formatValue(key, row[key])}
                  </td>
                ))}
                <td>
                  <RefLink value={row.record_ref ?? row.source_ref} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
