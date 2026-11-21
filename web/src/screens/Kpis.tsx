// KPI panel per building with drill-down: every figure opens the records it was computed from.
// AR aging by bucket, each bucket opening its open items.

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Row } from "../api";
import { RecordsTable } from "../components/RecordsTable";
import { ErrorNote, Skeleton } from "../components/States";
import { formatMoney, formatValue, label } from "../format";

const GROUPS: { title: string; metrics: string[] }[] = [
  { title: "Headcount", metrics: ["contracted_headcount", "active_headcount", "headcount_variance"] },
  { title: "Call-outs and coverage", metrics: ["scheduled_shifts", "callout_shifts", "callout_rate", "fill_rate", "overtime_hours", "overtime_dollars"] },
  { title: "Money", metrics: ["revenue", "labor_cost", "gross_margin", "gross_margin_pct", "unbilled_coverage_count", "unbilled_coverage_dollars"] },
];

const SHORT: Record<string, string> = {
  contracted_headcount: "Contracted",
  active_headcount: "Active",
  headcount_variance: "Variance",
  scheduled_shifts: "Scheduled",
  callout_shifts: "Call-outs",
  callout_rate: "Call-out rate",
  fill_rate: "Fill rate",
  overtime_hours: "OT hours",
  overtime_dollars: "OT $",
  revenue: "Revenue",
  labor_cost: "Labor cost",
  gross_margin: "Margin",
  gross_margin_pct: "Margin %",
  unbilled_coverage_count: "Unbilled",
  unbilled_coverage_dollars: "Unbilled $",
};

const BUCKETS: Record<string, string> = { current: "Current", "1_30": "1–30 days", "31_60": "31–60", "61_90": "61–90", over_90: "Over 90" };

export function Kpis() {
  const panel = useQuery({ queryKey: ["kpis"], queryFn: api.kpis });
  const [pick, setPick] = useState<{ building: string; metric: string } | null>(null);
  const [bucket, setBucket] = useState<string | null>(null);

  if (panel.isError) return <ErrorNote error={panel.error} />;
  if (!panel.data) return <div className="glass tile"><Skeleton rows={8} /></div>;
  const { buildings, metrics, ar_aging } = panel.data;
  const total = ar_aging.reduce((sum, b) => sum + Number(b.open_amount), 0);

  return (
    <div className="kpi-grid">
      <section className="glass tile kpi-table" aria-label="KPIs by building">
        <div className="tile-title">
          KPIs by building<span className="aside">click any figure to see the records behind it</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th rowSpan={2}>Building</th>
                {GROUPS.map((g) => (
                  <th key={g.title} colSpan={g.metrics.length} className="group">
                    {g.title}
                  </th>
                ))}
              </tr>
              <tr>
                {GROUPS.flatMap((g) => g.metrics).map((m) => (
                  <th key={m} className="num" title={metrics[m]}>
                    {SHORT[m]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {buildings.map((row: Row) => (
                <tr key={String(row.building)}>
                  <td className="strong">{String(row.building)}</td>
                  {GROUPS.flatMap((g) => g.metrics).map((m) => {
                    const active = pick?.building === row.building && pick?.metric === m;
                    return (
                      <td key={m} className="num">
                        <button
                          className={`cell${active ? " active" : ""}`}
                          aria-pressed={active}
                          onClick={() => setPick({ building: String(row.building), metric: m })}
                        >
                          {formatValue(m, row[m])}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="glass tile aging" aria-label="AR aging">
        <div className="tile-title">
          AR aging<span className="aside">open {formatMoney(total)}</span>
        </div>
        <ul className="buckets">
          {ar_aging.map((b) => (
            <li key={b.bucket}>
              <button className="bucket" aria-pressed={bucket === b.bucket} onClick={() => setBucket(bucket === b.bucket ? null : b.bucket)}>
                <span>{BUCKETS[b.bucket] ?? b.bucket}</span>
                <span className="meter" aria-hidden="true">
                  <span style={{ width: `${total ? (Math.max(0, Number(b.open_amount)) / total) * 100 : 0}%` }} />
                </span>
                <span className="strong">{formatMoney(b.open_amount)}</span>
              </button>
            </li>
          ))}
        </ul>
        {bucket && <BucketItems bucket={bucket} />}
      </section>

      <section className="glass tile detail" aria-label="Figure detail">
        {pick ? <Detail {...pick} /> : <p className="empty">Pick a figure in the table: its definition and every record behind it appear here.</p>}
      </section>
    </div>
  );
}

function Detail({ building, metric }: { building: string; metric: string }) {
  const detail = useQuery({ queryKey: ["kpi", building, metric], queryFn: () => api.kpiDetail(building, metric) });
  if (detail.isError) return <ErrorNote error={detail.error} />;
  if (!detail.data) return <Skeleton rows={6} />;
  const d = detail.data;
  return (
    <>
      <div className="tile-title">
        {building} · {label(metric)}
        <span className="aside">{formatValue(metric, d.value)}</span>
      </div>
      <p className="secondary definition">{d.definition}</p>
      {d.sections.map((s) => (
        <div key={s.title} className="section">
          <div className="section-title">
            {s.title} <span className="secondary">{s.records.length} records</span>
          </div>
          <RecordsTable rows={s.records} />
        </div>
      ))}
    </>
  );
}

function BucketItems({ bucket }: { bucket: string }) {
  const items = useQuery({ queryKey: ["ar", bucket], queryFn: () => api.arBucket(bucket) });
  if (items.isError) return <ErrorNote error={items.error} />;
  if (!items.data) return <Skeleton rows={3} />;
  return <RecordsTable rows={items.data} max={6} />;
}
