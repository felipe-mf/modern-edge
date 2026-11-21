// Payroll submissions: every absence and what was written to payroll, or why it was held.

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Row } from "../api";
import { RefLink } from "../components/Sources";
import { ErrorNote, Skeleton } from "../components/States";
import { codeText, formatDate, formatValue, label } from "../format";

type Filter = "all" | "written" | "held_for_review";

const FIELDS = ["reason", "contact_at", "contact_basis", "notice_hours", "code_reason", "hold_reason", "payroll_id", "submission_id", "final_status", "confidence", "evidence", "duplicate_of", "posting_id"];

export function Payroll() {
  const rows = useQuery({ queryKey: ["payroll"], queryFn: api.payroll });
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Row | null>(null);

  if (rows.isError) return <ErrorNote error={rows.error} />;
  if (!rows.data) return <div className="glass tile"><Skeleton rows={10} /></div>;
  const shown = rows.data.filter((r) => filter === "all" || r.decision === filter);
  const count = (f: Filter) => rows.data.filter((r) => f === "all" || r.decision === f).length;

  return (
    <div className="split-grid">
      <section className="glass tile" aria-label="Payroll submissions">
        <div className="tile-title">
          Payroll submissions
          <span className="aside segmented small">
            {(["all", "written", "held_for_review"] as Filter[]).map((f) => (
              <button key={f} className="btn" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                {f === "all" ? "All" : f === "written" ? "Written" : "Held"} {count(f)}
              </button>
            ))}
          </span>
        </div>
        <div className="table-wrap tall-scroll">
          <table>
            <thead>
              <tr>
                <th>Date</th><th>Name as reported</th><th>ID</th><th>Building</th><th>Shift</th><th>Code</th><th>Decision</th><th>Payroll</th><th>Source</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={String(r.id)} className="clickable" aria-selected={selected?.id === r.id} onClick={() => setSelected(r)}>
                  <td>{formatDate(r.absence_date as string)}</td>
                  <td className="strong">{String(r.name_as_written ?? "—")}</td>
                  <td>{String(r.employee_id ?? "—")}</td>
                  <td>{String(r.building ?? "—")}</td>
                  <td>{String(r.shift ?? "—")}</td>
                  <td className="strong">{String(r.code ?? "—")}</td>
                  <td>
                    <span className={r.decision === "written" ? "status" : "status solid"}>{label(String(r.decision ?? "—"))}</span>
                  </td>
                  <td className="secondary">{r.submission_id ? `${r.submission_id} · ${r.final_status ?? ""}` : "—"}</td>
                  <td><RefLink value={r.record_ref} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="glass tile record" aria-label="Submission detail">
        <div className="tile-title">Detail</div>
        {!selected && <p className="empty">Pick a row to see how the code was decided and what payroll answered.</p>}
        {selected && (
          <>
            <div className="record-head">
              <span className="name">{String(selected.name_as_written ?? "—")}</span>
              <span className="secondary">{formatDate(selected.absence_date as string, true)} · {String(selected.shift ?? "")} · {String(selected.building ?? "")}</span>
            </div>
            <div className="code-line">{codeText(selected.code)}</div>
            <dl className="facts">
              {FIELDS.filter((f) => selected[f] !== null && selected[f] !== undefined && selected[f] !== "").map((f) => (
                <Fact key={f} name={f} value={selected[f]} />
              ))}
            </dl>
            <div className="sources">
              <div className="secondary">Sources</div>
              <RefLink value={selected.record_ref} />
              {Boolean(selected.posting_id) && <RefLink value={`dispatch posting ${selected.posting_id}`} />}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function Fact({ name, value }: { name: string; value: unknown }) {
  return (
    <>
      <dt>{label(name === "contact_at" ? "reported" : name)}</dt>
      <dd>{formatValue(name, value)}</dd>
    </>
  );
}
