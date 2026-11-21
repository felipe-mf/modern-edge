// Every source_ref on screen opens the original records it points to, from any table.

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { createContext, useContext } from "react";

import { api, type Row } from "../api";
import { formatValue, label } from "../format";
import { ErrorNote, Skeleton } from "./States";

export const SourceContext = createContext<(ref: string) => void>(() => {});

export function RefLink({ value, text }: { value: unknown; text?: string }) {
  const open = useContext(SourceContext);
  if (value === null || value === undefined || value === "") return <span className="secondary">—</span>;
  return (
    <button
      className="ref"
      onClick={(event) => {
        event.stopPropagation();
        open(String(value));
      }}
    >
      {text ?? String(value)}
    </button>
  );
}

const TABLE_NAMES: Record<string, string> = {
  callout_log: "Reception call-out log",
  chat_messages: "Managers' chat",
  callout_events: "Call-out decision",
  payroll_ledger: "Payroll ledger",
  dispatch_postings: "Dispatch posting",
  hr_employees: "HR roster",
  invoice_lines: "Invoice line",
  gl_lines: "GL labor line",
  ar_items: "AR open item",
  time_punches: "Time clock punch",
};

/** The fields worth reading in a stored record: not the row id, not the reference already in the
 *  sheet's title, and not nested data (form fields, model extraction, event logs), which is kept for
 *  the pipeline and reads as raw JSON. */
function readableFields(record: Row, sourceRef: string): [string, unknown][] {
  return Object.entries(record).filter(
    ([key, value]) => key !== "id" && value !== null && value !== "" && typeof value !== "object" && String(value) !== sourceRef,
  );
}

export function SourceSheet({ sourceRef, onClose }: { sourceRef: string; onClose: () => void }) {
  const found = useQuery({ queryKey: ["records", sourceRef], queryFn: () => api.records(sourceRef) });
  return (
    <aside className="sheet glass" aria-label="Source records">
      <header>
        <h2>Source: {sourceRef}</h2>
        <button className="btn icon" onClick={onClose} aria-label="Close sources">
          <X />
        </button>
      </header>
      <div className="body">
        {found.isPending && <Skeleton rows={6} />}
        {found.isError && <ErrorNote error={found.error} />}
        {found.data?.length === 0 && (
          <p className="empty">No stored record carries this reference. It may name a file line that was read but not kept.</p>
        )}
        {found.data?.map(({ table, record }, i) => (
          <section key={`${table}-${i}`} className="source-block">
            <h3>{TABLE_NAMES[table] ?? label(table)}</h3>
            <dl className="facts">
              {readableFields(record, sourceRef).map(([key, value]) => (
                <Fact key={key} name={key} value={value} />
              ))}
            </dl>
          </section>
        ))}
      </div>
    </aside>
  );
}

/** One label and value pair in a details list (`dl.facts`). */
export function Fact({ name, value }: { name: string; value: unknown }) {
  return (
    <>
      <dt>{label(name)}</dt>
      <dd>{formatValue(name, value)}</dd>
    </>
  );
}
