// Small display helpers. They only format; they never change a value.

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export function formatMoney(value: unknown): string {
  return value === null || value === undefined || value === "" ? "—" : money.format(Number(value));
}

export function formatTime(value: string | null | undefined): string {
  return value ? value.slice(11, 16) : "—";
}

export function formatDate(value: string | null | undefined, withWeekday = false): string {
  if (!value) return "—";
  const day = new Date(`${value.slice(0, 10)}T12:00:00`);
  return day.toLocaleDateString("en-US", {
    weekday: withWeekday ? "short" : undefined,
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

// Stored words that read better in sentence case: lower-case codes ("own_illness") and the
// upper-case statuses some systems send ("POSTED", "EXPIRED") under these field names.
const WORD_FIELDS = ["reason", "decision", "status", "final_status", "line_type", "pricing_basis"];
const SHIFTS: Record<string, string> = { D: "Day", N: "Night", day: "Day", night: "Night" };

/** Any stored value as people read it. The one place where fields turn into words, so the same field
 *  reads the same in every table, panel and source sheet. */
export function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (key === "code") return codeText(value);
  if (key === "shift") return SHIFTS[String(value)] ?? String(value);
  if (key === "fill_type") return value === "OT" ? "Overtime" : label(String(value).toLowerCase());
  // Contract markups are stored in percent points (12 = 12%); the KPI rates and percentages are fractions.
  if (key === "markup_pct") return `${Number(value)}%`;
  if (/_pct$|^fill_rate$|^callout_rate$/.test(key)) return `${(Number(value) * 100).toFixed(1)}%`;
  if (/amount|revenue|cost|dollars|margin$|base_rate$|_fee$|billable/.test(key) && !/count/.test(key))
    return formatMoney(value);
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value))
    return `${formatDate(value)} ${formatTime(value)}`;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDate(value);
  if (WORD_FIELDS.includes(key)) return label(String(value).toLowerCase());
  if (typeof value === "string" && /^[a-z]+(_[a-z]+)*$/.test(value)) return label(value);
  return String(value);
}

// Field names whose plain spelling would mislead or run long.
const FIELD_LABELS: Record<string, string> = {
  name_as_written: "Name as reported",
  absent_employee_text: "Absent (as posted)",
  covering_employee: "Covering",
  covering_name: "Covering",
  contact_at: "Reported",
  fill_type: "Fill",
  doc_no: "Document",
  invoice_no: "Invoice",
  overtime_dollars: "Overtime $",
  billable_amount: "Billable",
  open_amount: "Open",
  days_past_due: "Days late",
};

export function label(key: string): string {
  if (FIELD_LABELS[key]) return FIELD_LABELS[key];
  const text = key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Payroll absence codes and what they mean (Article 14 of the union agreement). */
export const CODES: Record<string, string> = {
  SKP: "Sick, paid",
  SKU: "Sick, unpaid",
  LTN: "Late notice, unpaid",
  CLN: "Clinic visit",
  BRV: "Bereavement",
  JRY: "Jury duty",
  FEM: "Family emergency",
  PER: "Personal, unpaid",
};

export function codeText(code: unknown): string {
  return code ? `${code} · ${CODES[String(code)] ?? "unknown code"}` : "—";
}
