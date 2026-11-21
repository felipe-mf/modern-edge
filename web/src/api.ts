// Calls to the Northgate API. The screens only show what the pipeline wrote; nothing is recomputed here.

export type Row = Record<string, unknown>;

export interface RunInfo {
  period: string;
  period_start: string;
  period_end: string;
  payroll_dry_run: boolean;
  buildings: string[];
}

export interface Times {
  clock_in: string | null;
  clock_out: string | null;
  punch_refs: string[];
}

export interface Person extends Times {
  employee_id: string;
  name: string;
  job_class: string | null;
  employment_type: string | null;
  source_ref: string;
}

export interface Assigned extends Person {
  status: "on_site" | "out" | "no_punch";
  reason?: string;
  code?: string | null;
  decision?: string | null;
  callout_ref?: string;
  posting_id?: string | null;
  assignment_basis?: string;
}

export interface Coverage {
  posting_id: string;
  reason: string;
  status: string;
  fill_type: string | null;
  absent_as_posted: string | null;
  source_ref: string;
  covering: Person | null;
}

export interface Summary {
  assigned: number;
  on_site: number;
  out: number;
  covered: number;
  open: number;
}

export interface Board {
  building: string;
  date: string;
  shift: "day" | "night";
  contracted: number;
  scheduled_day: boolean;
  shift_start: string;
  assigned: Assigned[];
  covering: Coverage[];
  unexpected: Person[];
  summary: Summary;
}

export interface MonthDay extends Summary {
  date: string;
  contracted: number;
}

export interface KpiPanel {
  run: RunInfo;
  metrics: Record<string, string>;
  buildings: Row[];
  ar_aging: { bucket: string; open_amount: number }[];
}

export interface KpiDetail {
  building: string;
  metric: string;
  value: unknown;
  definition: string;
  sections: { title: string; records: Row[] }[];
}

export interface ReviewQueue {
  absences: Row[];
  exceptions: Row[];
}

export interface ChatAnswer {
  answer: string;
  sources: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json();
}

const q = encodeURIComponent;

export const api = {
  run: () => request<RunInfo>("/api/run"),
  board: (building: string, day: string, shift: string) =>
    request<Board>(`/api/buildings/${q(building)}/board?day=${day}&shift=${shift}`),
  month: (building: string, shift: string) =>
    request<MonthDay[]>(`/api/buildings/${q(building)}/month?shift=${shift}`),
  kpis: () => request<KpiPanel>("/api/kpis"),
  kpiDetail: (building: string, metric: string) =>
    request<KpiDetail>(`/api/kpis/${q(building)}/${q(metric)}`),
  arBucket: (bucket: string) => request<Row[]>(`/api/ar-aging/${q(bucket)}`),
  payroll: () => request<Row[]>("/api/payroll-submissions"),
  records: (ref: string) => request<{ table: string; record: Row }[]>(`/api/records?ref=${q(ref)}`),
  review: () => request<ReviewQueue>("/api/review"),
  reviewAbsence: (id: number, action: "approve" | "dismiss", note: string) =>
    request<Row>(`/api/review/absences/${id}`, { method: "POST", body: JSON.stringify({ action, note }) }),
  reviewException: (item_key: string, action: "acknowledge" | "dismiss", note: string) =>
    request<Row>("/api/review/exceptions", { method: "POST", body: JSON.stringify({ item_key, action, note }) }),
  chat: (messages: { role: string; content: string }[]) =>
    request<ChatAnswer>("/api/chat", { method: "POST", body: JSON.stringify({ messages }) }),
};
