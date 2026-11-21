// Payroll submissions: every absence and what was written to payroll, or why it was held.

import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useState } from "react";

import { api, type Row } from "../api";
import { Fact, RefLink } from "../components/Sources";
import { ErrorNote, Skeleton } from "../components/States";
import { CODES, codeText, formatDate, formatValue } from "../format";
import { revealOnNarrow } from "../reveal";

type Filter = "all" | "written" | "held_for_review";

const FIELDS = ["employee_id", "decision", "reason", "contact_at", "contact_basis", "notice_hours", "code_reason", "hold_reason", "payroll_id", "submission_id", "final_status", "confidence", "evidence", "duplicate_of", "posting_id"];

/** Lower case without accents, so "gonzalez" finds "González". */
function plain(text: string): string {
  return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

/** True when every word typed appears in the employee's reported name or ID, in any order
 *  ("maria gonz", "E10036", "10036"). */
function matchesSearch(r: Row, query: string): boolean {
  const haystack = plain(`${r.name_as_written ?? ""} ${r.employee_id ?? ""}`);
  return plain(query).split(/\s+/).filter(Boolean).every((word) => haystack.includes(word));
}

export function Payroll() {
  const rows = useQuery({ queryKey: ["payroll"], queryFn: api.payroll });
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Row | null>(null);

  if (rows.isError) return <ErrorNote error={rows.error} />;
  if (!rows.data) return <div className="glass tile"><Skeleton rows={10} /></div>;
  // The search narrows every list; the counts on the filter buttons follow it.
  const found = rows.data.filter((r) => matchesSearch(r, query));
  const shown = found.filter((r) => filter === "all" || r.decision === filter);
  const count = (f: Filter) => found.filter((r) => f === "all" || r.decision === f).length;

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
        <div className="search">
          <Search aria-hidden="true" />
          <input
            type="search"
            aria-label="Search by employee name or ID"
            placeholder="Search by employee name or ID"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setQuery("")}
          />
          {query && (
            <button className="btn icon" onClick={() => setQuery("")} aria-label="Clear search">
              <X />
            </button>
          )}
        </div>
        {shown.length === 0 && (
          <p className="empty">
            {query ? `No submission for “${query.trim()}”${filter === "all" ? "" : " in this list"}. Check the spelling, or search by employee ID.` : "No submission in this list."}
          </p>
        )}
        <div className="table-wrap tall-scroll" hidden={shown.length === 0}>
          <table>
            <thead>
              <tr>
                <th>Date</th><th>Employee</th><th>Building</th><th>Code</th><th>Result</th>
              </tr>
            </thead>
            <tbody className="rows-in">
              {shown.map((r) => (
                <tr key={String(r.id)} className="clickable" aria-selected={selected?.id === r.id} onClick={() => {
                  setSelected(r);
                  revealOnNarrow(".split-grid .record");
                }}>
                  <td>{formatDate(r.absence_date as string)}</td>
                  <td className="stack">
                    <span className="strong">{String(r.name_as_written ?? "—")}</span>
                    <span className="secondary">{String(r.employee_id ?? "not matched")}</span>
                  </td>
                  <td className="stack">
                    <span>{String(r.building ?? "—")}</span>
                    {r.shift ? <span className="secondary">{formatValue("shift", r.shift)} shift</span> : null}
                  </td>
                  <td className="stack">
                    <span className="strong">{String(r.code ?? "—")}</span>
                    <span className="secondary">{CODES[String(r.code)] ?? ""}</span>
                  </td>
                  <td>
                    {r.decision === "written" ? (
                      <span className="status ok">{r.final_status ? formatValue("final_status", r.final_status) : "Written"}</span>
                    ) : (
                      <span className="status warn">{formatValue("decision", r.decision)}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className={`glass tile record${selected ? "" : " idle"}`} aria-label="Submission detail">
        <div className="tile-title">Detail</div>
        {!selected && <p className="empty">Pick a row to see how the code was decided and what payroll answered.</p>}
        {selected && (
          <div className="swap-in" key={String(selected.id)}>
            <div className="record-head">
              <span className="name">{String(selected.name_as_written ?? "—")}</span>
              <span className="secondary">{[formatDate(selected.absence_date as string, true), selected.shift ? `${formatValue("shift", selected.shift)} shift` : null, selected.building]
                .filter(Boolean)
                .join(" · ")}</span>
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
          </div>
        )}
      </section>
    </div>
  );
}
