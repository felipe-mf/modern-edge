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

export function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (/_pct$|^fill_rate$|^callout_rate$/.test(key)) return `${(Number(value) * 100).toFixed(1)}%`;
  if (/amount|revenue|cost|dollars|margin$|base_rate$|billable/.test(key) && !/count/.test(key))
    return formatMoney(value);
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value))
    return `${formatDate(value)} ${formatTime(value)}`;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDate(value);
  return String(value);
}

export function label(key: string): string {
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
