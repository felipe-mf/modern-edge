// A table for any list of records (KPI drill-downs, AR items). Shows the most useful columns and
// always ends with the record's source, which opens the original line.

import type { Row } from "../api";
import { formatValue, label } from "../format";
import { RefLink } from "./Sources";

const HIDDEN = new Set(["id", "source_ref", "record_ref", "events", "evidence", "raw", "item_key", "review"]);

export function RecordsTable({ rows, columns, max = 9 }: { rows: Row[]; columns?: string[]; max?: number }) {
  if (rows.length === 0) return <p className="empty">No records behind this figure.</p>;
  const shown = (columns ?? Object.keys(rows[0]).filter((key) => !HIDDEN.has(key))).slice(0, max);
  return (
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
                <td key={key} className={isNumber(row[key]) ? "num" : undefined}>
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
  );
}

function isNumber(value: unknown): boolean {
  return typeof value === "number";
}
